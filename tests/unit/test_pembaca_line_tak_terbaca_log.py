"""Diagnostik and Antrean line point the support to the Log tab; their own failures go there.

Fix wave 2026-10-01: `DevService.diagnostics` (`/health/detail`) and `PantauAntreanLine`
(`/internal/outbox`) wrote the friendly sentence on screen but logged nothing. Same rule
as LineStatusWorker (`JejakTakTerbaca`): one WARNING with the raw reason once a line is
unreadable 3 polls in a row, one on recovery, nothing per poll.
"""
from __future__ import annotations

import asyncio
import logging

from palmgrade.core.config import LineEndpoint
from palmgrade.domain.operator_error import LINE_TIDAK_MENJAWAB
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.services.dev_service import DevService
from palmgrade.services.pantau_antrean_line import PantauAntreanLine

LINE = LineEndpoint("line-1", "Line 1", 8001, "m-1")
MENTAH = "line-1 did not answer: Client error '404 Not Found' for url 'http://line:8001/health/detail'"


class _Klien:
    def __init__(self) -> None:
        self.mati = True

    def _jawab(self, isi):
        if self.mati:
            raise LineUnavailable(LINE_TIDAK_MENJAWAB, MENTAH, line="Line 1", status=404)
        return isi

    async def health_detail(self, line):
        return self._jawab({"status": "ok"})

    async def antrean_line(self, line):
        return self._jawab({"menunggu": 0})


def _jalankan(panggil, klien, caplog, nama_logger) -> list[str]:
    caplog.set_level(logging.WARNING, logger=nama_logger)
    for _ in range(5):
        asyncio.run(panggil())
    klien.mati = False
    asyncio.run(panggil())
    asyncio.run(panggil())
    return [r.getMessage() for r in caplog.records if r.name == nama_logger and r.levelno == logging.WARNING]


def test_diagnostik_mencatat_line_tak_terbaca_sekali_lalu_pulih(tmp_path, caplog):
    klien = _Klien()
    dev = DevService(None, line_client=klien, lines=(LINE,), tenggang_start_s=0)
    pesan = _jalankan(dev.diagnostics, klien, caplog, "palmgrade.services.dev_service")

    assert len(pesan) == 2, pesan
    assert pesan[0].startswith("line-1 tidak terbaca oleh konsol (diagnostik, bukan_line)") and "404 Not Found" in pesan[0]
    assert pesan[1].startswith("line-1 terbaca lagi oleh konsol (diagnostik)")


def test_antrean_line_mencatat_line_tak_terbaca_sekali_lalu_pulih(caplog):
    klien = _Klien()
    pantau = PantauAntreanLine(klien, (LINE,), tenggang_start_s=0)
    pesan = _jalankan(pantau.ringkasan, klien, caplog, "palmgrade.services.pantau_antrean_line")

    assert len(pesan) == 2, pesan
    assert pesan[0].startswith("line-1 tidak terbaca oleh konsol (antrean line, bukan_line)")
    assert pesan[1].startswith("line-1 terbaca lagi oleh konsol (antrean line)")
