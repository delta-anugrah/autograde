#!/bin/sh
set -e

PORT="${APP_PORT:-8000}"

# APP_MODE=console → instance ke-4: konsol operator, tanpa kamera/YOLO/PLC.
# Modul app-nya beda supaya proses konsol tidak ikut memuat torch & cv2.
if [ "$APP_MODE" = "console" ]; then
    APP_MODULE="src.palmgrade.console_main:app"
else
    APP_MODULE="src.palmgrade.main:app"
fi

if [ "$APP_ENV" = "development" ]; then
    exec python -m uvicorn "$APP_MODULE" \
        --host 0.0.0.0 \
        --port "$PORT" \
        --reload
else
    exec python -m uvicorn "$APP_MODULE" \
        --host 0.0.0.0 \
        --port "$PORT"
fi
