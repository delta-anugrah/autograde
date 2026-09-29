"""`main.py` (app line): router antrean dipasang dengan dependensi yang SAMA, dijaga sebagai teks.

`create_app()` tidak bisa dinyalakan di CI (kamera, torch). Yang gagal senyap
kalau salah: router yang melihat store lain (layar menulis 0 menunggu padahal
worker menahan ribuan), atau RuntimeState lain (worker tidak pernah ketemu, layar
selamanya "tidak diketahui" dan Kirim Ulang tidak membangunkan apa pun).
"""
from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "palmgrade"
MAIN = (SRC / "main.py").read_text()
INTERNAL = (SRC / "routes" / "internal.py").read_text()


def test_router_antrean_dipasang_dengan_store_dan_state_yang_sama():
    blok = MAIN.split("buat_router_outbox(", 1)[1][:400]
    assert "settings=get_settings" in blok
    assert "AntreanLine(" in blok
    assert "get_outbox_store(), get_settings(), get_runtime_state(), get_folder_db_line()" in blok


def test_worker_pengirim_memakai_store_dan_state_yang_sama():
    blok = MAIN.split("outbox_worker = OutboxRetryWorker(", 1)[1][:200]
    assert "outbox=get_outbox_store()" in blok
    assert "state=state" in blok


def test_requeue_tidak_lagi_di_routes_internal():
    """Satu rute, satu tempat: dua definisi `/internal/outbox/requeue` berarti yang
    terpasang lebih dulu menang diam-diam."""
    assert '"/outbox/requeue"' not in INTERNAL
