"""`GET /internal/camera/settings` on the LINE: the read runs on the capture thread, never in the route."""
from __future__ import annotations

import threading
from dataclasses import replace

import pytest
from ai_palsu import KameraPalsu
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.setelan_kamera import NilaiSetelan
from palmgrade.routes import internal_kamera
from palmgrade.routes.internal_kamera import buat_router
from palmgrade.workers.runtime_state import RuntimeState

SECRET = "rahasia-setelan-kamera"
HEADER = {"x-internal-secret": SECRET}
JALUR = "/internal/camera/settings"
LAMPUNG = [NilaiSetelan("exposure", 4000.0, 15.0, 9959540.0), NilaiSetelan("black_level", 240, 0, 4095, 1)]


class _Pelayan:
    """Stands in for the capture thread: serves the queue until stopped."""

    def __init__(self, state: RuntimeState) -> None:
        self._state, self._henti = state, threading.Event()
        self.utas: list[str] = []
        threading.Thread(target=self._jalan, daemon=True).start()

    def _jalan(self) -> None:
        while not self._henti.is_set():
            if self._state.perintah_kamera.jalankan(self._state.lock):
                self.utas.append(threading.current_thread().name)
            self._henti.wait(0.01)

    def henti(self) -> None:
        self._henti.set()


@pytest.fixture
def line(tmp_path):
    settings = replace(Settings(), internal_secret=SECRET, camera_setelan_dir=tmp_path)
    state = RuntimeState()
    kamera = KameraPalsu()
    kamera.setelan = list(LAMPUNG)
    app = FastAPI()
    app.include_router(buat_router(settings=lambda: settings, state=lambda: state, kamera=lambda: kamera))
    pelayan = _Pelayan(state)
    yield TestClient(app), state, kamera, tmp_path
    pelayan.henti()


def test_tanpa_kunci_401(line):
    client, *_ = line
    assert client.get(JALUR).status_code == 401


def test_baris_dari_kamera_lewat_utas_capture(line):
    client, state, _, _ = line
    state.berkas_fitur_aktif = "models/01102026.mfs"
    jawab = client.get(JALUR, headers=HEADER)
    assert jawab.status_code == 200
    isi = jawab.json()
    assert [b["kunci"] for b in isi["setelan"]] == ["exposure", "black_level"]
    assert isi["setelan"][0]["nilai"] == 4000.0
    assert isi["berkas_tersimpan"] is False
    assert isi["berkas_fitur"] == "models/01102026.mfs"


def test_berkas_tersimpan_dilaporkan(line):
    client, _, _, folder = line
    (folder / f"{Settings().line_code}.mfs").write_text("x")   # the line code the default MACHINE_ID maps to
    assert client.get(JALUR, headers=HEADER).json()["berkas_tersimpan"] is True


def test_bukan_hikrobot_409_tanpa_antrean(line):
    client, state, kamera, _ = line
    kamera.setelan = None
    jawab = client.get(JALUR, headers=HEADER)
    assert jawab.status_code == 409
    assert jawab.json()["detail"]["kode"] == "kamera_tanpa_setelan"
    assert state.perintah_kamera.jalankan(state.lock) == 0


def test_kamera_putus_503(line):
    client, _, kamera, _ = line
    kamera.connected = False
    jawab = client.get(JALUR, headers=HEADER)
    assert jawab.status_code == 503
    assert jawab.json()["detail"]["kode"] == "kamera_tidak_menjawab"


def test_utas_capture_tidak_melayani_503_dalam_batas(monkeypatch, tmp_path):
    """Review Focus 1: a capture thread stuck in a reconnect backoff never serves the queue."""
    monkeypatch.setattr(internal_kamera, "BATAS_PERINTAH_KAMERA_DETIK", 0.1)
    settings = replace(Settings(), internal_secret=SECRET)
    state, kamera = RuntimeState(), KameraPalsu()
    kamera.setelan = list(LAMPUNG)
    app = FastAPI()
    app.include_router(buat_router(settings=lambda: settings, state=lambda: state, kamera=lambda: kamera))
    jawab = TestClient(app).get(JALUR, headers=HEADER)
    assert jawab.status_code == 503
    assert jawab.json()["detail"]["kode"] == "kamera_tidak_menjawab"


def test_semua_node_ditolak_berarti_kamera_tidak_menjawab_503(line):
    """Cable just pulled, `connected` still True: every node errors, which is a silent camera, not one that
    supports nothing (Review Focus 1)."""
    client, _, kamera, _ = line
    kamera.setelan = [NilaiSetelan("exposure", None, kode_galat="0x80000007"),
                      NilaiSetelan("black_level", None, kode_galat="0x80000007")]
    jawab = client.get(JALUR, headers=HEADER)
    assert jawab.status_code == 503
    assert jawab.json()["detail"]["kode"] == "kamera_tidak_menjawab"


def test_satu_node_ditolak_tetap_200(line):
    client, _, kamera, _ = line
    kamera.setelan = [NilaiSetelan("exposure", 4000.0, 15.0, 9959540.0),
                      NilaiSetelan("white_balance", None, kode_galat="0x80000106")]
    jawab = client.get(JALUR, headers=HEADER)
    assert jawab.status_code == 200
    assert [b["didukung"] for b in jawab.json()["setelan"]] == [True, False]
