#!/bin/bash
# HEIMDALL backend supervisor — auto-restarts uvicorn if it ever crashes.
# Port 8100 (8000 is reserved by the separate secure-wealth twin backend).
cd "$(dirname "$0")/.."
export ARROW_DEFAULT_MEMORY_POOL=system
while true; do
  .venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8100 --log-level warning
  code=$?
  echo "$(date -u +%FT%TZ) uvicorn exited code=$code — restarting in 2s" >> /tmp/heimdall_backend_supervisor.log
  sleep 2
done
