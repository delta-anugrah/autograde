"""`PelacakTransisi` (batch 3.3): satu baris saat mulai gagal, satu saat pulih.

Yang mahal kalau salah dua arah: menulis tiap percobaan (PLC dicabut = ±10 baris
per detik, log penuh sebelum ada yang sempat membaca), dan diam saat galatnya
BERGANTI jenis di tengah kejadian (jaringan putus lalu kunci ditolak: yang kedua
butuh tindakan lain dan tidak boleh tertelan oleh yang pertama).
"""
from __future__ import annotations

import time

import pytest

from palmgrade.domain.transisi import PelacakTransisi, teks_lama


class _Jam:
    def __init__(self, t: float = 100.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_sehat_sejak_awal():
    p = PelacakTransisi(jam=_Jam())
    assert p.putus is False
    assert p.pulih() is None


def test_kegagalan_pertama_saja_yang_pantas_ditulis():
    p = PelacakTransisi(jam=_Jam())
    hasil = [p.gagal() for _ in range(50)]
    assert hasil == [True] + [False] * 49
    assert p.putus is True


def test_pulih_melaporkan_lama_putus_sekali_saja():
    jam = _Jam(100.0)
    p = PelacakTransisi(jam=jam)
    p.gagal()
    jam.t = 142.5
    p.gagal()
    jam.t = 190.0
    assert p.pulih() == pytest.approx(90.0)
    assert p.pulih() is None
    assert p.putus is False


def test_sesudah_pulih_kejadian_baru_ditulis_lagi():
    p = PelacakTransisi(jam=_Jam())
    p.gagal()
    p.pulih()
    assert p.gagal() is True


def test_jenis_berganti_di_tengah_kejadian_ditulis_lagi_tanpa_menggeser_jam_mulai():
    jam = _Jam(0.0)
    p = PelacakTransisi(jam=jam)
    assert p.gagal("jaringan") is True
    jam.t = 30.0
    assert p.gagal("jaringan") is False
    assert p.gagal("HTTPStatusError") is True
    assert p.gagal("HTTPStatusError") is False
    jam.t = 600.0
    assert p.pulih() == pytest.approx(600.0)


def test_jam_mundur_tidak_menghasilkan_lama_negatif():
    jam = _Jam(100.0)
    p = PelacakTransisi(jam=jam)
    p.gagal()
    jam.t = 50.0
    assert p.pulih() == 0.0


def test_jam_bawaan_monotonic():
    """Jam dinding PC pabrik offline melompat berjam-jam saat NTP datang; lama putus
    yang dilaporkan tidak boleh ikut melompat."""
    assert PelacakTransisi()._jam is time.monotonic


@pytest.mark.parametrize(
    ("detik", "teks"),
    [
        (0.2, "1 detik"),
        (1.0, "1 detik"),
        (59.9, "59 detik"),
        (60.0, "1 menit"),
        (3599.0, "59 menit"),
        (3600.0, "1 jam"),
        (3600.0 + 5 * 60, "1 jam 5 menit"),
        (-3.0, "1 detik"),
    ],
)
def test_teks_lama(detik, teks):
    assert teks_lama(detik) == teks
