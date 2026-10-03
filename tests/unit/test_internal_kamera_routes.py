"""`POST /internal/camera/reconnect` on the LINE: raise the flag, never touch the camera.

Assembled through `buat_router()` with fakes, like `routes/internal_bahaya.py`:
`routes/internal.py` pulls in torch, and this lane has to run in CI.
"""
from __future__ import annotations

import importlib
import logging
import subprocess
import sys
import types
from dataclasses import replace
from pathlib import Path

import pytest
from ai_palsu import KameraPalsu
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.routes import internal_kamera
from palmgrade.routes.internal_kamera import KAMERA_TANPA_SAMBUNG_ULANG, buat_router
from palmgrade.workers.runtime_state import RuntimeState

SECRET = "rahasia-internal-kamera"
HEADER = {"x-internal-secret": SECRET}
JALUR = "/internal/camera/reconnect"


class KameraTanpaSentuh(KameraPalsu):
    """The route may read `supports_reconnect`, nothing else: the SDK is not thread safe."""

    def connect(self, index=0, serial=None, feature_file=None) -> None:
        raise AssertionError("the route connected the camera itself")

    def disconnect(self) -> None:
        raise AssertionError("the route disconnected the camera itself")


@pytest.fixture
def line():
    settings = replace(Settings(), internal_secret=SECRET)
    state = RuntimeState()
    kamera = KameraTanpaSentuh()
    kamera.bisa_sambung_ulang = True
    app = FastAPI()
    app.include_router(buat_router(settings=lambda: settings, state=lambda: state, kamera=lambda: kamera))
    return TestClient(app), state, kamera


def test_without_the_secret_401_and_no_request(line):
    client, state, _ = line
    assert client.post(JALUR, json={"requested_by": "Pak Budi"}).status_code == 401
    assert state.ambil_permintaan_sambung_ulang() is None


def test_a_camera_line_accepts_and_leaves_the_work_to_the_capture_thread(line):
    client, state, _ = line
    jawab = client.post(JALUR, json={"requested_by": "Pak Budi"}, headers=HEADER)
    assert jawab.status_code == 202
    assert jawab.json() == {"status": "requested"}
    assert state.ambil_permintaan_sambung_ulang() == "Pak Budi"


def test_without_a_name_the_request_still_goes_through(line):
    client, state, _ = line
    assert client.post(JALUR, json={}, headers=HEADER).status_code == 202
    assert state.ambil_permintaan_sambung_ulang() == "?"


def test_a_video_or_photo_source_is_refused_with_a_code(line):
    client, state, kamera = line
    kamera.bisa_sambung_ulang = False
    jawab = client.post(JALUR, json={"requested_by": "Pak Budi"}, headers=HEADER)
    assert jawab.status_code == 409
    assert jawab.json()["detail"]["kode"] == KAMERA_TANPA_SAMBUNG_ULANG == "kamera_tanpa_sambung_ulang"
    assert state.ambil_permintaan_sambung_ulang() is None


def test_a_body_of_the_wrong_shape_is_refused(line):
    client, state, _ = line
    assert client.post(JALUR, json={"requested_by": ["x"]}, headers=HEADER).status_code == 422
    assert state.ambil_permintaan_sambung_ulang() is None


def test_the_request_is_logged_with_who_asked(line, caplog):
    client, _, _ = line
    with caplog.at_level(logging.INFO, logger=internal_kamera.__name__):
        client.post(JALUR, json={"requested_by": "Pak Budi"}, headers=HEADER)
    assert [r.levelno for r in caplog.records if "Pak Budi" in r.getMessage()] == [logging.INFO]


def test_a_photo_source_has_no_camera_to_reconnect(monkeypatch):
    """The photo source would only re-read the same file: the button answers 409 for it,
    as for a video file. cv2 is stubbed: CI has none, and this needs no image."""
    nama = "palmgrade.integrations.camera.photo_camera"
    monkeypatch.setitem(sys.modules, "cv2", types.SimpleNamespace())
    monkeypatch.delitem(sys.modules, nama, raising=False)
    try:
        modul = importlib.import_module(nama)
        assert modul.PhotoCamera(path="contoh.jpg").supports_reconnect is False
    finally:
        sys.modules.pop(nama, None)  # bound to the fake cv2; a later import gets the real one


def test_module_does_not_pull_in_torch_cv2_or_ultralytics():
    src = Path(__file__).resolve().parents[2] / "src"
    skrip = (
        "import sys\n"
        "for m in ('torch', 'cv2', 'ultralytics'):\n"
        "    sys.modules[m] = None\n"
        "import palmgrade.routes.internal_kamera\n"
        "import palmgrade.workers.frame_capture_worker\n"
    )
    hasil = subprocess.run(
        [sys.executable, "-c", skrip], capture_output=True, text=True,
        env={"PYTHONPATH": str(src), "PATH": "/usr/bin:/bin"}, timeout=60,
    )
    assert hasil.returncode == 0, hasil.stderr[-800:]
