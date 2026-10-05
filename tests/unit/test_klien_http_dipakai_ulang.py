"""`LineClient` and `ErpClient` keep one HTTP client instead of building one per call (batch 6.5).

Building an `httpx.AsyncClient` is not free: without a test transport it loads the CA bundle
into a new TLS context every time, on the console's event loop. `LineStatusWorker` alone did
that three times a second, and `ErpClient` once per message sent to AutoERP.

What must NOT change with the reuse, and is pinned here: each call keeps its own timeout, the
same headers go out, and nothing a server answered (a cookie) rides along on the next call.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx
import pytest

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.integrations.erp.client import ErpClient
from palmgrade.integrations.notifications.line_client import TIMEOUT_SAMBUNG_ULANG_S, LineClient

LINE = LineEndpoint("line-1", "Line 1", 8001, "m-1")
LINE_2 = LineEndpoint("line-2", "Line 2", 8002, "m-2")


@pytest.fixture
def dibuat(monkeypatch) -> list[httpx.AsyncClient]:
    """Every `httpx.AsyncClient` built while the test runs, wherever the code builds it."""
    dibuat: list[httpx.AsyncClient] = []

    class Terhitung(httpx.AsyncClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            dibuat.append(self)

    monkeypatch.setattr(httpx, "AsyncClient", Terhitung)
    return dibuat


class Line:
    """A line that answers every path and remembers what it was asked."""

    def __init__(self, *, kue: bool = False) -> None:
        self.permintaan: list[httpx.Request] = []
        self._kue = kue

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.permintaan.append(request)
        tajuk = {"set-cookie": "sid=Guest; Path=/"} if self._kue else {}
        return httpx.Response(200, json={"message": "pong", "piston": {}}, headers=tajuk)

    def tenggat(self) -> list[float]:
        return [p.extensions["timeout"]["read"] for p in self.permintaan]


def _klien_line(line: Line) -> LineClient:
    setelan = replace(Settings(), console_line_host="http://line", internal_secret="rahasia")
    return LineClient(setelan, transport=httpx.MockTransport(line))


# ------------------------------------------------------------------ LineClient


def test_line_client_memakai_satu_klien_untuk_banyak_panggilan(dibuat):
    line = Line()
    klien = _klien_line(line)

    async def lima_putaran():
        for _ in range(5):
            await klien.status(LINE)
            await klien.status(LINE_2)

    asyncio.run(lima_putaran())

    assert len(line.permintaan) == 10
    assert len(dibuat) == 1, f"{len(dibuat)} HTTP clients were built for 10 calls"


def test_tiap_panggilan_line_tetap_membawa_tenggatnya_sendiri(dibuat):
    line = Line()
    klien = _klien_line(line)

    async def semua():
        await klien.status(LINE)                                  # once a second: 1.5 s
        await klien.health_detail(LINE)                           # support screen: 5 s
        await klien.plc_state(LINE)                               # polling screen: 2 s
        await klien.rekam_status(LINE)                            # 10 s
        await klien.hidup(LINE)                                   # every quarter second: 0.5 s
        await klien.reconnect_camera(LINE, requested_by="uji")
        await klien.set_piston(LINE, open=True, requested_by="uji", requested_at="2026-10-04T00:00:00Z")

    asyncio.run(semua())

    assert line.tenggat() == [1.5, 5.0, 2.0, 10.0, 0.5, TIMEOUT_SAMBUNG_ULANG_S, 10.0]
    assert len(dibuat) == 1


def test_kunci_internal_tetap_ikut_di_tiap_panggilan(dibuat):
    line = Line()
    klien = _klien_line(line)

    async def dua():
        await klien.status(LINE)
        await klien.status(LINE)

    asyncio.run(dua())

    assert [p.headers["x-internal-secret"] for p in line.permintaan] == ["rahasia", "rahasia"]
    assert [str(p.url) for p in line.permintaan] == ["http://line:8001/internal/status"] * 2


def test_event_loop_baru_mendapat_klien_baru(dibuat):
    """A client's connections belong to the loop that opened them. The console has one loop
    for its whole life; tests and scripts that call `asyncio.run` twice must still work."""
    klien = _klien_line(Line())

    asyncio.run(klien.status(LINE))
    asyncio.run(klien.status(LINE))

    assert len(dibuat) == 2


def test_line_client_bisa_ditutup_dan_dipakai_lagi(dibuat):
    klien = _klien_line(Line())

    async def tutup_di_tengah():
        await klien.status(LINE)
        await klien.aclose()
        ditutup = dibuat[0].is_closed
        await klien.status(LINE)
        return ditutup

    assert asyncio.run(tutup_di_tengah()) is True
    assert len(dibuat) == 2 and not dibuat[1].is_closed


def test_menutup_klien_yang_belum_pernah_dipakai_tidak_melempar(dibuat):
    asyncio.run(_klien_line(Line()).aclose())

    assert dibuat == []


# ------------------------------------------------------------------ ErpClient


def _klien_erp(server: Line, **argumen) -> ErpClient:
    return ErpClient("http://erp.local", "k", "s", transport=httpx.MockTransport(server), **argumen)


def test_erp_client_memakai_satu_klien_untuk_banyak_pesan(dibuat):
    server = Line()
    klien = _klien_erp(server)

    async def empat():
        await klien.ping()
        await klien.call_method("erpnext.palm_mill.api.upsert_truck", {"plate_number": "BE 1 AA"})
        await klien.call_method("erpnext.palm_mill.api.upsert_visit", {"name": "V-1"})
        await klien.list_modified_since("Supplier", ["name"], None, limit=5)

    asyncio.run(empat())

    assert len(dibuat) == 1, f"{len(dibuat)} HTTP clients were built for 4 messages"
    assert [p.headers["authorization"] for p in server.permintaan] == ["token k:s"] * 4
    assert [p.url.host for p in server.permintaan] == ["erp.local"] * 4
    assert server.tenggat() == [15.0] * 4


def test_tenggat_erp_dari_pemanggil_tetap_dipakai(dibuat):
    server = Line()

    asyncio.run(_klien_erp(server, timeout=3.0).ping())

    assert server.tenggat() == [3.0]


def test_kue_dari_autoerp_tidak_ikut_ke_pesan_berikutnya(dibuat):
    """With one client per message a cookie could never travel. A kept client would send
    AutoERP's `sid=Guest` back beside the token, and Frappe reads a session before a token."""
    server = Line(kue=True)
    klien = _klien_erp(server)

    async def dua():
        await klien.ping()
        await klien.ping()

    asyncio.run(dua())

    assert ["cookie" in p.headers for p in server.permintaan] == [False, False]


def test_kue_dari_line_tidak_ikut_ke_panggilan_berikutnya(dibuat):
    line = Line(kue=True)
    klien = _klien_line(line)

    async def dua():
        await klien.status(LINE)
        await klien.status(LINE)

    asyncio.run(dua())

    assert ["cookie" in p.headers for p in line.permintaan] == [False, False]


def test_erp_client_bisa_ditutup(dibuat):
    klien = _klien_erp(Line())

    async def pakai_lalu_tutup():
        await klien.ping()
        await klien.aclose()

    asyncio.run(pakai_lalu_tutup())

    assert dibuat[0].is_closed
