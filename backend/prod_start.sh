#!/usr/bin/env bash
# Production launcher for the RK Legal Bot API.
# Usage: ./prod_start.sh          (binds 0.0.0.0:8000)
#        PORT=9000 ./prod_start.sh (PaaS platforms inject PORT)
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "WARNING: backend/.env not found — GEMINI_API_KEY and other settings are required. See .env.example" >&2
fi

if [ ! -d .venv ]; then
    echo "Virtual environment missing — creating it now..." >&2
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# Single worker on purpose: the embedding model and ChromaDB collection are
# in-process singletons, and each worker would load its own copy (~2 GB RAM).
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
