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


# When a question can name several codes at once ("убытки по ГК, претензия
# по ГПК, вычет по НК"). Retrieval detects every named code group and spends
# a quota of top_k on each, instead of locking onto whichever code keyword
# matched first — that lock starved the other sub-questions of context and
# the model correctly answered with disclaimers. Each entry:
# (keywords, source filenames).
_GPK_SOURCE = "grazhdanskiy_protsessualnyy_kodeks_rk.md"
_GK_SOURCES = (
    "grazhdanskiy_kodeks_rk_obshaya_chast.md",
    "grazhdanskiy_kodeks_rk_osobennaya_chast.md",
)

_CODE_GROUPS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    # "налог" (not just "налогов") so e.g. "ставка земельного налога" lands
    # in the Tax Code instead of being swallowed by the земельн filter.
    (("налог", "ндс", "ипн", "кпн", "корпоративн", "социальн"), ("nalogoviy_kodeks_rk.md",)),
    (("предпринимат",), ("predprinimatelskiy_kodeks_rk.md",)),
    (("административн", "коап"), ("kodeks_administrativnykh_pravonarusheniy_rk.md",)),
    (("земельн",), ("zemelniy_kodeks_rk.md",)),
    # "ГПК"/"претензия"/"досудебный" mark civil-procedure sub-questions even
    # when the full name is never spelled out.
    (("процессуальн", "гпк", "досудебн", "претенз"), (_GPK_SOURCE,)),
    (("гражданск",), _GK_SOURCES),
    (("трудов", "заработн", "зарплат", "работодател"), ("trudovoy_kodeks_rk.md",)),
]

# "гражданско-процессуальный кодекс" mentions ГПК only: test the Civil Code
# keyword against the query with ГПК names removed, else that shared root
# drags the substantive ГК group in alongside ГПК.
_GPK_NAME_RE = re.compile(r"(?i)гражданск\w*[\s-]*процессуальн\w*|\bгпк\b")

# Procedural sub-questions ("в какой суд обращаться", "сроки подачи иска")
# inside otherwise substantive queries.
_PROCEDURAL_SUBSTRINGS = ("суд", "жалоб", "процессуальн", "обращен", "подач")
# \bиск(а|у|…)?\b matches иск/иска/иску/иске while \bисков\w* covers
# исковой/искового; both stay clear of "риск"/"исключение".
_PROCEDURAL_RE = re.compile(r"\bисков\w*|\bиск(?:а|у|ом|е|и|ам|ами|ах|ов)?\b")


def _sounds_procedural(query: str) -> bool:
    q = query.lower()
    return any(s in q for s in _PROCEDURAL_SUBSTRINGS) or bool(_PROCEDURAL_RE.search(q))


def _matched_groups(query: str) -> list[tuple[str, ...]]:
    """All code groups the query names — not just the first keyword hit."""
    q = query.lower()
    q_no_gpk = _GPK_NAME_RE.sub(" ", q)
    groups: list[tuple[str, ...]] = []
    for keywords, sources in _CODE_GROUPS:
        haystack = q_no_gpk if sources == _GK_SOURCES else q
        if any(k in haystack for k in keywords) and sources not in groups:
            groups.append(sources)
    # A substantive query that also sounds procedural ("задержка зарплаты
    # ... в какой суд обращаться") must not lose ГПК candidates.
    if groups and _sounds_procedural(q) and (_GPK_SOURCE,) not in groups:
        groups.append((_GPK_SOURCE,))
    return groups


_NUMBERED_SPLIT = re.compile(r"(?m)^\s*\d+\s*[.)]\s+")


def _numbered_parts(query: str) -> list[str]:
    """Sub-questions of a numbered list ("1. ... 2. ..."). Each part usually
    concerns its own code, and retrieving with the part text — not the whole
    multi-part question — ranks its articles far higher."""
    fragments = _NUMBERED_SPLIT.split(query)
    if len(fragments) < 3:
        return []
    return [" ".join(f.split()) for f in fragments[1:] if f.strip()]


# Canonical heading-phrase bridges per code group: a compact canonical
# phrase outperforms appending words to the noisy full-sentence query
# (e.g. "возмещение убытков и упущенной выгоды ..." holds ГК ст. 350/351
# at ~0.23 distance where the raw question leaves them below top-20).
def _group_bridges(query: str, sources: tuple[str, ...]) -> list[str]:
    q = query.lower()
    bridges: list[str] = []
    if sources == _GK_SOURCES:
        if re.search(r"убытк|упущенн", q):
            bridges.append("возмещение убытков и упущенной выгоды при нарушении обязательства")
        if re.search(r"неустойк|пени|просроч", q):
            bridges.append("неустойка за неправомерное пользование чужими деньгами")
        if re.search(r"взыск|защит", q):
            bridges.append("возмещение убытков взыскание неустойки защита гражданских прав")
    elif sources == (_GPK_SOURCE,):
        if re.search(r"досудебн|претенз", q):
            bridges.append("судебная защита прав и охраняемых законом интересов")
            bridges.append("возвращение искового заявления несоблюдение досудебного порядка урегулирования спора")
        if _sounds_procedural(q):
            bridges.append("подсудность гражданских дел и порядок подачи искового заявления в суд, сроки обращения за судебной защитой")
    elif sources == ("nalogoviy_kodeks_rk.md",):
        # "КПН" alone does not bridge to "корпоративный подоходный налог" in
        # the embedding space, mirroring the ИПН case below.
        if re.search(r"(?i)\bкпн\b", query):
            bridges.append(re.sub(r"(?i)\bкпн\b", "корпоративного подоходного налога", query))
        if re.search(r"убытк", q) and re.search(r"кпн|подоходн|уменьшен|вычет|вычесть", q):
            bridges.append("уменьшение налогооблагаемого дохода вычет понесенных убытков")
            bridges.append("учет убытков при исчислении корпоративного подоходного налога")
    return bridges


def _group_query_texts(query: str, sources: tuple[str, ...]) -> list[str]:
    texts = _fused_query_texts(query)
    # Strip the other codes' vocabulary so the embedding leans toward this
    # group's articles instead of being dragged by e.g. tax wording.
    other = [
        k
        for keywords, group_sources in _CODE_GROUPS
        if group_sources != sources
        for k in keywords
        # ГПК text legitimately speaks of "гражданские дела".
        if not (sources == (_GPK_SOURCE,) and k == "гражданск")
    ]
    stripped = " ".join(
        re.sub("|".join(map(re.escape, other)), " ", query, flags=re.IGNORECASE).split()
    )
    if stripped and stripped.lower() not in {t.lower() for t in texts}:
        texts.append(stripped)
    for part in _numbered_parts(query):
        if sources in _matched_groups(part):
            texts.append(part)
    texts.extend(_group_bridges(query, sources))
    return list(dict.fromkeys(t for t in texts if t.strip()))


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
    # "расторг" misses "расторжение" (no "г"); "растор" covers both.
    if re.search(r"(?i)растор|прекрат", query) and ("аренд" in query.lower() or "найм" in query.lower()):
        texts.append("расторжение договора имущественного найма по требованию одной из сторон")
    # "ИПН" alone does not bridge to "индивидуальный подоходный налог" in
    # the embedding space (НК ст. 363 falls out of the candidate pool);
    # the spelled-out form ranks it #1.
    if re.search(r"(?i)\bипн\b", query):
        texts.append(re.sub(r"(?i)\bипн\b", "индивидуального подоходного налога", query))
        if stripped != query:
            texts.append(re.sub(r"(?i)\bипн\b", "индивидуального подоходного налога", stripped))
    # КоАП ст. 608's heading phrase is what the embedding matches; colloquial
    # drunk-driving questions ("что будет если сесть за руль пьяным") rank
    # the inclusion article 619-1 above it. The canonical phrase ranks 608 #1.
    # "нетрезв" is a common sober-negation phrasing that matches neither root.
    if re.search(r"(?i)опьянени|пьян\w*\b|нетрезв", query) and re.search(
        r"(?i)управлени|водител|транспорт|рул\w*", query
    ):
        texts.append("управление транспортным средством в состоянии опьянения")
    # Land-allocation questions miss ЗК ст. 43 ("Порядок предоставления права
    # на земельный участок") — its own heading phrase ranks it #1 at 0.12
    # while natural phrasings leave it below top-40.
    if re.search(r"(?i)предоставл|выдел\w*\b|получ\w*\b", query) and "земельн" in query.lower():
        texts.append("порядок предоставления права на земельный участок")
    # ГПК ст. 148's chunks embed far from any filing/drafting phrasing (its
    # own title scores 0.58 to its own chunk — a list-heavy outlier), while
    # neighbouring articles rank ahead at ~0.23. The article's opening
    # sentence scores 0.21 and wins the ranking.
    if re.search(r"(?i)\bиск\w*", query) and re.search(
        r"(?i)подач|подат|подава|направ|состав|содержан|оформл|форм\w*", query
    ):
        texts.append(
            "иск подается в суд первой инстанции в письменной форме либо в форме электронного документа"
        )
    return list(dict.fromkeys(t for t in texts if t.strip()))


def _chunk_text(text: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", _linearize_tables(text)) if p.strip()]
    chunks: list[str] = []
    current = ""
    heading = ""

    def emit(chunk: str) -> None:
        # Continuation chunks of long articles carry the article heading so
        # they embed (and stay citable) as the article rather than as bare
        # mid-article text: ГПК ст. 148's list-heavy chunks otherwise never
        # surface for filing questions. Chapter/section lines keep their own
        # identity and are never prefixed with a neighbouring article.
        if heading and not chunk.startswith(("#", "*")):
            chunk = f"{heading}\n\n{chunk}"
        chunks.append(chunk)

    for para in paragraphs:
        # Flush at article boundaries so each chunk carries its article number
        # and definitional articles are not diluted by neighbouring ones.
        if current and ARTICLE_START.match(para):
            emit(current)
            current = ""
        if ARTICLE_START.match(para):
            heading = para.split("\n", 1)[0]
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= CHUNK_SIZE:
            current = candidate
            continue
        if current:
            emit(current)
        if len(para) <= CHUNK_SIZE:
            current = para
        else:
            for i in range(0, len(para), CHUNK_SIZE - CHUNK_OVERLAP):
                piece = para[i : i + CHUNK_SIZE].strip()
                if piece:
                    emit(piece)
            current = ""
    if current:
        emit(current)
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

    Multi-code questions retrieve a quota of chunks per named code group so
    every sub-question carries statutory context. Returns None if the store
    is empty or nothing passes the relevance threshold, letting the caller
    fall back to a context-free prompt.
    """
    collection = _get_collection()
    if collection.count() == 0 or not query.strip():
        return None

    def _fuse(texts: list[str], where: dict | None, n_results: int) -> list[tuple[str, dict, float]]:
        # Fuse all query variants (raw, stripped, bridges), best distance
        # per chunk id.
        embeddings = _get_model().encode(texts, show_progress_bar=False).tolist()
        res = collection.query(
            query_embeddings=embeddings,
            n_results=min(n_results, collection.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        if where and (not res["documents"] or not res["documents"][0]):
            # Named code not yet ingested — fall back to the full collection.
            res = collection.query(
                query_embeddings=embeddings,
                n_results=min(n_results, collection.count()),
                include=["documents", "metadatas", "distances"],
            )
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
        ranked = sorted(fused.values(), key=lambda item: item[2])
        # Cap two chunks per article so one repetitive article cannot eat
        # the whole quota (ГПК ст. 429's boilerplate otherwise appears 3×).
        per_article: dict[str, int] = {}
        diverse: list[tuple[str, dict, float]] = []
        for doc, meta, dist in ranked:
            article = doc.split("\n", 1)[0]
            per_article[article] = per_article.get(article, 0) + 1
            if per_article[article] <= 2:
                diverse.append((doc, meta, dist))
        return diverse

    groups = _matched_groups(query)
    if not groups:
        ranked = [
            item
            for item in _fuse(_fused_query_texts(query), None, max(top_k * 5, 25))
            if item[2] <= MAX_DISTANCE
        ][:top_k]
    else:
        group_ranked: list[list[tuple[str, dict, float]]] = []
        for sources in groups:
            texts = _group_query_texts(query, sources)
            ranked_group = [
                item
                for item in _fuse(texts, {"source": {"$in": list(sources)}}, max(top_k * 4, 15))
                if item[2] <= MAX_DISTANCE
            ]
            group_ranked.append(ranked_group)
        quota, remainder = divmod(top_k, len(groups))
        taken: list[tuple[str, dict, float]] = []
        for gi, ranked_group in enumerate(group_ranked):
            taken.extend(ranked_group[: quota + (1 if gi < remainder else 0)])
        # A weak or empty group spills its unused quota to the other groups.
        if len(taken) < top_k:
            counts = [min(quota + (1 if gi < remainder else 0), len(rg)) for gi, rg in enumerate(group_ranked)]
            rest = [item for gi, rg in enumerate(group_ranked) for item in rg[counts[gi] :]]
            rest.sort(key=lambda item: item[2])
            taken.extend(rest[: top_k - len(taken)])
        ranked = sorted(taken, key=lambda item: item[2])[:top_k]

    parts: list[str] = []
    for doc, meta, dist in ranked:
        source = meta.get("source", "unknown")
        parts.append(f"[Источник: {source}]\n{doc}")

    if not parts:
        return None
    return "\n\n".join(parts)
