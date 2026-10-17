#!/usr/bin/env bash
# Run Image Lab locally: installs what's missing, rebuilds the UI when its
# sources changed, then serves everything from one process on 127.0.0.1.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$ROOT/.venv"
PORT="${PORT:-8765}"
HOST=127.0.0.1

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

command -v python3 >/dev/null || die "python3 not found. Install Python 3.10+ (brew install python)."
command -v npm >/dev/null || die "npm not found. Install Node.js 18+ (brew install node)."

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  if curl -fsS "http://$HOST:$PORT/api/health" 2>/dev/null | grep -q '"app"'; then
    say "Image Lab is already running at http://$HOST:$PORT"
    command -v open >/dev/null && open "http://$HOST:$PORT"
    exit 0
  fi
  die "Port $PORT is in use by another program. Try: PORT=8766 ./start.sh"
fi

if [ ! -x "$VENV/bin/python" ]; then
  say "Creating Python environment"
  python3 -m venv "$VENV"
fi

REQ_STAMP="$VENV/.requirements.stamp"
if [ ! -f "$REQ_STAMP" ] || [ "$BACKEND/requirements.txt" -nt "$REQ_STAMP" ]; then
  say "Installing Python packages"
  "$VENV/bin/python" -m pip install -q --upgrade pip
  "$VENV/bin/python" -m pip install -q -r "$BACKEND/requirements.txt"
  touch "$REQ_STAMP"
fi

if [ ! -d "$FRONTEND/node_modules" ] || [ "$FRONTEND/package.json" -nt "$FRONTEND/node_modules" ]; then
  say "Installing frontend packages"
  (cd "$FRONTEND" && npm install --no-fund --no-audit)
  touch "$FRONTEND/node_modules"
fi

needs_build() {
  [ -f "$FRONTEND/dist/index.html" ] || return 0
  [ -n "$(find "$FRONTEND/src" "$FRONTEND/index.html" "$FRONTEND/public" "$FRONTEND/vite.config.js" \
      -newer "$FRONTEND/dist/index.html" -print -quit 2>/dev/null)" ]
}
if needs_build; then
  say "Building the interface"
  (cd "$FRONTEND" && npm run build --silent)
fi

if ! command -v jpegtran >/dev/null && [ ! -x /opt/homebrew/bin/jpegtran ] && [ ! -x /usr/local/bin/jpegtran ]; then
  echo "    tip: brew install jpeg-turbo  enables extra lossless JPEG savings"
fi

say "Image Lab → http://$HOST:$PORT   (Ctrl+C to stop)"
( sleep 1.5; command -v open >/dev/null && [ -z "${NO_OPEN:-}" ] && open "http://$HOST:$PORT" ) >/dev/null 2>&1 &

cd "$BACKEND"
exec "$VENV/bin/python" -m uvicorn main:app --host "$HOST" --port "$PORT" --log-level warning
