"""`LineStatusWorker` (polling 1 detik) harus membedakan kunci ditolak dari line
mati di `state`, dan mencatat WARNING satu kali per transisi, bukan tiap poll.

Sebelum ini semua exception (mati ATAU kunci ditolak) jatuh ke satu cabang
`except Exception` yang menulis `reachable: False` dan log DEBUG saja: tab Log
tidak pernah menunjukkan kunci yang salah, dan layar operator tidak bisa
membedakan "line mati" dari "line hidup, kunci beda".
"""
from __future__ import annotations

import asyncio
import logging

from palmgrade.core.config import LineEndpoint
from palmgrade.domain.operator_error import LINE_MENOLAK, LINE_TIDAK_MENJAWAB
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.workers.line_status_worker import LineStatusWorker

LINE = LineEndpoint("line-1", "Line 1", 8001, "m-1")


class _KlienPalsu:
    def __init__(self, efek) -> None:
        self._efek = list(efek)
        self.panggilan = 0

    async def status(self, line):
        hasil = self._efek[min(self.panggilan, len(self._efek) - 1)]
        self.panggilan += 1
        if isinstance(hasil, Exception):
            raise hasil
        return hasil


def test_kunci_ditolak_ditandai_terpisah_dari_reachable_false():
    tolak = LineUnavailable(LINE_MENOLAK, "line-1 refused: HTTP 401", line="Line 1", status=401)
    worker = LineStatusWorker([LINE], _KlienPalsu([tolak]))
    asyncio.run(worker.run_once())

    state = worker.snapshot()["line-1"]
    assert state["reachable"] is False
    assert state.get("kode") == LINE_MENOLAK


def test_line_mati_sungguhan_tidak_membawa_kode_ditolak():
    mati = LineUnavailable(LINE_TIDAK_MENJAWAB, "line-1 did not answer")
    worker = LineStatusWorker([LINE], _KlienPalsu([mati]))
    asyncio.run(worker.run_once())

    state = worker.snapshot()["line-1"]
    assert state["reachable"] is False
    assert state.get("kode") != LINE_MENOLAK


def test_warning_ditulis_sekali_per_transisi_bukan_tiap_poll(caplog):
    tolak = LineUnavailable(LINE_MENOLAK, "line-1 refused: HTTP 401", line="Line 1", status=401)
    worker = LineStatusWorker([LINE], _KlienPalsu([tolak, tolak, tolak]))

    caplog.set_level(logging.WARNING, logger="palmgrade.workers.line_status_worker")
    asyncio.run(worker.run_once())
    asyncio.run(worker.run_once())
    asyncio.run(worker.run_once())

    warnings_ditolak = [r for r in caplog.records if "menolak" in r.message.lower() or "401" in r.message]
    assert len(warnings_ditolak) == 1


def test_warning_pulih_ditulis_saat_kembali_diterima(caplog):
    tolak = LineUnavailable(LINE_MENOLAK, "line-1 refused: HTTP 401", line="Line 1", status=401)
    ok = {"piston": {}}
    worker = LineStatusWorker([LINE], _KlienPalsu([tolak, ok]))

    caplog.set_level(logging.WARNING, logger="palmgrade.workers.line_status_worker")
    asyncio.run(worker.run_once())
    asyncio.run(worker.run_once())

    assert worker.snapshot()["line-1"]["reachable"] is True
    pulih = [r for r in caplog.records if "pulih" in r.message.lower() or "diterima" in r.message.lower()]
    assert len(pulih) == 1
