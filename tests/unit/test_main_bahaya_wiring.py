"""`main.py` (app line) — urutan boot Danger Zone, dijaga sebagai teks.

`create_app()` tidak bisa dinyalakan di CI (kamera, torch), jadi yang dijaga di
sini dua hal yang kalau salah GAGAL SENYAP:

- hapus-saat-boot jalan SEBELUM store mana pun membuka berkasnya. Sesudahnya,
  `outbox.db` dan `upload_manifest.db` sudah terbuka: berkasnya hilang dari
  folder tapi proses tetap menulis ke inode lama, dan antrean yang dikira
  kosong ternyata masih mengirim;
- router Danger Zone dipasang dengan Settings, RuntimeState, dan fungsi keluar
  yang SAMA dengan router internal lain — Settings lain berarti folder lain.
"""
from __future__ import annotations

from pathlib import Path

MAIN = (Path(__file__).resolve().parents[2] / "src/palmgrade/main.py").read_text()
LIFESPAN = MAIN.split("async def lifespan(app: FastAPI):", 1)[1]


def test_hapus_saat_boot_sebelum_store_dibuka():
    i_hapus = LIFESPAN.index("hapus_kalau_diminta(settings.artifacts_dir, settings.state_dir)")
    for pembuka in ("_lic_manager.init()", "get_outbox_store()", "UploadManifest("):
        assert i_hapus < LIFESPAN.index(pembuka), pembuka


def test_hasil_hapus_dicatat():
    """Line yang menghapus datanya diam-diam = tidak ada jejak siapa yang meminta."""
    blok = LIFESPAN.split("hapus_kalau_diminta(", 1)[1][:600]
    assert "logger.warning" in blok


def test_router_bahaya_dipasang_dengan_dependensi_yang_sama():
    assert "app.include_router(" in MAIN
    blok = MAIN.split("buat_router_bahaya(", 1)[1][:300]
    assert "settings=get_settings" in blok
    assert "state=get_runtime_state" in blok
    assert "keluar=_jadwalkan_keluar" in blok


def test_penugasan_menolak_truk_baru_selama_hapus_menunggu():
    """I-3b: dijaga sebagai teks karena router internal menarik torch (test
    perilakunya: `tests/e2e/test_internal_assignment_hapus.py`, lokal)."""
    internal = (Path(__file__).resolve().parents[2] / "src/palmgrade/routes/internal.py").read_text()
    fn = internal.split("async def assignment_sync(", 1)[1].split("\n@router", 1)[0]
    assert "hapus_diminta(" in fn
    assert "409" in fn
