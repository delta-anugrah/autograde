"""`LineStatusWorker` membawa blok `ai` line ke layar dan mencatat transisinya
ke tab Log sekali masing-masing (batch 2.1), pola yang sama dengan
`_catat_unggah` / `_catat_kunci`.
"""
from __future__ import annotations

import asyncio
import logging

from palmgrade.core.config import LineEndpoint
from palmgrade.domain.operator_error import LINE_TIDAK_MENJAWAB
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.workers.line_status_worker import LineStatusWorker

LINE = LineEndpoint("line-1", "Line 1", 8001, "m-1")
MATI = {"keadaan": "ai_mati", "mati": True, "kode": "AI_MATI", "sejak": 1.0,
        "umur_detik": 40.0, "ambang_detik": 30}
SEHAT = {"keadaan": "sehat", "mati": False, "kode": None, "sejak": None,
         "umur_detik": 0.4, "ambang_detik": 30}


class _Klien:
    def __init__(self, jawaban) -> None:
        self._jawaban = list(jawaban)
        self.i = 0

    async def status(self, line):
        hasil = self._jawaban[min(self.i, len(self._jawaban) - 1)]
        self.i += 1
        if isinstance(hasil, Exception):
            raise hasil
        return {"piston": None, "alarms": [], "unggah": None, "ai": hasil}


def _putar(worker, kali):
    for _ in range(kali):
        asyncio.run(worker.run_once())


def test_blok_ai_ikut_ke_snapshot():
    worker = LineStatusWorker([LINE], _Klien([MATI]))
    _putar(worker, 1)
    assert worker.snapshot()["line-1"]["ai"] == MATI


def test_line_lama_tanpa_blok_ai_menjadi_none():
    class _KlienLama(_Klien):
        async def status(self, line):
            return {"piston": None}

    worker = LineStatusWorker([LINE], _KlienLama([]))
    _putar(worker, 1)
    assert worker.snapshot()["line-1"]["ai"] is None


def test_mati_dan_pulih_dicatat_sekali_masing_masing(caplog):
    caplog.set_level(logging.WARNING, logger="palmgrade.workers.line_status_worker")
    worker = LineStatusWorker([LINE], _Klien([SEHAT, MATI, MATI, MATI, SEHAT, SEHAT]))
    _putar(worker, 6)

    error = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    warning = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(error) == 1 and "line-1" in error[0] and "AI_MATI" in error[0]
    assert warning == ["line-1: AI memproses lagi"]


def test_line_offline_tidak_terbaca_sebagai_pulih(caplog):
    caplog.set_level(logging.WARNING, logger="palmgrade.workers.line_status_worker")
    mati_total = LineUnavailable(LINE_TIDAK_MENJAWAB, "line-1 did not answer")
    worker = LineStatusWorker([LINE], _Klien([MATI, mati_total, mati_total]))
    _putar(worker, 3)
    assert not [r for r in caplog.records if "memproses lagi" in r.getMessage()]
    assert "ai" not in worker.snapshot()["line-1"]
