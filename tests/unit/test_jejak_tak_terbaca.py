"""`JejakTakTerbaca`: the episode rule (domain/episode_tak_terbaca.py) written to a logger, per line."""
from __future__ import annotations

import logging

from palmgrade.services.jejak_tak_terbaca import JejakTakTerbaca

LOGGER = logging.getLogger("uji.jejak_tak_terbaca")


class _Jam:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t


def _pesan(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == LOGGER.name and r.levelno == logging.WARNING]


def test_per_line_dengan_sumber_alasan_mentah_dan_lama(caplog):
    jam = _Jam()
    jejak = JejakTakTerbaca(LOGGER, "diagnostik", jam=jam, mulai=jam.t, tenggang_s=0)
    caplog.set_level(logging.WARNING, logger=LOGGER.name)
    for _ in range(4):
        jejak.gagal("line-1", "bukan_line", "line-1 did not answer: 404 Not Found")
        jejak.gagal("line-2", "kunci_ditolak", "line-2 refused: HTTP 401")
        jam.t += 5
    jejak.pulih("line-1")

    pesan = _pesan(caplog)
    assert pesan == [
        "line-1 tidak terbaca oleh konsol (diagnostik, bukan_line): line-1 did not answer: 404 Not Found",
        "line-2 menolak kunci konsol (diagnostik): INTERNAL_SECRET di line itu beda dari yang dipakai konsol"
        " (line-2 refused: HTTP 401)",
        "line-1 terbaca lagi oleh konsol (diagnostik) sesudah 20 detik, sudah pulih",
    ]


def test_tenggang_start_bawaan_menahan_awal(caplog):
    jam = _Jam()
    jejak = JejakTakTerbaca(LOGGER, "status", jam=jam, mulai=jam.t)
    caplog.set_level(logging.WARNING, logger=LOGGER.name)
    for _ in range(10):
        jejak.gagal("line-3", "tak_terjangkau", "mati")
        jam.t += 1
    jejak.pulih("line-3")
    assert _pesan(caplog) == []
