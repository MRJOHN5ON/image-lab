#!/usr/bin/env bash
# Dev mode: backend + Vite hot reload
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/.venv"
PORT="${PORT:-8765}"

source "$VENV/bin/activate" 2>/dev/null || {
  python3 -m venv "$VENV"
  source "$VENV/bin/activate"
  pip install -q -r "$ROOT/backend/requirements.txt"
}

(cd "$ROOT/frontend" && npm install --silent 2>/dev/null; npm run dev) &
FRONTEND_PID=$!

cd "$ROOT/backend"
uvicorn main:app --host 127.0.0.1 --port "$PORT" --reload &
BACKEND_PID=$!

trap "kill $FRONTEND_PID $BACKEND_PID 2>/dev/null" EXIT

echo "Dev servers running:"
echo "  Frontend: http://127.0.0.1:5173"
echo "  Backend:  http://127.0.0.1:$PORT"
wait
