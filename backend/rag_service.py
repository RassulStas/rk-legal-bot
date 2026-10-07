"""RAG service: ChromaDB vector store + sentence-transformers embeddings.

Pipeline:
1. On startup, ingest_documents() scans backend/legal_docs (*.txt / *.md),
   chunks the text, embeds the chunks with a multilingual SentenceTransformer
   and stores them in the persistent ChromaDB collection 'rk_laws'.
2. retrieve_context(query) embeds the user's chat message and returns the
   top-k most relevant legal chunks as a single combined context block,
   or None when the store is empty / nothing is semantically close enough.
"""

import hashlib
import logging
import os
import re
from pathlib import Path

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

logger = logging.getLogger("rk_legal_bot.rag")

BACKEND_DIR = Path(__file__).parent
LEGAL_DOCS_DIR = Path(os.environ.get("RAG_DOCS_DIR", BACKEND_DIR / "legal_docs"))
CHROMA_DIR = Path(os.environ.get("RAG_CHROMA_PATH", BACKEND_DIR / "chroma_db"))
COLLECTION_NAME = "rk_laws"
EMBEDDING_MODEL = os.environ.get(
    "RAG_EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"
)

CHUNK_SIZE = int(os.environ.get("RAG_CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.environ.get("RAG_CHUNK_OVERLAP", "150"))
# Cosine distance cutoff (0 = identical, 2 = opposite). On-topic queries
# score ≤ ~0.35, unrelated small-talk ≥ ~0.79 with the default model.
MAX_DISTANCE = float(os.environ.get("RAG_MAX_DISTANCE", "0.6"))

_COLLECTION_METADATA = {"hnsw:space": "cosine"}

_DOC_EXTENSIONS = (".txt", ".md")

_model: SentenceTransformer | None = None
_client: chromadb.ClientAPI | None = None
_collection: chromadb.Collection | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        logger.info("Loading embedding model %s", EMBEDDING_MODEL)
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
    return _client


def _collection_names(client: chromadb.ClientAPI) -> set[str]:
    # chromadb < 0.6 returned names as strings, newer versions return
    # Collection objects — support both.
    return {c if isinstance(c, str) else c.name for c in client.list_collections()}


def _get_collection() -> chromadb.Collection:
    global _collection
    if _collection is None:
        _collection = _get_client().get_or_create_collection(
            name=COLLECTION_NAME, metadata=dict(_COLLECTION_METADATA)
        )
    return _collection


def _recreate_collection(fingerprint: str | None) -> chromadb.Collection:
    global _collection
    client = _get_client()
    if COLLECTION_NAME in _collection_names(client):
        client.delete_collection(COLLECTION_NAME)
    metadata = dict(_COLLECTION_METADATA)
    if fingerprint:
        metadata["fingerprint"] = fingerprint
    _collection = client.get_or_create_collection(name=COLLECTION_NAME, metadata=metadata)
    return _collection


def _doc_files() -> list[Path]:
    if not LEGAL_DOCS_DIR.exists():
        return []
    return sorted(
        p
        for p in LEGAL_DOCS_DIR.iterdir()
        if p.suffix.lower() in _DOC_EXTENSIONS
        and not p.name.upper().startswith("README")
    )


def _fingerprint(files: list[Path]) -> str:
    parts = [(p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in files]
    return hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()


ARTICLE_START = re.compile(r"^(##\s*Статья\s+\d+|\*\*Статья\s+\d+\b)")

_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$", re.MULTILINE)


def _linearize_tables(text: str) -> str:
    """Turn markdown table rows into prose so they embed meaningfully.

    Pipe tables (e.g. tax rate scales) embed as noise, which buried the
    ИПН rate article of НК ст. 363 below top-20 despite a topical query.
    """

    def repl(match: re.Match) -> str:
        cells = [c.strip() for c in match.group(1).split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            return ""  # markdown separator row
        return " — ".join(c for c in cells if c)

    return _TABLE_ROW.sub(repl, text)


# When a question explicitly names a code, restrict retrieval to that code's
# documents so chunks from other codes don't dilute the context. Each entry:
# (keywords, source filenames). Checked in order; first match wins.
_CODE_FILTERS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    # "налог" (not just "налогов") so e.g. "ставка земельного налога" lands
    # in the Tax Code instead of being swallowed by the земельн filter.
    (("налог", "ндс", "корпоративн", "социальн"), ("nalogoviy_kodeks_rk.md",)),
    (("предпринимат",), ("predprinimatelskiy_kodeks_rk.md",)),
    (("административн", "коап"), ("kodeks_administrativnykh_pravonarusheniy_rk.md",)),
    (("земельн",), ("zemelniy_kodeks_rk.md",)),
    # Must precede the гражданск entry: "гражданский процессуальный"
    # queries belong to ГПК, not the substantive Civil Code.
    (("процессуальн",), ("grazhdanskiy_protsessualnyy_kodeks_rk.md",)),
    (
        ("гражданск",),
        (
            "grazhdanskiy_kodeks_rk_obshaya_chast.md",
            "grazhdanskiy_kodeks_rk_osobennaya_chast.md",
        ),
    ),
    (("трудов", "заработн"), ("trudovoy_kodeks_rk.md",)),
]


def _code_filter(query: str) -> dict | None:
    q = query.lower()
    for keywords, sources in _CODE_FILTERS:
        if any(k in q for k in keywords):
            return {"source": {"$in": list(sources)}}
    return None


# Geographic/code/year filler in user questions ("в Казахстане", "2026",
# "по Налоговому кодексу РК") drags embeddings away from definitional
# articles — a bare "Ставки индивидуального подоходного налога" ranks
# НК ст. 363 at #2 where the full question ranks it #86. We embed both the
# raw and the stripped query and fuse the results.
_FILLER = re.compile(
    r"(?i)\b(20\d\d|рк|кодекс\w*|казахстан\w*|налого\w*|гражданск\w*|трудов\w*)\b"
)


def _fused_query_texts(query: str) -> list[str]:
    stripped = _FILLER.sub(" ", query)
    stripped = " ".join(stripped.split())
    texts = [query, stripped]
    # The Civil Code regulates lease largely through "имущественный наём"
    # norms (ГК ст. 540–564) while users ask about "аренда" — bridge the
    # lexical gap so the наём article surface. ГК ст. 556 otherwise ranks
    # below top-20 for "расторжение договора аренды".
    if "аренд" in query.lower() and "найм" not in query.lower():
        texts.append(re.sub(r"(?i)аренд\w*", "аренды (имущественного найма)", query, count=1))
        if stripped != query:
            texts.append(re.sub(r"(?i)аренд\w*", "аренды (имущественного найма)", stripped, count=1))
    # Termination of lease is regulated under the doctrinal title "по
    # требованию одной из сторон" (ГК ст. 556) — users ask "расторгнуть
    # аренду" without that phrase, and the article otherwise ranks below
    # the fusion cutoff against repeated "аренда предприятия" chunks.
    # A compact canonical phrase outperforms appending words to the noisy
    # full-sentence query (0.16 vs 0.30 cosine distance to ст. 556).
    if re.search(r"(?i)расторг|прекрат", query) and ("аренд" in query.lower() or "найм" in query.lower()):
        texts.append("расторжение договора имущественного найма по требованию одной из сторон")
    # "ИПН" alone does not bridge to "индивидуальный подоходный налог" in
    # the embedding space (НК ст. 363 falls out of the candidate pool);
    # the spelled-out form ranks it #1.
    if re.search(r"(?i)\bипн\b", query):
        texts.append(re.sub(r"(?i)\bипн\b", "индивидуального подоходного налога", query))
        if stripped != query:
            texts.append(re.sub(r"(?i)\bипн\b", "индивидуального подоходного налога", stripped))
    return list(dict.fromkeys(t for t in texts if t.strip()))


def _chunk_text(text: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", _linearize_tables(text)) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        # Flush at article boundaries so each chunk carries its article number
        # and definitional articles are not diluted by neighbouring ones.
        if current and ARTICLE_START.match(para):
            chunks.append(current)
            current = ""
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= CHUNK_SIZE:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(para) <= CHUNK_SIZE:
            current = para
        else:
            for i in range(0, len(para), CHUNK_SIZE - CHUNK_OVERLAP):
                piece = para[i : i + CHUNK_SIZE].strip()
                if piece:
                    chunks.append(piece)
            current = ""
    if current:
        chunks.append(current)
    return chunks


def ingest_documents(force: bool = False) -> int:
    """(Re)build the 'rk_laws' collection from LEGAL_DOCS_DIR.

    Idempotent: skips the rebuild when the folder fingerprint is unchanged.
    Returns the number of chunks stored in the collection.
    """
    files = _doc_files()
    fingerprint = _fingerprint(files)

    collection = _get_collection()
    if not force and collection.metadata and collection.metadata.get("fingerprint") == fingerprint:
        # A failed ingest leaves the new fingerprint on an emptied collection;
        # rebuild when documents exist but nothing made it into the store.
        if not files or collection.count() > 0:
            return collection.count()

    if files:
        chunks: list[str] = []
        metadatas: list[dict] = []
        ids: list[str] = []
        for path in files:
            text = path.read_text(encoding="utf-8")
            for idx, chunk in enumerate(_chunk_text(text)):
                chunks.append(chunk)
                metadatas.append({"source": path.name, "chunk": idx})
                ids.append(f"{path.name}:{idx}")

        if chunks:
            embeddings = _get_model().encode(chunks, show_progress_bar=False).tolist()
            collection = _recreate_collection(fingerprint)
            # Chroma caps a single add() well below our chunk count — batch.
            batch_size = 500
            for start in range(0, len(ids), batch_size):
                end = start + batch_size
                collection.add(
                    ids=ids[start:end],
                    documents=chunks[start:end],
                    metadatas=metadatas[start:end],
                    embeddings=embeddings[start:end],
                )
            logger.info(
                "RAG: ingested %d chunks from %d document(s) into '%s'",
                len(chunks),
                len(files),
                COLLECTION_NAME,
            )
            return collection.count()

    # No usable documents — keep the store empty so chat falls back gracefully.
    collection = _recreate_collection(fingerprint)
    return collection.count()


def retrieve_context(query: str, top_k: int = 3) -> str | None:
    """Return the top_k most relevant legal chunks for a chat message.

    Returns None if the store is empty or nothing passes the relevance
    threshold, letting the caller fall back to a context-free prompt.
    """
    collection = _get_collection()
    if collection.count() == 0 or not query.strip():
        return None

    n_results = min(max(top_k * 5, 25), collection.count())
    where = _code_filter(query)

    def _query(texts: list[str]) -> dict:
        embeddings = _get_model().encode(texts, show_progress_bar=False).tolist()
        res = collection.query(
            query_embeddings=embeddings,
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        if where and (not res["documents"] or not res["documents"][0]):
            # Named code not yet ingested — fall back to the full collection.
            res = collection.query(
                query_embeddings=embeddings,
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )
        return res

    # Fuse raw and filler-stripped embeddings, best distance per chunk id.
    texts = [t for t in _fused_query_texts(query) if t.strip()]
    res = _query(texts)
    fused: dict[str, tuple[str, dict, float]] = {}
    for qi in range(len(texts)):
        for id_, doc, meta, dist in zip(
            res["ids"][qi],
            res["documents"][qi],
            res["metadatas"][qi],
            res["distances"][qi],
        ):
            if id_ not in fused or dist < fused[id_][2]:
                fused[id_] = (doc, meta, dist)

    ranked = sorted(fused.values(), key=lambda item: item[2])[:top_k]
    parts: list[str] = []
    for doc, meta, dist in ranked:
        if dist > MAX_DISTANCE:
            continue
        source = meta.get("source", "unknown")
        parts.append(f"[Источник: {source}]\n{doc}")

    if not parts:
        return None
    return "\n\n".join(parts)
