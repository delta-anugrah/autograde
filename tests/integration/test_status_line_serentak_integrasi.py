"""Batch 6.5, real parts wired together: `LineStatusWorker` + `LineClient` + three line apps.

The console's real `LineClient` talks to three FastAPI apps through the in-process transport
`LinePerPort` (no sockets). Line 2 holds its `/internal/status` answer until the test lets
it go, like a line that is alive but stuck.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

from antrean_line_rakit import LinePerPort
from fastapi import FastAPI

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.workers.line_status_worker import LineStatusWorker

LINES = (
    LineEndpoint("line-1", "Line 1", 8001, "m-1"),
    LineEndpoint("line-2", "Line 2", 8002, "m-2"),
    LineEndpoint("line-3", "Line 3", 8003, "m-3"),
)
BATAS_TUNGGU_S = 5.0


def _line(tahan: asyncio.Event | None = None) -> FastAPI:
    app = FastAPI()

    @app.get("/internal/status")
    async def status() -> dict:
        if tahan is not None:
            await tahan.wait()
        return {"truck_id": None, "ffb_source": "External", "piston": {"requested": False}, "alarms": []}

    return app


def _klien(apps: dict[int, FastAPI]) -> LineClient:
    setelan = replace(Settings(), console_line_host="http://line", internal_secret="rahasia")
    return LineClient(setelan, transport=LinePerPort(apps))


async def _sampai(syarat) -> None:
    async with asyncio.timeout(BATAS_TUNGGU_S):
        while not syarat():
            await asyncio.sleep(0.005)


def test_line_yang_tersangkut_tidak_menahan_status_dua_line_lain():
    async def skenario():
        tahan = asyncio.Event()
        klien = _klien({8001: _line(), 8002: _line(tahan), 8003: _line()})
        worker = LineStatusWorker(LINES, klien)
        putaran = asyncio.create_task(worker.run_once())
        try:
            await _sampai(lambda: {"line-1", "line-3"} <= set(worker.snapshot()))
            selagi_tersangkut = worker.snapshot()
        finally:
            tahan.set()
            await putaran
            await klien.aclose()
        return selagi_tersangkut, worker.snapshot()

    selagi_tersangkut, akhir = asyncio.run(skenario())

    assert "line-2" not in selagi_tersangkut, "line 2 had not answered yet"
    assert selagi_tersangkut["line-1"]["reachable"] is True
    assert selagi_tersangkut["line-3"]["ffb_source"] == "External"
    assert akhir["line-2"]["reachable"] is True


def test_line_mati_dan_line_sehat_dalam_satu_putaran():
    """A port with no line behind it fails at once; the two others are still read whole."""

    async def skenario():
        klien = _klien({8001: _line(), 8003: _line()})
        worker = LineStatusWorker(LINES, klien)
        await worker.run_once()
        await klien.aclose()
        return worker.snapshot()

    keadaan = asyncio.run(skenario())

    assert keadaan["line-2"]["reachable"] is False
    assert keadaan["line-2"]["sebab_kode"] == "tak_terjangkau"
    assert keadaan["line-1"]["reachable"] is True and keadaan["line-3"]["reachable"] is True


def test_run_loop_membaca_line_sehat_berulang_selama_satu_line_tersangkut():
    async def skenario():
        tahan = asyncio.Event()
        dijawab = {8001: 0, 8003: 0}

        def hitung(port: int) -> FastAPI:
            app = FastAPI()

            @app.get("/internal/status")
            async def status() -> dict:
                dijawab[port] += 1
                return {"piston": {}, "alarms": []}

            return app

        klien = _klien({8001: hitung(8001), 8002: _line(tahan), 8003: hitung(8003)})
        worker = LineStatusWorker(LINES, klien, interval_s=0.001)
        loop = asyncio.create_task(worker.run_loop())
        try:
            await _sampai(lambda: min(dijawab.values()) >= 5)
        finally:
            loop.cancel()
            await asyncio.gather(loop, return_exceptions=True)
            tahan.set()
            await klien.aclose()
        return dijawab, worker.snapshot()

    dijawab, keadaan = asyncio.run(skenario())

    assert min(dijawab.values()) >= 5
    assert "line-2" not in keadaan
