"""Camera settings from the line's capture thread to the console's answer, over `httpx.ASGITransport`."""
from __future__ import annotations

import asyncio
import threading
from dataclasses import replace

import httpx
from ai_palsu import KameraPalsu
from fastapi import FastAPI

from palmgrade.core.config import Settings
from palmgrade.domain.setelan_kamera import NilaiSetelan
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.routes.internal_kamera import buat_router
from palmgrade.services.setelan_kamera_konsol import SetelanKameraKonsol
from palmgrade.workers.runtime_state import RuntimeState

SECRET = "kunci-setelan-integrasi"


def test_nilai_kamera_sampai_ke_jawaban_konsol(tmp_path):
    settings = replace(Settings(), internal_secret=SECRET, console_line_host="http://line", repo_root=tmp_path)
    l1 = settings.console_lines[0]
    state, kamera = RuntimeState(), KameraPalsu()
    kamera.setelan = [NilaiSetelan("exposure", 4000.0, 15.0, 9959540.0)]
    state.berkas_fitur_aktif = "models/01102026.mfs"
    app = FastAPI()
    app.include_router(buat_router(settings=lambda: settings, state=lambda: state, kamera=lambda: kamera))
    henti = threading.Event()

    def _capture() -> None:
        while not henti.is_set():
            state.perintah_kamera.jalankan(state.lock)
            henti.wait(0.01)

    threading.Thread(target=_capture, daemon=True).start()
    try:
        client = LineClient(settings, transport=httpx.ASGITransport(app=app))
        hasil = asyncio.run(SetelanKameraKonsol((l1,), client).baca_semua())["lines"][l1.line_code]
    finally:
        henti.set()
    assert hasil["terjangkau"] is True
    assert hasil["berkas_fitur"] == "models/01102026.mfs"
    assert hasil["setelan"][0]["kunci"] == "exposure" and hasil["setelan"][0]["nilai"] == 4000.0
