"""End-to-end: a line the console cannot read, friendly on screen, raw in the Log tab.

User decision 2026-10-01 after testing PR #200: the Status tab showed "line-1 did not
answer: Client error '404 Not Found' for url ..." on the Diagnostik card and in the line
queue. Now the screen says why in plain words (`sebab_kode` from the backend through
KAMUS) and the raw reason is one WARNING row in the Log tab per episode.

Three lines on the console's real `LineClient` (transport `LinePerPort`, no sockets):
line-1 has no process at all, line-2 is something else answering 404, line-3 refuses the
console key. Console: `LineStatusWorker` with the Log tab handler, `DevService`,
`PantauAntreanLine`, the real console routes with a support login; cards and rows are
rendered through node with the real KAMUS.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import replace

import httpx
import pytest
from antrean_line_rakit import LinePerPort, app_konsol, masuk
from fastapi import FastAPI, HTTPException
from konsol_js import HTML, NODE, jalankan

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.core.log_sink import SqliteLogHandler
from palmgrade.domain.role import ROLE_SUPPORT
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.console_deps import get_dev_service
from palmgrade.services.dev_service import DevService
from palmgrade.services.pantau_antrean_line import PantauAntreanLine
from palmgrade.workers.line_status_worker import TAK_TERBACA_POLL_BERTURUT, LineStatusWorker

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")

LINES = (
    LineEndpoint("line-1", "Line 1", 8001, "m-1"),
    LineEndpoint("line-2", "Line 2", 8002, "m-2"),
    LineEndpoint("line-3", "Line 3", 8003, "m-3"),
)
DASH = 'const dash = (v) => (v === null || v === undefined || v === "" ? KOSONG : esc(v));'
DIAG = ["tanda", "diagPlc", "diagAngka", "diagFrame", "diagDisk", "diagLisensi", "diagNol",
        "kunciSebabTakTerbaca", "kartuDiagnostik"]
ANTREAN_LINE = ["kunciSebabTakTerbaca", "keadaanAntreanLine", "barisAntreanLine", "waktu", "lamaProses"]
MENTAH = ("404", "Not Found", "http", "did not answer", "tidak ada line di port", "401", "refused", "HTTP")
DIHARAPKAN = {"line-1": "tak_terjangkau", "line-2": "bukan_line", "line-3": "kunci_ditolak"}


def _kamus_id() -> dict[str, str]:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    blok = re.search(r"^  id: \{(.*?)^  \},", kamus, re.S | re.M).group(1)
    return dict(re.findall(r'(\w+):\s*"((?:[^"\\]|\\.)*)"', blok))


def _esc(teks: str) -> str:
    ganti = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;"}
    return "".join(ganti.get(c, c) for c in teks)


def _bukan_line() -> FastAPI:
    """Something else on the line's port: every path is 404 (no AutoGrade routes)."""
    return FastAPI()


def _menolak_kunci() -> FastAPI:
    app = FastAPI()

    @app.api_route("/{jalur:path}", methods=["GET", "POST"])
    async def tolak(jalur: str) -> None:
        raise HTTPException(status_code=401, detail="x-internal-secret tidak cocok")

    return app


def _line_sehat() -> FastAPI:
    app = FastAPI()

    @app.get("/internal/status")
    async def status() -> dict:
        return {"piston": {}, "alarms": []}

    return app


@pytest.fixture
def konsol(tmp_path):
    log_store = LogStore(tmp_path / "log_kejadian.db")
    handler = SqliteLogHandler(log_store)
    logger = logging.getLogger("palmgrade.workers.line_status_worker")
    transport = LinePerPort({8002: _bukan_line(), 8003: _menolak_kunci()})
    klien = LineClient(replace(Settings(), console_line_host="http://line", internal_secret="rahasia"),
                       transport=transport)
    store = ConsoleStore(tmp_path / "console.db")
    app = app_konsol(store, PantauAntreanLine(klien, LINES))
    app.dependency_overrides[get_dev_service] = lambda: DevService(log_store, line_client=klien, lines=LINES)
    layar = masuk(app, store, role=ROLE_SUPPORT)
    worker = LineStatusWorker(LINES, klien)
    logger.addHandler(handler)
    try:
        yield layar, worker, transport
    finally:
        logger.removeHandler(handler)


def _poll(worker: LineStatusWorker, kali: int = TAK_TERBACA_POLL_BERTURUT) -> None:
    for _ in range(kali):
        asyncio.run(worker.run_once())


def _tab_log(layar) -> list[dict]:
    res = layar.get("/api/console/dev/log?limit=200")
    assert res.status_code == 200, res.text
    return res.json()["items"]


@butuh_node
def test_kartu_diagnostik_ramah_dan_alasan_mentahnya_di_tab_log(konsol):
    layar, worker, _transport = konsol
    _poll(worker)

    lines = layar.get("/api/console/dev/diagnostik").json()["lines"]
    kamus = _kamus_id()
    for kode, sebab in DIHARAPKAN.items():
        assert (lines[kode]["terjangkau"], lines[kode]["sebab_kode"]) == (False, sebab)
        html = jalankan(DIAG, f"kartuDiagnostik({json.dumps(kode)}, {json.dumps(lines[kode])})", tambahan=DASH)
        assert _esc(kamus[f"lineSebab_{sebab}"]) in html, (kode, html)
        for potongan in MENTAH:
            assert potongan not in html, (kode, potongan, html)

    baris = {b["message"].split(" ", 1)[0]: b for b in _tab_log(layar)}
    assert set(baris) == set(DIHARAPKAN), baris
    assert all(b["level"] == "WARNING" and b["count"] == 1 for b in baris.values())
    assert "tidak ada line di port 8001" in baris["line-1"]["message"]
    assert "404 Not Found" in baris["line-2"]["message"]
    assert "401" in baris["line-3"]["message"] and baris["line-3"]["message"].startswith("line-3 menolak kunci")


@butuh_node
def test_antrean_line_memakai_kalimat_ramah_yang_sama(konsol):
    layar, _worker, _transport = konsol

    lines = layar.get("/api/console/dev/antrean/line").json()["lines"]
    kamus = _kamus_id()
    for kode, sebab in DIHARAPKAN.items():
        html = jalankan(ANTREAN_LINE, f"barisAntreanLine({json.dumps(kode)}, {json.dumps(lines[kode])}, 0)",
                        tambahan=DASH)
        assert _esc(kamus[f"lineSebab_{sebab}"]) in html, (kode, html)
        for potongan in MENTAH:
            assert potongan not in html, (kode, potongan, html)


def test_satu_baris_per_kejadian_lalu_satu_saat_pulih(konsol):
    layar, worker, transport = konsol
    _poll(worker, 10)                               # ten seconds unreadable: still one row per line
    assert len(_tab_log(layar)) == 3

    transport._tujuan[8001] = httpx.ASGITransport(app=_line_sehat())
    _poll(worker, 3)

    pesan = [b["message"] for b in _tab_log(layar)]
    assert len(pesan) == 4, pesan
    assert any(p.startswith("line-1 terbaca lagi oleh konsol") and "pulih" in p for p in pesan), pesan
