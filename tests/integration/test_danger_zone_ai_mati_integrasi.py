"""Danger Zone menunggu line yang AI-nya mati sampai prosesnya benar-benar pergi.

Final review line M3: perbaikan gabungan 7389437 (`LineClient.hidup()` menghitung 503
yang membawa `ai.mati` sebagai proses hidup) cuma diuji dengan badan jawaban tulisan
tangan. Di sini rantainya sungguhan: penjaga AI + worker deteksi asli (`LinePalsu`),
rute `/health` asli lewat ASGI, `LineClient` asli, dan `BahayaService._tunggu_mati`
asli dengan aturan dua kali tidak menjawab. Mengganti nama `mati` atau blok `ai` di
skema `/health` membuat test ini merah, bukan konsol yang menghapus datanya sementara
line masih menguras antrean simpannya.

`os._exit` line ditiru transport yang mulai menolak sambungan sesudah `HIDUP_S`.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import replace

import httpx
import pytest
from ai_palsu import LinePalsu
from fastapi import FastAPI

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.health_ringan import buat_router_health
from palmgrade.services.bahaya_service import BahayaService
from palmgrade.services.health_service import HealthService

HIDUP_S = 1.0
ENDPOINT = LineEndpoint("line-1", "Line 1", 8001, "m-1")


class _Outbox:
    def pending_count(self) -> int:
        return 0

    def failed_count(self) -> int:
        return 0


class _MatiSesudah(httpx.AsyncBaseTransport):
    """Line yang menjawab lewat app aslinya, lalu `os._exit` sesudah `hidup_s`."""

    def __init__(self, app: FastAPI, hidup_s: float) -> None:
        self._asgi = httpx.ASGITransport(app=app)
        self._mati_at = time.monotonic() + hidup_s
        self.status: list[int] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if time.monotonic() >= self._mati_at:
            raise httpx.ConnectError("Connection refused", request=request)
        jawab = await self._asgi.handle_async_request(request)
        self.status.append(jawab.status_code)
        return jawab


def _line(keadaan: str) -> FastAPI:
    line = LinePalsu()
    line.mulai()
    if keadaan == "ai_mati":
        line.pipeline.galat = RuntimeError("CUDA error: an illegal memory access")
    line.jalan(35)
    if keadaan == "kamera_putus":
        line.kamera.connected = False
    assert line.penjaga.nilai().keadaan.value == keadaan
    health = HealthService(settings=line.settings, state=line.state, camera=line.kamera, outbox=_Outbox())
    app = FastAPI()
    app.include_router(buat_router_health(lambda: health))
    return app


def _bahaya(tmp_path, transport: httpx.AsyncBaseTransport) -> BahayaService:
    return BahayaService(
        ConsoleStore(tmp_path / "console.db"),
        LogStore(tmp_path / "log.db"),
        LineClient(replace(Settings(), console_line_host="http://line"), transport=transport),
        (ENDPOINT,),
        ErpOutboxStore(tmp_path / "erp_outbox.db"),
        erp_aktif=False,
        hari_kerja=lambda: "2026-09-29",
        tunggu_mati_s=6.0,
        jeda_cek_s=0.25,
    )


@pytest.mark.parametrize("keadaan", ["ai_mati", "sehat", "kamera_putus"])
def test_konsol_menunggu_sampai_line_benar_benar_pergi(tmp_path, keadaan):
    transport = _MatiSesudah(_line(keadaan), HIDUP_S)
    bahaya = _bahaya(tmp_path, transport)

    mulai = time.monotonic()
    belum_mati = asyncio.run(bahaya._tunggu_mati([ENDPOINT], jeda=0.0))
    lama = time.monotonic() - mulai

    assert belum_mati == set()
    assert lama >= HIDUP_S, f"konsol berhenti menunggu sesudah {lama:.2f} dtk, line masih hidup"
    assert lama < 4.0
    assert set(transport.status) == ({503} if keadaan == "ai_mati" else {200})
