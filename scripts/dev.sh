#!/usr/bin/env bash
# Starts API, worker and web app for local development (Postgres and Redis must be running).
# Ctrl+C stops all three.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p out/logs
.venv/bin/uvicorn backend.app.main:app --port 8000 &
.venv/bin/python -m backend.app.run_worker &
(cd frontend && npm run dev -- --port 5173) &
trap 'kill 0' INT TERM EXIT
echo "API http://localhost:8000  ·  web app http://localhost:5173  ·  Ctrl+C to stop"
wait
