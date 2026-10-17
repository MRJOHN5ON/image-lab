#!/usr/bin/env bash
# Dev mode: backend with auto-reload + Vite hot reload on :5173 (proxies /api).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/.venv"
PORT="${PORT:-8765}"

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install -q -r "$ROOT/backend/requirements-dev.txt"
[ -d "$ROOT/frontend/node_modules" ] || (cd "$ROOT/frontend" && npm install --no-fund --no-audit)

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

(cd "$ROOT/backend" && exec "$VENV/bin/python" -m uvicorn main:app --host 127.0.0.1 --port "$PORT" --reload) &
pids+=($!)
(cd "$ROOT/frontend" && exec npm run dev) &
pids+=($!)

echo "Dev servers:"
echo "  UI (hot reload): http://127.0.0.1:5173"
echo "  API:             http://127.0.0.1:$PORT"
wait
