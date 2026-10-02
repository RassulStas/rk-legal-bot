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


def _chunk_text(text: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
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
            collection.add(ids=ids, documents=chunks, metadatas=metadatas, embeddings=embeddings)
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

    query_embedding = _get_model().encode(query, show_progress_bar=False).tolist()
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    parts: list[str] = []
    for doc, meta, dist in zip(
        result["documents"][0], result["metadatas"][0], result["distances"][0]
    ):
        if dist > MAX_DISTANCE:
            continue
        source = meta.get("source", "unknown")
        parts.append(f"[Источник: {source}]\n{doc}")

    if not parts:
        return None
    return "\n\n".join(parts)
