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

echo "Starting backend on http://localhost:8000 ..."
( cd "$ROOT/backend" && "$PYTHON" -m uvicorn main:app --host 0.0.0.0 --port 8000 ) &
BACKEND_PID=$!

echo "Starting frontend on http://localhost:5173 ..."
( cd "$ROOT/frontend" && npm run dev ) &
FRONTEND_PID=$!

cleanup() {
  echo ""
  echo "Shutting down..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

wait
