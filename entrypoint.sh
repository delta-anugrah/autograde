#!/bin/sh
set -e

PORT="${APP_PORT:-8000}"

if [ "$APP_ENV" = "development" ]; then
    exec python -m uvicorn src.palmgrade.main:app \
        --host 0.0.0.0 \
        --port "$PORT" \
        --reload
else
    exec python -m uvicorn src.palmgrade.main:app \
        --host 0.0.0.0 \
        --port "$PORT"
fi
