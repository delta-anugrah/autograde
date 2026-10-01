"""`LineStatusWorker` membawa blok `ai` line ke layar dan mencatat transisinya sekali
masing-masing (batch 2.1) sebagai INFO di `docker logs` konsol. Sejak batch 3.2 yang
sampai tab Log adalah baris milik line itu sendiri, lewat tarikan log line (aturan 35).
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
    caplog.set_level(logging.INFO, logger="palmgrade.workers.line_status_worker")
    worker = LineStatusWorker([LINE], _Klien([SEHAT, MATI, MATI, MATI, SEHAT, SEHAT]))
    _putar(worker, 6)

    info = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    tinggi = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(info) == 2 and "line-1" in info[0] and "AI_MATI" in info[0]
    assert info[1] == "line-1: AI memproses lagi"
    assert tinggi == []


def test_line_offline_tidak_terbaca_sebagai_pulih(caplog):
    caplog.set_level(logging.WARNING, logger="palmgrade.workers.line_status_worker")
    mati_total = LineUnavailable(LINE_TIDAK_MENJAWAB, "line-1 did not answer")
    worker = LineStatusWorker([LINE], _Klien([MATI, mati_total, mati_total]))
    _putar(worker, 3)
    assert not [r for r in caplog.records if "memproses lagi" in r.getMessage()]
    assert "ai" not in worker.snapshot()["line-1"]



def test_ai_mati_lalu_frame_berhenti_tidak_mengaku_memproses_lagi(caplog):
    """Keluar dari AI mati ke frame berhenti: line itu tetap tidak menyortir."""
    frame_berhenti = {"keadaan": "frame_berhenti", "mati": False, "kode": "FRAME_BERHENTI",
                      "sejak": 2.0, "umur_detik": 80.0, "ambang_detik": 30}
    caplog.set_level(logging.INFO, logger="palmgrade.workers.line_status_worker")
    worker = LineStatusWorker([LINE], _Klien([MATI, frame_berhenti]))
    _putar(worker, 2)
    pesan = [r.getMessage() for r in caplog.records]
    assert "line-1: AI tidak lagi dinilai mati (keadaan frame_berhenti)" in pesan
    assert not [p for p in pesan if "memproses lagi" in p]
