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

Current contents:
- `trudovoy_kodeks_rk.md` — full text of the Labor Code of the Republic of
  Kazakhstan (23.11.2015 № 414-V ЗРК, consolidated version as of the source
  capture date).
- `grazhdanskiy_kodeks_rk.md` — abridged excerpts from the Civil Code (special
  part). Replace with the full text when a machine-readable current version is
  available.

Note: the Tax Code was deliberately removed — the 2017 code (№ 120-VI) was
repealed by the Tax Code of 18.07.2025 № 214-VIII effective 01.01.2026, and no
text source for the current code is available to this pipeline yet. Do not
re-add the repealed text: the bot must not cite outdated tax rates.

Tuning via `backend/.env`:
- `RAG_EMBEDDING_MODEL` — any SentenceTransformers model name
- `RAG_TOP_K` — number of chunks retrieved per query (default 3)
- `RAG_MAX_DISTANCE` — cosine distance cutoff for relevance (default 0.6)
- `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP` — chunking parameters

Sources for full official texts: https://adilet.zan.kz/rus — check
licensing/attribution requirements before publishing a derived dataset.
