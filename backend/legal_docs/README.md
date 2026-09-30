# Legal documents for RAG ingestion

Drop Kazakhstan legal act documents here (UTF-8 plain text, `.txt` or `.md`).
At backend startup, `rag_service.ingest_documents()` automatically:

1. Scans every `.txt` / `.md` file in this folder
2. Chunks the text (~1000 chars with overlap, paragraph-aware)
3. Generates semantic embeddings (`paraphrase-multilingual-MiniLM-L12-v2` by default)
4. Stores the chunks in the persistent ChromaDB collection `rk_laws`

Adding, editing, or removing files triggers a full re-ingest on the next
restart (detection is based on file name, size, and mtime). The vector store
lives in `backend/chroma_db/`.

Tuning via `backend/.env`:
- `RAG_EMBEDDING_MODEL` — any SentenceTransformers model name
- `RAG_TOP_K` — number of chunks retrieved per query (default 3)
- `RAG_MAX_DISTANCE` — cosine distance cutoff for relevance (default 0.8)
- `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP` — chunking parameters

The documents in this folder are abridged excerpts for development purposes.
For production, replace them with official texts from
https://adilet.zan.kz/rus and keep licensing/attribution in mind.
