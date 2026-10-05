"""Benchmark for batch 6.5: the console's line status round and its HTTP clients.

    .venv/bin/python scripts/bench_status_line.py

Three stub "lines" and one stub "AutoERP" listen on free loopback ports inside this process
(plain HTTP, no line, console, camera or GPU involved, and never ports 8100 or 8001 to 8003).
Two ways of doing the same work are timed against them:

* old: what the console did before 6.5. The lines are asked one after another and every call
  builds its own `httpx.AsyncClient`.
* new: the real `LineStatusWorker` + `LineClient` (lines side by side, one kept client) and
  the real `ErpClient`.

Not a test and never run by CI. Loopback has no latency and no TLS handshake, so the gain on
connection reuse towards the real AutoERP (HTTPS) is larger than shown here and is not
measured by this script.
"""
from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palmgrade.core.config import LineEndpoint, Settings  # noqa: E402
from palmgrade.integrations.erp.client import ErpClient  # noqa: E402
from palmgrade.integrations.notifications.line_client import LineClient  # noqa: E402
from palmgrade.workers.line_status_worker import LineStatusWorker  # noqa: E402

TIMEOUT_STATUS_S = 1.5   # `LineClient.status`
PUTARAN = 200
PESAN_ERP = 50
JAWABAN = json.dumps({"truck_id": None, "piston": {}, "alarms": [], "message": "pong"}).encode()


class Stub:
    """A tiny keep-alive HTTP server. `lambat_s` delays every answer; `bisu` never answers."""

    def __init__(self, *, lambat_s: float = 0.0, bisu: bool = False) -> None:
        self.lambat_s = lambat_s
        self.bisu = bisu
        self.port = 0
        self._server: asyncio.AbstractServer | None = None

    async def mulai(self) -> Stub:
        self._server = await asyncio.start_server(self._layani, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def tutup(self) -> None:
        self._server.close()

    async def _layani(self, baca: asyncio.StreamReader, tulis: asyncio.StreamWriter) -> None:
        try:
            while True:
                kepala = await baca.readuntil(b"\r\n\r\n")
                panjang = 0
                for baris in kepala.split(b"\r\n"):
                    if baris.lower().startswith(b"content-length:"):
                        panjang = int(baris.split(b":")[1])
                if panjang:
                    await baca.readexactly(panjang)
                if self.bisu:
                    await asyncio.sleep(3600)
                if self.lambat_s:
                    await asyncio.sleep(self.lambat_s)
                tulis.write(
                    b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: "
                    + str(len(JAWABAN)).encode() + b"\r\n\r\n" + JAWABAN
                )
                await tulis.drain()
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.CancelledError):
            pass
        finally:
            tulis.close()


def _lines(stubs: list[Stub]) -> tuple[LineEndpoint, ...]:
    return tuple(LineEndpoint(f"line-{i}", f"Line {i}", s.port, f"m-{i}") for i, s in enumerate(stubs, 1))


async def _putaran_lama(lines, tercatat: dict[str, float], mulai: float) -> None:
    """Before 6.5: one line after another, a new client per call."""
    for line in lines:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_STATUS_S) as klien:
                res = await klien.get(
                    f"http://127.0.0.1:{line.port}/internal/status",
                    headers={"x-internal-secret": "rahasia"},
                )
            res.json()
        except httpx.HTTPError:
            pass
        tercatat[line.line_code] = time.perf_counter() - mulai


class _PekerjaTercatat(LineStatusWorker):
    """The real worker, noting when each line's status was recorded."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.tercatat: dict[str, float] = {}
        self.mulai = 0.0

    async def _baca_line(self, line) -> None:
        await super()._baca_line(line)
        self.tercatat[line.line_code] = time.perf_counter() - self.mulai


def _median_ms(nilai: list[float]) -> float:
    return statistics.median(nilai) * 1000


async def _ukur_putaran(nama: str, stubs: list[Stub], putaran: int) -> None:
    lines = _lines(stubs)
    setelan = replace(Settings(), console_line_host="http://127.0.0.1", internal_secret="rahasia")
    sehat = [ln.line_code for ln, s in zip(lines, stubs, strict=True) if not s.bisu]

    lama_total, lama_sehat = [], []
    for _ in range(putaran):
        tercatat: dict[str, float] = {}
        mulai = time.perf_counter()
        await _putaran_lama(lines, tercatat, mulai)
        lama_total.append(time.perf_counter() - mulai)
        lama_sehat.append(max(tercatat[k] for k in sehat))

    klien = LineClient(setelan)
    worker = _PekerjaTercatat(lines, klien, tenggang_start_s=3600)
    baru_total, baru_sehat = [], []
    for _ in range(putaran):
        worker.tercatat.clear()
        worker.mulai = time.perf_counter()
        await worker.run_once()
        baru_total.append(time.perf_counter() - worker.mulai)
        baru_sehat.append(max(worker.tercatat[k] for k in sehat))
    await klien.aclose()

    print(
        f"{nama:<44}{_median_ms(lama_sehat):>10.1f}{_median_ms(baru_sehat):>10.1f}"
        f"{_median_ms(lama_total):>12.1f}{_median_ms(baru_total):>10.1f}"
    )


async def _ukur_klien() -> None:
    """Building a client alone, with the default transport as in production."""
    lama = []
    for _ in range(PUTARAN):
        mulai = time.perf_counter()
        async with httpx.AsyncClient(timeout=TIMEOUT_STATUS_S):
            pass
        lama.append(time.perf_counter() - mulai)
    print(f"building one httpx.AsyncClient (median of {PUTARAN}): {_median_ms(lama):.2f} ms")
    print(f"  before 6.5 the status poll alone built 3 per second: {_median_ms(lama) * 3:.1f} ms of every second")
    print("  on the console's event loop; now 0")


async def _ukur_erp(stub: Stub) -> None:
    alamat = f"http://127.0.0.1:{stub.port}"
    mulai = time.perf_counter()
    for _ in range(PESAN_ERP):
        async with httpx.AsyncClient(base_url=alamat, headers={"Authorization": "token k:s"}, timeout=15.0) as klien:
            (await klien.post("/api/method/erpnext.palm_mill.api.upsert_visit", json={"name": "V"})).json()
    lama = time.perf_counter() - mulai

    erp = ErpClient(alamat, "k", "s")
    mulai = time.perf_counter()
    for _ in range(PESAN_ERP):
        await erp.call_method("erpnext.palm_mill.api.upsert_visit", {"name": "V"})
    baru = time.perf_counter() - mulai
    await erp.aclose()
    print(
        f"{PESAN_ERP} messages to the AutoERP stub (plain HTTP, loopback): "
        f"old {lama / PESAN_ERP * 1000:.2f} ms per message, new {baru / PESAN_ERP * 1000:.2f} ms per message"
    )


async def main() -> None:
    print(f"httpx {httpx.__version__}, loopback stubs, median, milliseconds\n")
    await _ukur_klien()
    print()
    print(f"{'one status round, three lines':<44}{'healthy lines recorded':>20}{'whole round':>22}")
    print(f"{'':<44}{'old':>10}{'new':>10}{'old':>12}{'new':>10}")
    skenario = [
        ("all three answer at once", [Stub(), Stub(), Stub()], PUTARAN),
        ("all three answer after 20 ms", [Stub(lambat_s=0.02) for _ in range(3)], 50),
        ("line 1 never answers (1.5 s timeout)", [Stub(bisu=True), Stub(), Stub()], 3),
        ("lines 1 and 2 never answer", [Stub(bisu=True), Stub(bisu=True), Stub()], 3),
    ]
    for nama, stubs, putaran in skenario:
        for stub in stubs:
            await stub.mulai()
        await _ukur_putaran(nama, stubs, putaran)
        for stub in stubs:
            await stub.tutup()
    print()
    erp = await Stub().mulai()
    await _ukur_erp(erp)
    await erp.tutup()


if __name__ == "__main__":
    asyncio.run(main())
