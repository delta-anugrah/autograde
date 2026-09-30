"""`PantauAntreanLine` (konsol, batch 2.4): satu baris per line apa pun keadaannya, Kirim Ulang tercatat."""
from __future__ import annotations

import asyncio
import logging
import time

import pytest

from palmgrade.core.config import LineEndpoint
from palmgrade.domain.operator_error import LINE_MENOLAK, LINE_TIDAK_DIKENAL, LINE_TIDAK_MENJAWAB, InvalidInput
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.services import pantau_antrean_line
from palmgrade.services.pantau_antrean_line import PantauAntreanLine

LINES = (
    LineEndpoint("line-1", "Line 1", 8001, "m-1"),
    LineEndpoint("line-2", "Line 2", 8002, "m-2"),
    LineEndpoint("line-3", "Line 3", 8003, "m-3"),
)


class _Macet:
    """Line yang menerima sambungan tapi tidak pernah menjawab."""


class _KlienPalsu:
    def __init__(self, jawaban: dict, kirim: dict | None = None) -> None:
        self._jawaban = jawaban
        self._kirim = kirim or {}

    async def antrean_line(self, line: LineEndpoint) -> dict:
        if isinstance(self._jawaban[line.line_code], _Macet):
            await asyncio.sleep(30)
        return _atau_lempar(self._jawaban[line.line_code])

    async def kirim_ulang_antrean_line(self, line: LineEndpoint) -> int:
        return _atau_lempar(self._kirim[line.line_code])


def _atau_lempar(hasil):
    if isinstance(hasil, Exception):
        raise hasil
    return hasil


def test_ringkasan_satu_baris_per_line_apa_pun_keadaannya():
    klien = _KlienPalsu({
        "line-1": {"menunggu": 2, "tersambung": True},
        "line-2": LineUnavailable(LINE_MENOLAK, "line-2 refused: HTTP 401", line="Line 2", status=401),
        "line-3": LineUnavailable(LINE_TIDAK_MENJAWAB, "line-3 did not answer", line="Line 3"),
    })

    hasil = asyncio.run(PantauAntreanLine(klien, LINES).ringkasan())["lines"]

    assert list(hasil) == ["line-1", "line-2", "line-3"]
    assert hasil["line-1"] == {"terjangkau": True, "menunggu": 2, "tersambung": True}
    # `sebab_kode` (2026-10-01): the screen words the reason from it, never from `pesan`.
    assert hasil["line-2"] == {
        "terjangkau": False, "kode": LINE_MENOLAK, "status": 401, "pesan": "line-2 refused: HTTP 401",
        "sebab_kode": "kunci_ditolak",
    }
    assert (hasil["line-3"]["kode"], hasil["line-3"]["status"]) == (LINE_TIDAK_MENJAWAB, None)
    assert hasil["line-3"]["sebab_kode"] == "tak_terjangkau"


def test_galat_tak_terduga_satu_line_tidak_mengosongkan_yang_lain():
    klien = _KlienPalsu({"line-1": RuntimeError("bug"), "line-2": {"menunggu": 0}, "line-3": {"menunggu": 1}})

    hasil = asyncio.run(PantauAntreanLine(klien, LINES).ringkasan())["lines"]

    # An unexpected failure is not "no answer at all": the generic code, not tak_terjangkau.
    assert hasil["line-1"] == {
        "terjangkau": False, "kode": LINE_TIDAK_MENJAWAB, "status": None, "pesan": "bug", "sebab_kode": "lain",
    }
    assert hasil["line-3"]["menunggu"] == 1


def test_status_http_line_ikut_ke_barisnya():
    """Something answering 404 at the line's address (not an AutoGrade line, or too old)."""
    klien = _KlienPalsu({
        "line-1": {"menunggu": 0},
        "line-2": LineUnavailable(LINE_TIDAK_MENJAWAB, "line-2 did not answer: 404", line="Line 2", status=404),
        "line-3": {"menunggu": 0},
    })

    hasil = asyncio.run(PantauAntreanLine(klien, LINES).ringkasan())["lines"]

    assert (hasil["line-2"]["kode"], hasil["line-2"]["status"]) == (LINE_TIDAK_MENJAWAB, 404)
    assert hasil["line-2"]["sebab_kode"] == "bukan_line"


def test_line_macet_tidak_menahan_layar_lebih_dari_batasnya():
    klien = _KlienPalsu({"line-1": {"menunggu": 1}, "line-2": _Macet(), "line-3": {"menunggu": 3}})
    pantau = PantauAntreanLine(klien, LINES, batas_tunggu_s=0.2)

    mulai = time.monotonic()
    hasil = asyncio.run(pantau.ringkasan())["lines"]

    assert time.monotonic() - mulai < 1.0
    assert (hasil["line-2"]["terjangkau"], hasil["line-2"]["kode"]) == (False, LINE_TIDAK_MENJAWAB)
    assert "line-2" in hasil["line-2"]["pesan"]
    assert hasil["line-2"]["sebab_kode"] == "tak_terjangkau"
    assert (hasil["line-1"]["menunggu"], hasil["line-3"]["menunggu"]) == (1, 3)


def test_batas_tunggu_bawaan_di_bawah_timeout_klien():
    assert pantau_antrean_line.BATAS_TUNGGU_LINE_S == 3.0


def test_jawaban_bukan_objek_jadi_baris_galat_line_itu_saja():
    klien = _KlienPalsu({"line-1": [1, 2], "line-2": {"menunggu": 0}, "line-3": {"menunggu": 1}})

    hasil = asyncio.run(PantauAntreanLine(klien, LINES).ringkasan())["lines"]

    assert (hasil["line-1"]["terjangkau"], hasil["line-1"]["kode"]) == (False, LINE_TIDAK_MENJAWAB)
    assert hasil["line-1"]["sebab_kode"] == "lain", "it answered, just not an object"
    assert (hasil["line-2"]["terjangkau"], hasil["line-3"]["menunggu"]) == (True, 1)


def test_kirim_ulang_mencatat_siapa_dan_berapa(caplog):
    pantau = PantauAntreanLine(_KlienPalsu({}, {"line-1": 5}), LINES)

    with caplog.at_level(logging.WARNING, logger=pantau_antrean_line.__name__):
        hasil = asyncio.run(pantau.kirim_ulang("line-1", oleh="support@pks.test"))

    assert hasil == {"line_code": "line-1", "dijadwalkan": 5}
    pesan = [r.getMessage() for r in caplog.records]
    assert any("line-1" in p and "support@pks.test" in p and "5 janjang" in p for p in pesan), pesan


def test_kirim_ulang_line_tidak_dikenal():
    with pytest.raises(InvalidInput) as info:
        asyncio.run(PantauAntreanLine(_KlienPalsu({}), LINES).kirim_ulang("line-9", oleh="s"))
    assert info.value.code == LINE_TIDAK_DIKENAL


def test_kirim_ulang_gagal_diteruskan_dan_dicatat(caplog):
    gagal = LineUnavailable(LINE_MENOLAK, "line-1 refused: HTTP 401", line="Line 1", status=401)
    pantau = PantauAntreanLine(_KlienPalsu({}, {"line-1": gagal}), LINES)

    with caplog.at_level(logging.WARNING, logger=pantau_antrean_line.__name__), pytest.raises(LineUnavailable):
        asyncio.run(pantau.kirim_ulang("line-1", oleh="support@pks.test"))

    assert any("gagal" in r.getMessage() and "support@pks.test" in r.getMessage() for r in caplog.records)
