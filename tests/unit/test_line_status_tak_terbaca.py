"""`LineStatusWorker`: a line the console cannot read is a CONSOLE fact, logged once per episode.

User decision 2026-10-01: outside the Log tab no screen shows system error text, so the
raw reason ("line-1 did not answer: Client error '404 Not Found' ...") must reach the Log
tab instead. The worker polls every second; before this it logged an unreachable line at
DEBUG only (the raw reason reached no one) and wrote a "sudah pulih" line when a line that
refused the key went down. Now: one WARNING when the episode starts (with the raw reason),
one more when its cause changes, one when the line answers again. An episode starts after
`TAK_TERBACA_POLL_BERTURUT` failed polls in a row: one poll past the 1.5 s timeout of a
line busy with inference is a blip, not an event, and must not write two rows each time.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from palmgrade.core.config import LineEndpoint
from palmgrade.domain.line_tak_terbaca import (
    SEBAB_BUKAN_LINE,
    SEBAB_KUNCI_DITOLAK,
    SEBAB_LAIN,
    SEBAB_TAK_TERJANGKAU,
)
from palmgrade.domain.operator_error import LINE_MENOLAK, LINE_TIDAK_MENJAWAB
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.workers.line_status_worker import TAK_TERBACA_POLL_BERTURUT, LineStatusWorker

LINE = LineEndpoint("line-1", "Line 1", 8001, "m-1")
LOGGER = "palmgrade.workers.line_status_worker"
SEHAT = {"piston": {}, "alarms": []}
MATI = LineUnavailable(LINE_TIDAK_MENJAWAB, "line-1 did not answer: All connection attempts failed", line="Line 1")
BUKAN_LINE = LineUnavailable(
    LINE_TIDAK_MENJAWAB,
    "line-1 did not answer: Client error '404 Not Found' for url 'http://line:8001/internal/status'",
    line="Line 1", status=404,
)
TOLAK = LineUnavailable(LINE_MENOLAK, "line-1 refused: HTTP 401 unauthorized", line="Line 1", status=401)


class _Klien:
    def __init__(self, urutan) -> None:
        self._urutan = list(urutan)
        self._ke = 0

    async def status(self, line):
        hasil = self._urutan[min(self._ke, len(self._urutan) - 1)]
        self._ke += 1
        if isinstance(hasil, Exception):
            raise hasil
        return hasil


def _jalankan(urutan, caplog) -> tuple[LineStatusWorker, list[logging.LogRecord]]:
    # No start-up grace here (`tenggang_start_s=0`); the grace has its own test below.
    worker = LineStatusWorker([LINE], _Klien(urutan), tenggang_start_s=0)
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    for _ in urutan:
        asyncio.run(worker.run_once())
    return worker, [r for r in caplog.records if r.name == LOGGER and r.levelno >= logging.WARNING]


def test_ambang_poll_kecil_dan_bernama():
    assert TAK_TERBACA_POLL_BERTURUT == 3


def test_kedip_satu_dua_poll_tidak_ditulis_sama_sekali(caplog):
    """No start row, so no recovery row either."""
    _worker, catatan = _jalankan([SEHAT, MATI, MATI, SEHAT, MATI, SEHAT], caplog)

    assert catatan == []


def test_line_yang_tak_terbaca_ditulis_sekali_dengan_alasan_mentahnya(caplog):
    worker, catatan = _jalankan([SEHAT, *[BUKAN_LINE] * 6], caplog)

    assert len(catatan) == 1, [r.getMessage() for r in catatan]
    pesan = catatan[0].getMessage()
    assert pesan.startswith("line-1 ")
    assert "404 Not Found" in pesan, "the raw reason is the whole point of this row"
    assert SEBAB_BUKAN_LINE in pesan
    assert worker.snapshot()["line-1"]["sebab_kode"] == SEBAB_BUKAN_LINE


def test_pulih_ditulis_sekali_dengan_lamanya(caplog):
    _worker, catatan = _jalankan([MATI, MATI, MATI, MATI, SEHAT, SEHAT], caplog)

    pesan = [r.getMessage() for r in catatan]
    assert len(pesan) == 2, pesan
    assert "All connection attempts failed" in pesan[0]
    assert "line-1" in pesan[1] and "pulih" in pesan[1]


def test_sebab_bergantian_cuma_awal_dan_pulih(caplog):
    """Fix wave ruling: only the FIRST cause when the episode starts, then the recovery;
    a cause change used to write a row on every poll that changed it."""
    _worker, catatan = _jalankan([MATI, TOLAK, MATI, TOLAK, MATI, TOLAK, BUKAN_LINE, SEHAT], caplog)

    pesan = [r.getMessage() for r in catatan]
    assert len(pesan) == 2, pesan
    assert SEBAB_TAK_TERJANGKAU in pesan[0] and "All connection attempts failed" in pesan[0]
    assert "pulih" in pesan[1]


def test_tenggang_start_tidak_menulis_line_yang_masih_memuat_model(caplog):
    """Seen live 2026-10-01: at console boot all three lines were still loading the model."""
    class _Jam:
        t = 5_000.0

        def __call__(self):
            return self.t

    jam = _Jam()
    worker = LineStatusWorker([LINE], _Klien([MATI] * 60 + [SEHAT]), jam=jam, mulai=jam.t)
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    for _ in range(61):
        asyncio.run(worker.run_once())
        jam.t += 1

    assert [r for r in caplog.records if r.name == LOGGER and r.levelno >= logging.WARNING] == []


def test_line_yang_menolak_kunci_lalu_mati_tidak_dicatat_pulih(caplog):
    """The old `_catat_kunci(ditolak=False)` wrote "sudah pulih" the moment such a line went down."""
    _worker, catatan = _jalankan([TOLAK, TOLAK, TOLAK, MATI], caplog)

    pesan = [r.getMessage() for r in catatan]
    assert len(pesan) == 1, pesan            # the same episode: its first cause only
    assert not any("pulih" in p for p in pesan), pesan


def test_galat_tanpa_kode_operator_tetap_ditulis_dengan_jenisnya(caplog):
    worker, catatan = _jalankan([httpx.ConnectError("line mati")] * 3, caplog)

    assert len(catatan) == 1
    assert "ConnectError" in catatan[0].getMessage() and "line mati" in catatan[0].getMessage()
    assert worker.snapshot()["line-1"] == {"reachable": False, "sebab_kode": SEBAB_LAIN}


def test_snapshot_line_tak_terbaca_membawa_kode_status_dan_sebab(caplog):
    worker, _catatan = _jalankan([TOLAK], caplog)

    assert worker.snapshot()["line-1"] == {
        "reachable": False, "kode": LINE_MENOLAK, "status": 401, "sebab_kode": SEBAB_KUNCI_DITOLAK,
    }
