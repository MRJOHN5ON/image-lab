#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$ROOT/.venv"
PORT="${PORT:-8765}"

echo "==> Image Lab startup"

if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$VENV"
fi

source "$VENV/bin/activate"
pip install -q -r "$BACKEND/requirements.txt"

if [ ! -d "$FRONTEND/node_modules" ]; then
  echo "Installing frontend dependencies..."
  (cd "$FRONTEND" && npm install)
fi

# Build frontend if dist missing
if [ ! -d "$FRONTEND/dist" ]; then
  echo "Building frontend..."
  (cd "$FRONTEND" && npm run build)
fi

echo ""
echo "  Backend:  http://127.0.0.1:$PORT"
echo "  Frontend: http://127.0.0.1:5173 (dev) or served from backend"
echo ""
echo "  Tip: brew install jpeg  (for lossless jpegtran optimization)"
echo ""

# Start backend (serves built frontend)
cd "$BACKEND"
exec uvicorn main:app --host 127.0.0.1 --port "$PORT" --reload
