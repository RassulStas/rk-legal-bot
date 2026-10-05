#!/usr/bin/env bash
# One-shot repair for the VPS backend boot failure:
#   ModuleNotFoundError: No module named 'database'  (main.py, line 24)
# Root cause: directory nesting conflict under /root/backend — main.py sits in
# /root/backend/backend/ while sibling service modules (database, models,
# rag_service, parser_service, docx_service, security_logger) live in a nested
# /root/backend/backend/backend/ (double-cloned repo). main.py's sys.path guard
# (commit adb464d) only adds its own folder, so the flat imports at lines 24-36
# still fail. Fix: rescue the missing modules next to main.py, then launch
# uvicorn from the app dir as main:app. Verified end-to-end against a local
# reproduction of this exact layout (import + uvicorn boot + HTTP 200).
#
# Run on the server as root:
#   export GEMINI_API_KEY='<key>'
#   bash /root/backend/backend/server_repair.sh
set -euo pipefail

APPROOT=/root/backend
APPDIR="$APPROOT/backend"
PORT=10000
PROC_NAME=rk-legal-api
ENTRY="main:app"
REQUIRED_MODS=(database models rag_service parser_service docx_service security_logger)

echo "=== [1/8] Diagnose layout ==="
find "$APPROOT" -maxdepth 3 -name main.py -not -path '*/venv/*' -not -path '*/.venv/*' 2>/dev/null || true
find "$APPROOT" -maxdepth 3 -name database.py -not -path '*/venv/*' -not -path '*/.venv/*' 2>/dev/null || true
if command -v pm2 >/dev/null; then pm2 list || true; else echo "WARN: pm2 not found on PATH"; fi

if [ ! -f "$APPDIR/main.py" ]; then
    echo "ERROR: $APPDIR/main.py not found — adjust APPDIR in this script" >&2
    exit 1
fi
echo "APPDIR=$APPDIR  ENTRY=$ENTRY"

echo "=== [2/8] Sync code (non-destructive git pull) ==="
TOP="$(git -C "$APPDIR" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$TOP" ]; then
    git -C "$TOP" pull --ff-only origin main \
        || echo "WARN: git pull failed — continuing with local fixes"
else
    echo "WARN: $APPDIR is not inside a git repo — continuing with local fixes"
fi

echo "=== [3/8] Ensure sys.path guard in main.py ==="
MAIN="$APPDIR/main.py"
if ! grep -q 'sys.path.insert' "$MAIN"; then
    python3 - "$MAIN" <<'PY'
import sys
path = sys.argv[1]
guard = (
    "import sys as _sys\n"
    "from pathlib import Path as _Path\n"
    "_sys.path.insert(0, str(_Path(__file__).resolve().parent))\n\n"
)
with open(path, encoding="utf-8") as fh:
    src = fh.read()
with open(path, "w", encoding="utf-8") as fh:
    fh.write(guard + src)
print("patched: sys.path guard prepended to main.py")
PY
else
    echo "guard already present"
fi

echo "=== [4/8] Rescue modules trapped by the nesting conflict ==="
rescue_one() {
    local name="$1"
    [ -f "$APPDIR/$name" ] && return 0
    local src
    src="$(find "$APPROOT" -maxdepth 4 -name "$name" \
        -not -path '*/venv/*' -not -path '*/.venv/*' -not -path '*/site-packages/*' \
        2>/dev/null | head -1)"
    if [ -n "$src" ]; then
        cp "$src" "$APPDIR/$name"
        echo "rescued $name from $(dirname "$src")"
    else
        echo "ERROR: $name not found anywhere under $APPROOT" >&2
        return 1
    fi
}
for mod in "${REQUIRED_MODS[@]}"; do
    rescue_one "$mod.py" || exit 1
done
rescue_one "requirements.txt" || true
rescue_one ".env" || true
touch "$APPDIR/__init__.py" 2>/dev/null || true

echo "=== [5/8] Runtime env (.env + GEMINI_API_KEY) ==="
ENV_FILE="$APPDIR/.env"
touch "$ENV_FILE"; chmod 600 "$ENV_FILE"
if [ -z "${GEMINI_API_KEY:-}" ] && grep -qs '^GEMINI_API_KEY=.' "$ENV_FILE"; then
    GEMINI_API_KEY="$(grep '^GEMINI_API_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
fi
if [ -z "${GEMINI_API_KEY:-}" ]; then
    echo "ERROR: GEMINI_API_KEY not set and not found in $ENV_FILE" >&2
    echo "       export GEMINI_API_KEY='<key>' then re-run" >&2
    exit 1
fi
export GEMINI_API_KEY
if ! grep -qs '^GEMINI_API_KEY=' "$ENV_FILE"; then
    printf 'GEMINI_API_KEY=%s\n' "$GEMINI_API_KEY" >> "$ENV_FILE"
    echo "GEMINI_API_KEY written to $ENV_FILE"
else
    echo "GEMINI_API_KEY already present in $ENV_FILE"
fi

echo "=== [6/8] Python env ==="
PY=""
for cand in "$APPDIR/venv/bin/python" "$APPDIR/.venv/bin/python" "$APPROOT/venv/bin/python"; do
    if [ -x "$cand" ]; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
    echo "ERROR: no virtualenv python found (looked in $APPDIR/venv, $APPDIR/.venv, $APPROOT/venv)" >&2
    exit 1
fi
echo "PY=$PY"
if [ -f "$APPDIR/requirements.txt" ]; then
    "$PY" -m pip install --quiet -r "$APPDIR/requirements.txt"
else
    echo "WARN: no requirements.txt — skipping dependency sync"
fi

echo "=== [7/8] Import smoke test (exact prod env) ==="
( cd "$APPDIR" && PYTHONPATH="$APPDIR" "$PY" -c \
    "import importlib; importlib.import_module('${ENTRY%:app}'); print('IMPORT_OK')" )

echo "=== [8/8] (Re)start on 0.0.0.0:$PORT ==="
export PYTHONPATH="$APPDIR"
fuser -k "${PORT}/tcp" 2>/dev/null || true
if command -v pm2 >/dev/null; then
    pm2 delete "$PROC_NAME" 2>/dev/null || true
    cd "$APPDIR"
    pm2 start "$PY" --name "$PROC_NAME" --cwd "$APPDIR" -- \
        -m uvicorn "$ENTRY" --host 0.0.0.0 --port "$PORT"
    pm2 save || true
else
    cd "$APPDIR"
    nohup "$PY" -m uvicorn "$ENTRY" --host 0.0.0.0 --port "$PORT" \
        > "$APPROOT/uvicorn.log" 2>&1 &
    echo "started without pm2 (nohup), log: $APPROOT/uvicorn.log"
fi

echo "=== Verify ==="
ok=""
code=""
for _ in $(seq 1 30); do
    code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/docs" || true)"
    if [ "$code" = "200" ]; then ok=1; echo "HEALTH_OK  /docs -> 200"; break; fi
    sleep 2
done
if [ -z "$ok" ]; then
    echo "HEALTH_FAIL: last HTTP code='$code' — recent logs:" >&2
    pm2 logs "$PROC_NAME" --lines 40 --nostream 2>/dev/null \
        || tail -40 "$APPROOT/uvicorn.log" 2>/dev/null || true
    exit 1
fi
pm2 logs "$PROC_NAME" --lines 25 --nostream 2>/dev/null || true
echo "=== REPAIR COMPLETE: $ENTRY up on 0.0.0.0:$PORT ==="
