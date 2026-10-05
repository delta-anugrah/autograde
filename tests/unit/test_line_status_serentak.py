"""`LineStatusWorker` reads the lines side by side (batch 6.5).

Before, the three lines were read one after another. A line that hangs until its timeout
(1.5 s) held up the status of the two healthy lines behind it, every round, and with it the
piston button and the alarm ribbon the operator looks at.

The fake client below answers when the test lets it, so nothing here depends on wall time.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

from palmgrade.core.config import Settings
from palmgrade.workers import line_status_worker
from palmgrade.workers.line_status_worker import LineStatusWorker

SEHAT = {"piston": {}, "alarms": []}


def _lines():
    return replace(Settings()).console_lines


class KlienTertahan:
    """`status()` of the lines in `tertahan` waits for `lepas`; the others answer at once."""

    def __init__(self, tertahan: set[str] = frozenset(), jawaban: dict | None = None) -> None:
        self.tertahan = set(tertahan)
        self.jawaban = jawaban or {}
        self.lepas = asyncio.Event()
        self.panggilan: dict[str, int] = {}
        self.sedang_jalan = 0
        self.puncak = 0

    async def status(self, line):
        kode = line.line_code
        self.panggilan[kode] = self.panggilan.get(kode, 0) + 1
        self.sedang_jalan += 1
        self.puncak = max(self.puncak, self.sedang_jalan)
        try:
            await asyncio.sleep(0)
            if kode in self.tertahan:
                await self.lepas.wait()
            return self.jawaban.get(kode, SEHAT)
        finally:
            self.sedang_jalan -= 1


async def _beri_giliran(kali: int = 20) -> None:
    for _ in range(kali):
        await asyncio.sleep(0)


def test_ketiga_line_ditanya_bersamaan():
    klien = KlienTertahan()

    asyncio.run(LineStatusWorker(_lines(), klien).run_once())

    assert klien.puncak == 3, "the lines were asked one after another"


def test_line_yang_menggantung_tidak_menahan_status_dua_line_lain():
    async def skenario():
        klien = KlienTertahan({"line-1"})
        worker = LineStatusWorker(_lines(), klien)
        putaran = asyncio.create_task(worker.run_once())
        await _beri_giliran()

        selagi_menggantung = worker.snapshot()
        klien.lepas.set()
        await putaran
        return selagi_menggantung, worker.snapshot()

    selagi_menggantung, akhir = asyncio.run(skenario())

    assert "line-1" not in selagi_menggantung
    assert selagi_menggantung["line-2"]["reachable"] is True
    assert selagi_menggantung["line-3"]["reachable"] is True
    assert akhir["line-1"]["reachable"] is True


def test_run_loop_tetap_membaca_line_sehat_selama_satu_line_menggantung():
    """Each line keeps its own pace: a line that never answers costs the others no round."""

    async def skenario():
        klien = KlienTertahan({"line-2"})
        worker = LineStatusWorker(_lines(), klien, interval_s=0)
        loop = asyncio.create_task(worker.run_loop())
        await _beri_giliran(60)
        loop.cancel()
        await asyncio.gather(loop, return_exceptions=True)
        return klien.panggilan

    panggilan = asyncio.run(skenario())

    assert panggilan["line-2"] == 1
    assert panggilan["line-1"] >= 5 and panggilan["line-3"] >= 5, panggilan


def test_jawaban_yang_tidak_bisa_dibaca_hanya_menjatuhkan_line_itu(caplog):
    """An answer that is not the expected object used to raise out of the worker and end its
    task for good: every card then kept its last status forever, with nothing in the log."""
    klien = KlienTertahan(jawaban={"line-2": ["bukan", "objek"]})
    worker = LineStatusWorker(_lines(), klien, tenggang_start_s=0)

    with caplog.at_level(logging.WARNING, logger=line_status_worker.__name__):
        for _ in range(line_status_worker.TAK_TERBACA_POLL_BERTURUT):
            asyncio.run(worker.run_once())

    keadaan = worker.snapshot()
    assert keadaan["line-1"]["reachable"] is True and keadaan["line-3"]["reachable"] is True
    assert keadaan["line-2"] == {"reachable": False, "sebab_kode": "lain"}
    baris = [r.getMessage() for r in caplog.records if "line-2" in r.getMessage()]
    assert len(baris) == 1 and "AttributeError" in baris[0], baris


def test_run_loop_bertahan_dari_jawaban_yang_tidak_bisa_dibaca():
    async def skenario():
        klien = KlienTertahan(jawaban={"line-2": ["bukan", "objek"]})
        worker = LineStatusWorker(_lines(), klien, interval_s=0)
        loop = asyncio.create_task(worker.run_loop())
        await _beri_giliran(60)
        masih_jalan = not loop.done()
        loop.cancel()
        await asyncio.gather(loop, return_exceptions=True)
        return masih_jalan, klien.panggilan

    masih_jalan, panggilan = asyncio.run(skenario())

    assert masih_jalan, "one unreadable answer ended the status loop"
    assert min(panggilan.values()) >= 5, panggilan
