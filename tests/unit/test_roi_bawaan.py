"""The detection box a line uses when the console never set one: its `.env` ROI (2026-10-05).

Settings showed four empty inputs for "use this PC's own box", and nobody could see which box
that was. The console does not receive `ROI_*` (the lines do), so it asks the lines. All three
read the same `.env`, so the first line that answers speaks for the PC.
"""
from __future__ import annotations

import asyncio

from palmgrade.core.config import LineEndpoint
from palmgrade.services.roi_bawaan import roi_bawaan

LINES = (
    LineEndpoint("line-1", "Line 1", 8001, "m-1"),
    LineEndpoint("line-2", "Line 2", 8002, "m-2"),
    LineEndpoint("line-3", "Line 3", 8003, "m-3"),
)
KOSONG = {"roi_x1": None, "roi_y1": None, "roi_x2": None, "roi_y2": None, "line_code": None}


class Klien:
    def __init__(self, jawaban: dict) -> None:
        self.jawaban = jawaban  # line_code -> dict, or an Exception to raise
        self.sedang = 0
        self.puncak = 0

    async def setelan_aktif(self, line):
        self.sedang += 1
        self.puncak = max(self.puncak, self.sedang)
        try:
            await asyncio.sleep(0)
            jawab = self.jawaban.get(line.line_code, OSError("line mati"))
            if isinstance(jawab, Exception):
                raise jawab
            return jawab
        finally:
            self.sedang -= 1


def _tanya(jawaban: dict) -> tuple[dict, Klien]:
    klien = Klien(jawaban)
    return asyncio.run(roi_bawaan(LINES, klien)), klien


def test_line_pertama_yang_menjawab_mewakili_pc():
    hasil, _ = _tanya({"line-2": {"roi_env": [100, 100, 1180, 620]}, "line-3": {"roi_env": [1, 2, 3, 4]}})

    assert hasil == {"roi_x1": 100, "roi_y1": 100, "roi_x2": 1180, "roi_y2": 620, "line_code": "line-2"}


def test_tidak_ada_line_yang_menjawab_berarti_tidak_diketahui():
    hasil, _ = _tanya({})

    assert hasil == KOSONG


def test_line_versi_lama_tanpa_kotak_env_dilewati():
    hasil, _ = _tanya({"line-1": {"conf_threshold": 0.6}, "line-2": {"roi_env": [0, 0, 0, 0]}})

    assert hasil == {"roi_x1": 0, "roi_y1": 0, "roi_x2": 0, "roi_y2": 0, "line_code": "line-2"}


def test_jawaban_yang_tidak_berbentuk_kotak_dilewati():
    hasil, _ = _tanya({
        "line-1": {"roi_env": [100, 100, 1180]},
        "line-2": {"roi_env": ["a", "b", "c", "d"]},
        "line-3": {"roi_env": [-5, 0, 10, 10]},
    })

    assert hasil == KOSONG


def test_ketiga_line_ditanya_bersamaan():
    """A dead line must not hold the Settings screen for the others' timeouts."""
    _, klien = _tanya({"line-3": {"roi_env": [100, 100, 1180, 620]}})

    assert klien.puncak == 3
