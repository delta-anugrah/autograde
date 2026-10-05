"""Console side of the camera settings screen: three lines at once, each failure as a code."""
from __future__ import annotations

import asyncio

from palmgrade.core.config import Settings
from palmgrade.domain.operator_error import LINE_TIDAK_MENJAWAB
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.services.setelan_kamera_konsol import SetelanKameraKonsol

L1, L2, L3 = Settings().console_lines
JAWAB = {"berkas_tersimpan": False, "berkas_fitur": "models/01102026.mfs", "setelan": [{"kunci": "exposure"}]}


class _Client:
    def __init__(self, per_line: dict) -> None:
        self.per_line = per_line

    async def camera_settings(self, line):
        hasil = self.per_line[line.line_code]
        if isinstance(hasil, Exception):
            raise hasil
        return hasil


def _galat(status: int | None) -> LineUnavailable:
    return LineUnavailable(LINE_TIDAK_MENJAWAB, "x", line="Line", status=status)


def test_satu_line_mati_tidak_mengosongkan_yang_lain():
    client = _Client({L1.line_code: JAWAB, L2.line_code: _galat(409), L3.line_code: _galat(None)})
    hasil = asyncio.run(SetelanKameraKonsol((L1, L2, L3), client).baca_semua())["lines"]
    assert hasil[L1.line_code] == {"terjangkau": True, **JAWAB}
    assert hasil[L2.line_code] == {"terjangkau": False, "sebab_kode": "bukan_kamera"}
    assert hasil[L3.line_code] == {"terjangkau": False, "sebab_kode": "tak_terjangkau"}


def test_line_versi_lama_404_dan_kamera_diam_503():
    client = _Client({L1.line_code: _galat(404), L2.line_code: _galat(503), L3.line_code: JAWAB})
    hasil = asyncio.run(SetelanKameraKonsol((L1, L2, L3), client).baca_semua())["lines"]
    assert hasil[L1.line_code]["sebab_kode"] == "bukan_line"
    assert hasil[L2.line_code]["sebab_kode"] == "kamera_tidak_menjawab"


def test_galat_tak_terduga_jadi_lain():
    client = _Client({L1.line_code: ValueError("bug"), L2.line_code: JAWAB, L3.line_code: JAWAB})
    hasil = asyncio.run(SetelanKameraKonsol((L1, L2, L3), client).baca_semua())["lines"]
    assert hasil[L1.line_code] == {"terjangkau": False, "sebab_kode": "lain"}
