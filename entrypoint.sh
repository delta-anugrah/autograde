#!/bin/sh
set -e

PORT="${APP_PORT:-8000}"

# APP_MODE=console → instance ke-4: konsol operator, tanpa kamera/YOLO/PLC.
# Modul app-nya beda supaya proses konsol tidak ikut memuat torch & cv2.
# Konsol sengaja TANPA --timeout-graceful-shutdown (lihat blok line di bawah):
# satu-satunya aliran konsol (CSV Riwayat) selesai sendiri, dan batas itu cuma
# memotong permintaan yang sedang jalan saat `docker stop`, mis. CSV sebulan
# (~6 detik) atau hapus-data Danger Zone yang menunggu line mati.
if [ "$APP_MODE" = "console" ]; then
    if [ "$APP_ENV" = "development" ]; then
        exec python -m uvicorn src.palmgrade.console_main:app \
            --host 0.0.0.0 \
            --port "$PORT" \
            --reload
    fi
    exec python -m uvicorn src.palmgrade.console_main:app \
        --host 0.0.0.0 \
        --port "$PORT"
fi

# Line: --timeout-graceful-shutdown. Saat SIGTERM (`docker stop`, `autograde
# restart`) uvicorn menunggu semua koneksi selesai sebelum lifespan shutdown.
# Layar konsol membuka /api/video_feed tiap line terus-menerus dan aliran itu
# tidak pernah selesai sendiri, jadi tanpa batas ini uvicorn menunggu sampai
# SIGKILL 10 detik kemudian dan urutan tutup line (coil PLC OFF, antrean simpan
# ditulis) tidak pernah jalan. 1 detik + BATAS_TUTUP_S (services/penutup_line.py)
# harus muat di 10 detik itu: tests/unit/test_tenggang_tutup_uvicorn.py.
if [ "$APP_ENV" = "development" ]; then
    exec python -m uvicorn src.palmgrade.main:app \
        --host 0.0.0.0 \
        --port "$PORT" \
        --timeout-graceful-shutdown 1 \
        --reload
fi
exec python -m uvicorn src.palmgrade.main:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    --timeout-graceful-shutdown 1
