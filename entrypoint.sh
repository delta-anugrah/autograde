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

# --timeout-graceful-shutdown: saat SIGTERM (`docker stop`, `autograde restart`)
# uvicorn menunggu semua koneksi selesai sebelum lifespan shutdown. Layar konsol
# membuka /api/video_feed tiap line terus-menerus dan aliran itu tidak pernah
# selesai sendiri, jadi tanpa batas ini uvicorn menunggu sampai SIGKILL 10 detik
# kemudian dan urutan tutup line (coil PLC OFF, antrean simpan ditulis) tidak
# pernah jalan. 1 detik + BATAS_TUTUP_S (services/penutup_line.py) harus muat di
# 10 detik itu: tests/unit/test_tenggang_tutup_uvicorn.py.

if [ "$APP_ENV" = "development" ]; then
    exec python -m uvicorn "$APP_MODULE" \
        --host 0.0.0.0 \
        --port "$PORT" \
        --timeout-graceful-shutdown 1 \
        --reload
else
    exec python -m uvicorn "$APP_MODULE" \
        --host 0.0.0.0 \
        --port "$PORT" \
        --timeout-graceful-shutdown 1
fi
