"""Live scale reading, pure rules: register words -> kg, reading -> tile state."""
from __future__ import annotations

import pytest

from palmgrade.domain import timbangan_live as tl
from palmgrade.domain.timbangan_live import Bacaan, alamat_bit, alamat_word, gabung_kata, ke_kg, ringkas


@pytest.mark.parametrize(
    ("teks", "hasil"),
    [("D100", "D100"), (" d100 ", "D100"), ("ZR2000", "ZR2000"), ("W1A", "W1A"), ("R5", "R5")],
)
def test_alamat_word_sah(teks, hasil):
    assert alamat_word(teks) == hasil


@pytest.mark.parametrize("teks", ["", None, "M100", "D", "100", "D-1", "D100,"])
def test_alamat_word_tidak_sah_berarti_mati(teks):
    assert alamat_word(teks) is None


@pytest.mark.parametrize(("teks", "hasil"), [("m2000", "M2000"), ("X1F", "X1F"), ("B10", "B10")])
def test_alamat_bit_sah(teks, hasil):
    assert alamat_bit(teks) == hasil


@pytest.mark.parametrize("teks", ["", None, "D100", "M", "2000"])
def test_alamat_bit_tidak_sah(teks):
    assert alamat_bit(teks) is None


def test_satu_kata_dipakai_apa_adanya():
    assert gabung_kata([12345]) == 12345
    assert gabung_kata([-3]) == -3


def test_dua_kata_kata_rendah_dulu():
    # 45,000 kg does not fit in 16 bits: low word first, as the PLC keeps a DINT.
    rendah, tinggi = 45000 & 0xFFFF, 45000 >> 16
    # pymcprotocol returns words signed: 45000 & 0xFFFF = 45000 > 32767, so -20536.
    assert gabung_kata([rendah - 65536, tinggi]) == 45000


def test_dua_kata_negatif_tetap_negatif():
    # A scale drifting below zero: -2 as DINT is 0xFFFFFFFE, both words -1 / -2 signed.
    assert gabung_kata([-2, -1]) == -2


def test_jumlah_kata_lain_ditolak():
    with pytest.raises(ValueError):
        gabung_kata([1, 2, 3])


def test_desimal():
    assert ke_kg(12345, 0) == 12345
    assert ke_kg(12345, 1) == 1234.5
    assert ke_kg(12345, 2) == 123.45


def _ringkas(**kw):
    dasar = {"dipakai": True, "bacaan": None, "ok_pada": None, "gagal_pada": None, "sekarang": 100.0}
    return ringkas(**{**dasar, **kw})


def test_tidak_dipakai():
    assert _ringkas(dipakai=False)["keadaan"] == tl.TIDAK_DIPAKAI


def test_belum_ada_jawaban_memeriksa():
    assert _ringkas() == {"keadaan": tl.MEMERIKSA, "kg": None, "umur_detik": None}


def test_belum_pernah_berhasil_tapi_gagal_berarti_putus():
    assert _ringkas(gagal_pada=99.0)["keadaan"] == tl.PUTUS


def test_stabil_dan_bergerak():
    stabil = _ringkas(bacaan=Bacaan(kg=24310, stabil=True), ok_pada=99.5)
    assert stabil == {"keadaan": tl.STABIL, "kg": 24310, "umur_detik": 0.5}
    assert _ringkas(bacaan=Bacaan(kg=24000, stabil=False), ok_pada=99.5)["keadaan"] == tl.BERGERAK


def test_tanpa_bit_stabil_cuma_terbaca():
    assert _ringkas(bacaan=Bacaan(kg=100), ok_pada=99.5)["keadaan"] == tl.TERBACA


def test_gagal_sesudah_berhasil_menyembunyikan_angka():
    hasil = _ringkas(bacaan=Bacaan(kg=24310, stabil=True), ok_pada=98.0, gagal_pada=99.0)
    assert hasil["keadaan"] == tl.PUTUS
    assert hasil["kg"] is None


def test_bacaan_basi_tidak_ditampilkan():
    hasil = _ringkas(bacaan=Bacaan(kg=24310, stabil=True), ok_pada=100.0 - tl.BASI_DETIK - 0.1)
    assert hasil["keadaan"] == tl.PUTUS
    assert hasil["kg"] is None


def test_bit_error_menyembunyikan_angka():
    hasil = _ringkas(bacaan=Bacaan(kg=24310, stabil=True, error=True), ok_pada=99.5)
    assert hasil["keadaan"] == tl.ERROR
    assert hasil["kg"] is None
