"""Router internal Danger Zone di sisi LINE — tanpa torch, jadi jalan di CI.

`routes/internal.py` menarik torch lewat controller-nya, dan semua test lane-nya
dilewati di CI. Fitur yang menghapus data tidak boleh diuji cuma di laptop, jadi
router ini dirakit lewat fungsi pabrik: Settings, RuntimeState, dan fungsi
keluar-proses disuntik — test memberi yang palsu, `main.py` memberi yang asli.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.routes.internal_bahaya import buat_router
from palmgrade.services.hapus_data_line import PENANDA
from palmgrade.workers.runtime_state import RuntimeState

SECRET = "rahasia-internal-uji"
HEADER = {"x-internal-secret": SECRET}


class _RecorderPalsu:
    def __init__(self, merekam: bool) -> None:
        self._merekam = merekam

    def status(self) -> dict:
        return {"merekam": self._merekam}


@pytest.fixture
def line(tmp_path, monkeypatch):
    # Satu secret untuk dua arah (Settings.internal_secret dibaca dari WEBHOOK_SECRET).
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.delenv("ARTIFACTS_DIR", raising=False)
    monkeypatch.delenv("REKAMAN_DIR", raising=False)
    monkeypatch.setenv("MACHINE_ID", "d1f9c7b2-8e5a-4c3b-9a1e-2f6d4c8e7b01")
    settings = replace(Settings(), repo_root=tmp_path)
    state = RuntimeState()
    keluar: list[float] = []
    app = FastAPI()
    app.include_router(
        buat_router(settings=lambda: settings, state=lambda: state, keluar=keluar.append)
    )
    return TestClient(app), settings, state, keluar


def test_tanpa_secret_401(line):
    client, settings, _state, keluar = line
    res = client.post("/internal/hapus-data", json={"mode": "transaksi", "diminta_oleh": "s"})
    assert res.status_code == 401
    assert not (settings.artifacts_dir / PENANDA).exists()
    assert keluar == []


def test_secret_salah_401(line):
    client, _settings, _state, _keluar = line
    res = client.get("/internal/rekam/berkas", headers={"x-internal-secret": "salah"})
    assert res.status_code == 401


def test_hapus_data_menulis_penanda_lalu_keluar(line):
    client, settings, _state, keluar = line
    res = client.post(
        "/internal/hapus-data",
        json={"mode": "transaksi", "diminta_oleh": "support@pks.id"},
        headers=HEADER,
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"status": "menghapus", "jeda_detik": 1.0}
    assert (settings.artifacts_dir / PENANDA).exists()
    assert keluar == [1.0]


def test_hapus_data_ditolak_saat_truk_terpasang(line):
    """Pemeriksaan kedua, di proses yang benar-benar tahu keadaan line —
    pola yang sama dengan Uji PLC. Konsol sudah memeriksa, tapi truk bisa
    dipasang di antara pemeriksaan konsol dan perintah ini."""
    client, settings, state, keluar = line
    state.current_assignment_id = "assign-1"

    res = client.post(
        "/internal/hapus-data", json={"mode": "semua", "diminta_oleh": "s"}, headers=HEADER
    )

    assert res.status_code == 409
    assert res.json()["detail"]["kode"] == "truk_terpasang"
    assert not (settings.artifacts_dir / PENANDA).exists()
    assert keluar == []


def test_mode_asing_400(line):
    client, settings, _state, keluar = line
    res = client.post(
        "/internal/hapus-data", json={"mode": "semuanya", "diminta_oleh": "s"}, headers=HEADER
    )
    assert res.status_code == 400
    assert res.json()["detail"]["kode"] == "mode_asing"
    assert not (settings.artifacts_dir / PENANDA).exists()
    assert keluar == []


def _rekaman(settings: Settings) -> None:
    settings.videos_dir.mkdir(parents=True, exist_ok=True)
    kode = settings.line_code
    (settings.videos_dir / f"{kode}_20260925-101500.mp4").write_bytes(b"a" * 40)
    (settings.videos_dir / "line-9_20260925-101500.mp4").write_bytes(b"b" * 5)


def test_rekam_berkas_menghitung_milik_line_ini(line):
    client, settings, _state, _keluar = line
    _rekaman(settings)

    res = client.get("/internal/rekam/berkas", headers=HEADER)

    assert res.status_code == 200
    assert res.json() == {
        "line_code": settings.line_code, "berkas": 1, "bytes": 40, "merekam": False,
    }


def test_rekam_hapus_cuma_milik_line_ini(line):
    client, settings, _state, _keluar = line
    _rekaman(settings)

    res = client.post("/internal/rekam/hapus", headers=HEADER)

    assert res.status_code == 200
    assert res.json() == {"line_code": settings.line_code, "berkas": 1, "bytes": 40}
    assert [p.name for p in settings.videos_dir.iterdir()] == ["line-9_20260925-101500.mp4"]


def test_rekam_hapus_ditolak_saat_merekam(line):
    client, settings, state, _keluar = line
    _rekaman(settings)
    state.video_recorder = _RecorderPalsu(merekam=True)

    res = client.post("/internal/rekam/hapus", headers=HEADER)

    assert res.status_code == 409
    assert res.json()["detail"]["kode"] == "sedang_merekam"
    assert len(list(settings.videos_dir.iterdir())) == 2


def test_rekam_berkas_melapor_sedang_merekam(line):
    client, _settings, state, _keluar = line
    state.video_recorder = _RecorderPalsu(merekam=True)
    assert client.get("/internal/rekam/berkas", headers=HEADER).json()["merekam"] is True


def test_modul_tidak_menarik_torch_cv2_atau_ultralytics():
    """Kalau modul ini suatu hari mengimpor sesuatu yang menarik torch, semua test
    di atas dilewati di CI tanpa ada yang sadar — persis nasib test lane line."""
    src = Path(__file__).resolve().parents[2] / "src"
    skrip = (
        "import sys\n"
        "for m in ('torch', 'cv2', 'ultralytics'):\n"
        "    sys.modules[m] = None\n"
        "import palmgrade.routes.internal_bahaya\n"
        "import palmgrade.services.hapus_data_line\n"
    )
    hasil = subprocess.run(
        [sys.executable, "-c", skrip], capture_output=True, text=True,
        env={"PYTHONPATH": str(src), "PATH": "/usr/bin:/bin"}, timeout=60,
    )
    assert hasil.returncode == 0, hasil.stderr[-800:]
