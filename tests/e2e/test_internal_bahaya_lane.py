"""End-to-end sisi LINE: perintah hapus lewat HTTP sampai folder bersih saat boot.

Unit test membuktikan potongannya satu-satu. Yang dibuktikan di sini rantainya
dengan Settings dan RuntimeState SUNGGUHAN dan folder yang bentuknya sama dengan
PC pabrik: perintah → penanda di `artifacts/` → boot berikutnya mengosongkan
`artifacts/` dan berkas milik line di `state/` → `license.db` tetap.

Tanpa torch, jadi jalan di CI — kecuali test terakhir, yang memeriksa rute ini
benar-benar terpasang di app line asli (`main.create_app`, butuh torch).
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.routes.internal_bahaya import buat_router
from palmgrade.services.hapus_data_line import PENANDA, hapus_kalau_diminta
from palmgrade.workers.runtime_state import RuntimeState

SECRET = "e2e-bahaya-secret"
HEADER = {"x-internal-secret": SECRET}


@pytest.fixture
def line(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.delenv("ARTIFACTS_DIR", raising=False)
    monkeypatch.delenv("REKAMAN_DIR", raising=False)
    settings = replace(Settings(), repo_root=tmp_path)

    # Bentuk folder line di PC pabrik (`/opt/palmgrade/autograde/artifacts/line-1`).
    foto = settings.results_dir / "2026-09-25" / "101500_B1234XY_abcd1234"
    for varian in ("bbox/Ripe", "clean/Ripe", "thumb/Ripe"):
        (foto / varian).mkdir(parents=True)
        (foto / varian / "20260925_101501_auto.webp").write_bytes(b"w" * 32)
    (settings.results_dir / "2026-09-25" / "20260925_101501_ripeness.json").write_text("{}")
    (settings.artifacts_dir / "outbox.db").write_bytes(b"outbox")
    (settings.artifacts_dir / "license.db").write_bytes(b"lisensi")
    settings.state_dir.mkdir(parents=True)
    (settings.state_dir / "upload_manifest.db").write_bytes(b"manifest")

    state = RuntimeState()
    keluar: list[float] = []
    app = FastAPI()
    app.include_router(
        buat_router(settings=lambda: settings, state=lambda: state, keluar=keluar.append)
    )
    return TestClient(app), settings, state, keluar


def test_perintah_lalu_boot_mengosongkan_line(line):
    client, settings, _state, keluar = line

    res = client.post(
        "/internal/hapus-data",
        json={"mode": "transaksi", "diminta_oleh": "support@pks.test"},
        headers=HEADER,
    )
    assert res.status_code == 200, res.text
    assert keluar == [1.0]  # di pabrik: os._exit → restart: unless-stopped

    # "Boot" berikutnya: awal lifespan main.py.
    hasil = hapus_kalau_diminta(settings.artifacts_dir, settings.state_dir)

    assert hasil["gagal"] == 0
    assert hasil["diminta_oleh"] == "support@pks.test"
    assert sorted(p.name for p in settings.artifacts_dir.iterdir()) == ["license.db"]
    assert (settings.artifacts_dir / "license.db").read_bytes() == b"lisensi"
    assert list(settings.state_dir.iterdir()) == []


def test_boot_biasa_tidak_menyentuh_apa_pun(line):
    _client, settings, _state, _keluar = line
    sebelum = sorted(str(p) for p in settings.artifacts_dir.rglob("*"))

    assert hapus_kalau_diminta(settings.artifacts_dir, settings.state_dir) is None

    assert sorted(str(p) for p in settings.artifacts_dir.rglob("*")) == sebelum


def test_truk_terpasang_tidak_meninggalkan_penanda(line):
    """Ditolak berarti ditolak: tanpa penanda, restart berikutnya (karena apa
    pun) tidak boleh menghapus data yang sedang dipakai truk itu."""
    client, settings, state, keluar = line
    state.current_assignment_id = "assign-aktif"

    res = client.post(
        "/internal/hapus-data", json={"mode": "semua", "diminta_oleh": "s"}, headers=HEADER
    )

    assert res.status_code == 409
    assert not (settings.artifacts_dir / PENANDA).exists()
    assert hapus_kalau_diminta(settings.artifacts_dir, settings.state_dir) is None
    assert keluar == []


def test_rute_terpasang_di_app_line_sungguhan():
    """`main.create_app()` memasang router ini. Butuh torch (app line menarik
    YOLO), jadi dilewati di CI — penjaga teksnya ada di
    `tests/unit/test_main_bahaya_wiring.py`."""
    pytest.importorskip("torch")
    pytest.importorskip("cv2")
    from palmgrade.main import create_app

    jalur = {getattr(r, "path", "") for r in create_app().routes}
    assert {"/internal/hapus-data", "/internal/rekam/hapus", "/internal/rekam/berkas"} <= jalur
