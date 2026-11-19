#!/usr/bin/env bash
# Launch backend (FastAPI) and frontend (Vite) together.
# Ctrl-C stops both.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON="$ROOT/backend/venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "venv not found at backend/venv — falling back to system python3"
  PYTHON="python3"
fi

# 127.0.0.1, not 0.0.0.0: the backend has no login, so it must not be reachable from the venue Wi-Fi.
# ~/.local/bin holds iverilog / yosys / sta on the demo machine.
export PATH="$HOME/.local/bin:$PATH"
echo "Starting backend on http://127.0.0.1:8000 ..."
( cd "$ROOT/backend" && "$PYTHON" -m uvicorn main:app --host 127.0.0.1 --port 8000 ) &
BACKEND_PID=$!

echo "Starting frontend on http://127.0.0.1:5173 ..."
( cd "$ROOT/frontend" && npm run dev -- --host 127.0.0.1 ) &
FRONTEND_PID=$!

cleanup() {
  echo ""
  echo "Shutting down..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

wait
