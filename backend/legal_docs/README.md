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

Current contents (all full consolidated official texts, Russian language):
- `trudovoy_kodeks_rk.md` — Labor Code of the Republic of Kazakhstan
  (23.11.2015 № 414-V ЗРК).
- `grazhdanskiy_kodeks_rk_obshaya_chast.md` — Civil Code, General Part
  (27.12.1994 № 268-XIII, in force since 01.03.1995).
- `grazhdanskiy_kodeks_rk_osobennaya_chast.md` — Civil Code, Special Part
  (01.07.1999 № 409).
- `nalogoviy_kodeks_rk.md` — Tax Code of the Republic of Kazakhstan
  (17.07.2025 № 214-VIII, in force since 01.01.2026).
- `predprinimatelskiy_kodeks_rk.md` — Entrepreneurial Code of the Republic of
  Kazakhstan (29.10.2015 № 375-V ЗРК).
- `kodeks_administrativnykh_pravonarusheniy_rk.md` — Code on Administrative
  Offences of the Republic of Kazakhstan (05.07.2014 № 235-V ЗРК).
- `zemelniy_kodeks_rk.md` — Land Code of the Republic of Kazakhstan
  (20.06.2003 № 442).
- `grazhdanskiy_protsessualnyy_kodeks_rk.md` — Civil Procedure Code of the
  Republic of Kazakhstan (31.10.2015 № 377-V ЗРК).

All fetched from the adilet.zan.kz SPA API (`GET /api/documents/by-ngr/{NGR}
?language=rus`, `text_content` HTML) with `is_actual` verified at fetch time
(2026-10): Предпринимательский K1500000375, КоАП K1400000235, Земельный
K030000442_, ГПК K1500000377. Old repealed NGRs (e.g. ГПК K990000411_,
status "yts") must not be used.

Note: the previous tax document was removed earlier because it contained the
2017 code (№ 120-VI), repealed by the Tax Code of 18.07.2025 № 214-VIII
effective 01.01.2026. The current file above is the NEW code — do not replace
it with the repealed 2017 text: the bot must not cite outdated tax rates.

The texts are pre-cleaned before ingestion: editorial-system paragraphs
(«Сноска.» amendment-history footnotes, ИЗПИ/РЦПИ service notes, «Содержание»
TOC preambles) are stripped. The consolidated article text already incorporates
those amendments, and the footnotes otherwise dilute chunk embeddings — a
preamble-heavy first chunk once pushed the definitional article of ГК
ст. 406 (договор купли-продажи) to rank ~2800 in retrieval. Re-apply the same
cleaning to any future documents before adding them here. adilet's HTML also
requires: dropping bare «№ 123-VI» anchors that point at other documents,
flushing loose amendment fragments («вводится», «ст. 2») that sit between
`<p>` tags so they don't glue onto the next article paragraph, and stripping
junk prefixes glued before «Статья N» headings.

Tuning via `backend/.env`:
- `RAG_EMBEDDING_MODEL` — any SentenceTransformers model name
- `RAG_TOP_K` — number of chunks retrieved per query (default 3)
- `RAG_MAX_DISTANCE` — cosine distance cutoff for relevance (default 0.6)
- `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP` — chunking parameters

Sources for full official texts: https://adilet.zan.kz/rus — check
licensing/attribution requirements before publishing a derived dataset.
