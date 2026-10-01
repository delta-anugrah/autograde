"""`LineStatusWorker` membawa blok `disk` ke layar dan mencatat transisi frame
berhenti (3.6) dan disk (3.7) ke tab Log sekali masing-masing, pola `_catat_ai`.
"""
from __future__ import annotations

import asyncio
import logging

from palmgrade.core.config import LineEndpoint
from palmgrade.workers.line_status_worker import LineStatusWorker

LINE = LineEndpoint("line-1", "Line 1", 8001, "m-1")
SEHAT = {"keadaan": "sehat", "mati": False, "kode": None, "ambang_detik": 30}
BERHENTI = {"keadaan": "frame_berhenti", "mati": False, "kode": "FRAME_BERHENTI", "ambang_detik": 30}


def _disk(tingkat: str, bebas: float) -> dict:
    kode = {"peringatan": "DISK_HAMPIR_PENUH", "kritis": "DISK_KRITIS"}.get(tingkat)
    return {"tingkat": tingkat, "kode": kode, "bebas_gb": bebas, "total_gb": 468.0}


class _Klien:
    def __init__(self, jawaban: list[dict]) -> None:
        self._jawaban = jawaban
        self.i = 0

    async def status(self, line):
        hasil = self._jawaban[min(self.i, len(self._jawaban) - 1)]
        self.i += 1
        return {"piston": None, "alarms": [], "unggah": None, **hasil}


def _putar(worker, kali):
    for _ in range(kali):
        asyncio.run(worker.run_once())


def test_blok_disk_ikut_ke_snapshot_dan_line_lama_none():
    worker = LineStatusWorker([LINE], _Klien([{"ai": SEHAT, "disk": _disk("aman", 232)}]))
    _putar(worker, 1)
    assert worker.snapshot()["line-1"]["disk"]["bebas_gb"] == 232
    lama = LineStatusWorker([LINE], _Klien([{"ai": SEHAT}]))
    _putar(lama, 1)
    assert lama.snapshot()["line-1"]["disk"] is None


def test_frame_berhenti_dan_pulih_dicatat_sekali_masing_masing(caplog):
    caplog.set_level(logging.INFO, logger="palmgrade.workers.line_status_worker")
    jawab = [{"ai": a} for a in (SEHAT, BERHENTI, BERHENTI, BERHENTI, SEHAT, SEHAT)]
    _putar(LineStatusWorker([LINE], _Klien(jawab)), 6)
    info = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    tinggi = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(info) == 2
    assert "line-1" in info[0] and "FRAME_BERHENTI" in info[0]
    assert info[1] == "line-1: kamera mengirim gambar lagi"
    assert tinggi == []


def test_disk_transisi_dicatat_sekali_per_tingkat(caplog):
    caplog.set_level(logging.INFO, logger="palmgrade.workers.line_status_worker")
    urutan = [("aman", 232), ("peringatan", 14), ("peringatan", 13), ("kritis", 4),
              ("kritis", 3), ("aman", 30), ("aman", 30)]
    jawab = [{"ai": SEHAT, "disk": _disk(t, b)} for t, b in urutan]
    _putar(LineStatusWorker([LINE], _Klien(jawab)), len(jawab))
    pesan = [(r.levelname, r.getMessage()) for r in caplog.records if r.levelno == logging.INFO]
    tinggi = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert [lvl for lvl, _ in pesan] == ["INFO", "INFO", "INFO"]
    assert "DISK_HAMPIR_PENUH" in pesan[0][1] and "sisa 14 GB dari 468.0 GB" in pesan[0][1]
    assert "DISK_KRITIS" in pesan[1][1]
    assert pesan[2][1] == "line-1: disk kembali lega, sisa 30 GB dari 468.0 GB"
    assert tinggi == []


def test_disk_tak_terbaca_atau_line_lama_tidak_mencatat(caplog):
    caplog.set_level(logging.INFO, logger="palmgrade.workers.line_status_worker")
    jawab = [{"ai": SEHAT, "disk": {"tingkat": "tidak_terbaca"}}, {"ai": SEHAT}]
    _putar(LineStatusWorker([LINE], _Klien(jawab)), 2)
    assert caplog.records == []
