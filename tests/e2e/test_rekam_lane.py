"""End-to-end: tombol rekam di konsol sampai ke line dan benar-benar menulis MP4.

Unit test membuktikan recorder-nya benar (`test_video_recorder.py`) dan bahwa
capture worker menyerahkan frame (`test_frame_capture_rekam.py`). Yang belum
terbukti di keduanya adalah lapisan HTTP yang menghubungkannya: kode status yang
dipakai layar untuk membedakan "sudah merekam" dari "disk penuh", dan bahwa
setelan yang dikirim konsol benar-benar dipakai encoder.

App-nya dirakit sendiri di sini dengan dependensi di-override, bukan
`create_app()` — yang itu menarik torch dan menyentuh state milik developer.
"""
from __future__ import annotations

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.core.dependencies import get_runtime_state, get_settings
from palmgrade.routes import internal as internal_routes
from palmgrade.workers.runtime_state import RuntimeState

SECRET = "e2e-internal-secret"
HEADER = {"x-internal-secret": SECRET}
SETELAN = {"width": 320, "height": 240, "fps": 5, "bitrate_kbps": 500}


@pytest.fixture()
def line(tmp_path, monkeypatch):
    monkeypatch.setenv("INTERNAL_SECRET", SECRET)
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("REKAMAN_DIR", str(tmp_path / "videos"))
    # Rem disk dimatikan: yang diuji di sini rantai HTTP-nya, dan ambang
    # sungguhan punya test sendiri di unit.
    monkeypatch.setenv("UPLOAD_DISK_MIN_FREE_GB", "0")
    settings = Settings()
    state = RuntimeState()

    app = FastAPI()
    app.include_router(internal_routes.router)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_runtime_state] = lambda: state
    app.dependency_overrides[internal_routes._verify_internal_secret] = lambda: None

    with TestClient(app) as c:
        yield c, state, tmp_path / "videos"
        if state.video_recorder is not None and state.video_recorder.status()["merekam"]:
            state.video_recorder.stop()


def test_status_awal_tidak_merekam(line):
    c, _state, _dir = line
    res = c.get("/internal/rekam/status", headers=HEADER)
    assert res.status_code == 200, res.text
    assert res.json()["merekam"] is False


def test_mulai_lalu_status_ikut_berubah(line):
    c, _state, _dir = line
    res = c.post("/internal/rekam/mulai", json=SETELAN, headers=HEADER)
    assert res.status_code == 200, res.text
    assert res.json()["merekam"] is True

    assert c.get("/internal/rekam/status", headers=HEADER).json()["merekam"] is True
    c.post("/internal/rekam/stop", headers=HEADER)


def test_setelan_konsol_benar_benar_dipakai(line):
    """Sambungan yang paling mudah putus tanpa terlihat: layar mengirim 10 fps,
    line merekam pada 5 karena payload tidak pernah sampai ke encoder."""
    c, _state, _dir = line
    res = c.post(
        "/internal/rekam/mulai",
        json={"width": 640, "height": 480, "fps": 10, "bitrate_kbps": 1000},
        headers=HEADER,
    )
    assert res.json()["setelan"] == {
        "width": 640, "height": 480, "fps": 10, "bitrate_kbps": 1000
    }
    c.post("/internal/rekam/stop", headers=HEADER)


def test_payload_kosong_memakai_bawaan(line):
    # Layar versi lama boleh mengirim tanpa body sama sekali.
    c, _state, _dir = line
    res = c.post("/internal/rekam/mulai", headers=HEADER)
    assert res.status_code == 200, res.text
    assert res.json()["setelan"]["width"] == 1280
    c.post("/internal/rekam/stop", headers=HEADER)


def test_mulai_dua_kali_jawab_409(line):
    c, _state, _dir = line
    c.post("/internal/rekam/mulai", json=SETELAN, headers=HEADER)
    res = c.post("/internal/rekam/mulai", json=SETELAN, headers=HEADER)
    assert res.status_code == 409
    c.post("/internal/rekam/stop", headers=HEADER)


def test_stop_tanpa_mulai_jawab_409(line):
    c, _state, _dir = line
    assert c.post("/internal/rekam/stop", headers=HEADER).status_code == 409


def test_setelan_ngawur_jawab_400(line):
    # 400 dan bukan 500: salah ketik di layar bukan kerusakan line.
    c, _state, _dir = line
    res = c.post("/internal/rekam/mulai", json={"fps": 999}, headers=HEADER)
    assert res.status_code == 400
    assert "fps" in res.json()["detail"]


def test_rekaman_menghasilkan_berkas_yang_bisa_dibaca(line):
    """Bukti sesungguhnya: MP4-nya ada, berisi, dan bisa dibuka lagi."""
    import cv2

    c, state, videos = line
    hasil = c.post("/internal/rekam/mulai", json=SETELAN, headers=HEADER).json()
    for _ in range(10):
        state.video_recorder.tulis(np.zeros((240, 320, 3), dtype=np.uint8))
    c.post("/internal/rekam/stop", headers=HEADER)

    berkas = videos / hasil["berkas"]
    assert berkas.exists(), f"{berkas} tidak ditulis"
    assert berkas.stat().st_size > 0

    cap = cv2.VideoCapture(str(berkas))
    try:
        assert cap.isOpened(), "berkas ditulis tapi tidak bisa dibuka lagi"
        ok, frame = cap.read()
        assert ok and frame is not None
        assert frame.shape[:2] == (240, 320)
    finally:
        cap.release()


def test_stop_mengembalikan_nama_berkas(line):
    c, _state, _dir = line
    c.post("/internal/rekam/mulai", json=SETELAN, headers=HEADER)
    hasil = c.post("/internal/rekam/stop", headers=HEADER).json()
    assert hasil["berkas"].endswith(".mp4")
    assert hasil["merekam"] is False


def test_rekaman_tidak_menyentuh_folder_artifacts(line, tmp_path):
    """Rekaman bukan bukti grading: retensi `artifacts/` tidak boleh
    menghapusnya diam-diam di tengah penelusuran masalah."""
    c, _state, videos = line
    c.post("/internal/rekam/mulai", json=SETELAN, headers=HEADER)
    c.post("/internal/rekam/stop", headers=HEADER)

    assert list(videos.glob("*.mp4")), "rekaman tidak mendarat di videos/"
    artifacts = tmp_path / "artifacts"
    assert not artifacts.exists() or not list(artifacts.rglob("*.mp4"))
