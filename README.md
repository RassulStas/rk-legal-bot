# RK Legal AI Assistant

Production-ready legal AI assistant for the Republic of Kazakhstan legislation.
Answers are grounded in official RK legal acts via a Retrieval-Augmented
Generation (RAG) pipeline, streamed in real time, persisted with compliance
auditing, and PII-hardened.

## Architecture

| Layer | Stack |
|---|---|
| Frontend | React 19 + TypeScript + Vite 8 + Tailwind CSS v4 |
| API | FastAPI + Uvicorn (SSE streaming) |
| LLM | Google Gemini (`gemini-3.5-flash` by default) |
| RAG | ChromaDB (persistent, cosine) + sentence-transformers (`paraphrase-multilingual-MiniLM-L12-v2`) |
| Storage | SQLAlchemy 2 async — SQLite by default, PostgreSQL-ready (`DATABASE_URL`) |
| Compliance | IIN masking, prompt-injection blocking, `security_audit.log` audit trail |

Key backend modules:

- `main.py` — API, SSE chat endpoint, persistence, RAG fusion
- `rag_service.py` — document ingestion + semantic retrieval (collection `rk_laws`)
- `database.py` / `models.py` — async SQLAlchemy, `ChatSession` / `ChatMessage`
- `security_logger.py` — IIN (12-digit) regex filter + audit logging
- `legal_docs/` — drop `.txt` / `.md` law texts here; auto-ingested at startup
- `prod_start.sh` — production launcher (venv + Uvicorn on port 8000)

---

## Local development

Prerequisites: Python 3.10+, Node.js 20+.

```bash
# 1. Backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then set GEMINI_API_KEY (https://aistudio.google.com/apikey)
uvicorn main:app --reload --port 8000

# 2. Frontend (new terminal)
cd frontend
npm install
npm run dev               # http://localhost:5173, proxies /api -> :8000
```

First startup downloads the embedding model (~500 MB) and builds the
`rk_laws` vector store from `backend/legal_docs/`.

### Environment variables (backend/.env)

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | — | **Required.** Gemini API key |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Gemini model (Pro models need a paid plan) |
| `DATABASE_URL` | SQLite `chat.db` | e.g. `postgresql+asyncpg://user:pass@host/db` |
| `CORS_ORIGINS` | `*` | Allowed browser origins, comma-separated (wildcard by default; restrict per-domain for tighter deployments) |
| `RAG_TOP_K` | `3` | Chunks retrieved per query |
| `RAG_MAX_DISTANCE` | `0.6` | Cosine distance cutoff for relevance |
| `RAG_EMBEDDING_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | SentenceTransformer model |
| `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP` | `1000` / `150` | Chunking parameters |
| `RAG_DOCS_DIR` / `RAG_CHROMA_PATH` | `legal_docs` / `chroma_db` | RAG paths |

Frontend: `VITE_API_URL` (optional) — absolute backend origin. When unset, the
app calls same-origin `/api` (the nginx setup below).

---

## Production deployment (fresh Ubuntu 20.04+/22.04/24.04)

Manual, Docker-free deployment using git, python3-pip, pm2, and nginx.

### 1. System packages

```bash
sudo apt update
sudo apt install -y git python3 python3-pip python3-venv nginx
```

### 2. Node.js 20+ and pm2 (for the API process manager)

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install -g pm2
```

### 3. Get the code

```bash
sudo mkdir -p /var/www && sudo chown "$USER" /var/www
cd /var/www
git clone <YOUR_REPO_URL> rk-legal-bot
cd rk-legal-bot
```

### 4. Backend

```bash
cd /var/www/rk-legal-bot/backend
cp .env.example .env
nano .env        # set GEMINI_API_KEY; add CORS_ORIGINS if frontend calls API directly
./prod_start.sh &      # first run creates .venv and installs dependencies (~3-5 min)
curl -s localhost:8000/api/health   # -> {"status":"healthy"}
kill %1                # stop the foreground test instance
```

`prod_start.sh` creates the venv on first run and starts Uvicorn on
`0.0.0.0:8000` (override with `PORT`). It runs a single worker on purpose —
the embedding model and ChromaDB collection are in-process singletons.

### 5. Run the API under pm2

```bash
cd /var/www/rk-legal-bot
pm2 start backend/prod_start.sh --name rk-legal-api
pm2 startup          # run the printed command to survive reboots
pm2 save
pm2 logs rk-legal-api   # watch startup: DB init + RAG ingestion
```

### 6. Build the frontend

```bash
cd /var/www/rk-legal-bot/frontend
npm install
npm run build        # outputs static site to frontend/dist/
```

If the frontend will call the backend directly (no reverse proxy), bake the
API origin in at build time instead:

```bash
VITE_API_URL=https://api.example.com npm run build
# or: echo 'VITE_API_URL=https://api.example.com' > .env.production && npm run build
```

### 7. nginx

```bash
sudo nano /etc/nginx/sites-available/rk-legal-bot
```

```nginx
server {
    listen 80;
    server_name _;   # or your domain

    root /var/www/rk-legal-bot/frontend/dist;
    index index.html;

    # SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Reverse proxy to the API — SSE-safe
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Required for SSE streaming (disables response buffering)
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/rk-legal-bot /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

### 8. Firewall (optional but recommended)

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

### 9. HTTPS (strongly recommended)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

Visit `http://<server-ip>` (or your domain) and send a legal question — the
answer should stream in with article citations.

---

### Deploying on Render (managed platform)

**Backend — Web Service**
- Root directory: `backend`
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Environment: `GEMINI_API_KEY` (required). `CORS_ORIGINS` defaults to `*`,
  so a frontend on any origin can call it.
- First boot downloads the embedding model (~500 MB) and builds the `rk_laws`
  vector store — expect a slow first deploy. Run the app as a single process
  (the default): the embedding model and ChromaDB collection are in-process
  singletons.

**Frontend — Static Site**
- Root directory: `frontend`
- Build command: `npm install && npm run build`
- Publish directory: `dist`
- Environment: `VITE_API_URL=https://<your-backend-service>.onrender.com`
  (baked into the bundle at build time — without it, the app calls same-origin
  `/api`, which only works behind a reverse proxy)

Free-tier note: Render spins idle services down; the backend's cold boot
re-loads the embedding model, so the first request after idle time can take
a minute or two.

---

## Updating the deployment

```bash
cd /var/www/rk-legal-bot
git pull
cd frontend && npm install && npm run build && cd ..
pm2 restart rk-legal-api   # re-ingests legal_docs/ if changed (fingerprinted)
```

To force a full vector-store rebuild: `rm -rf backend/chroma_db && pm2 restart rk-legal-api`.

## Security & compliance

- **IIN protection** — 12-digit Kazakh IINs are masked (`[IIN_REDACTED]`)
  everywhere: database, Gemini prompts, and history. Every trigger is logged
  to `backend/security_audit.log` with timestamp, anonymized session hash,
  and `PII_LEAK_PREVENTED`.
- **Prompt-injection blocking** — "ignore previous instructions" patterns
  (EN/RU) are rejected with HTTP 400 and logged as `UNAUTHORIZED_PAYLOAD_BLOCKED`.
- **Audit trail** — JSON lines, no raw personal data ever written.
- **Zero data loss** — user messages commit before streaming; assistant
  replies (even partial, on error) commit in a `finally` block.
- The legal documents in `backend/legal_docs/` are abridged development
  excerpts — replace with official texts from [adilet.zan.kz](https://adilet.zan.kz)
  for production use.

## Project layout

```
rk-legal-bot/
├── backend/
│   ├── main.py             # FastAPI app: chat, persistence, RAG fusion
│   ├── rag_service.py      # ChromaDB + embeddings
│   ├── security_logger.py  # IIN filter + audit log
│   ├── database.py         # async SQLAlchemy setup
│   ├── models.py           # ChatSession / ChatMessage
│   ├── prod_start.sh       # production launcher
│   ├── legal_docs/         # ingested law texts (.txt / .md)
│   ├── .env.example        # environment template
│   └── requirements.txt
└── frontend/
    ├── src/                # React app (chat UI, i18n kk/ru)
    └── vite.config.ts      # VITE_API_URL-aware proxy
```
