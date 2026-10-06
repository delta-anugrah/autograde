"""How long the live kilograms held, so a scan may save a reading without a stable bit
(user 2026-10-06): the same number for 2 s, restarted by a change or a cut."""
from __future__ import annotations

from palmgrade.domain.timbangan_live import Bacaan
from palmgrade.services.timbangan_live import TimbanganLive


class _Jam:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def _live():
    jam = _Jam()
    return TimbanganLive(dipakai=True, jam=jam), jam


def test_stabil_langsung_layak():
    live, _ = _live()
    live.berhasil(Bacaan(kg=14820, stabil=True))
    assert live.berat_layak(1000) == 14820


def test_terbaca_layak_sesudah_angka_sama_2_detik():
    live, jam = _live()
    live.berhasil(Bacaan(kg=14820))
    assert live.berat_layak(1000) is None
    jam.t += 1.0
    live.berhasil(Bacaan(kg=14820))
    assert live.berat_layak(1000) is None
    jam.t += 1.0
    live.berhasil(Bacaan(kg=14820))
    assert live.berat_layak(1000) == 14820


def test_angka_berubah_mengulang_tahan():
    live, jam = _live()
    live.berhasil(Bacaan(kg=14000))
    jam.t += 3.0
    live.berhasil(Bacaan(kg=14820))
    assert live.berat_layak(1000) is None
    jam.t += 2.0
    live.berhasil(Bacaan(kg=14820))
    assert live.berat_layak(1000) == 14820


def test_putus_mengulang_tahan():
    live, jam = _live()
    live.berhasil(Bacaan(kg=14820))
    jam.t += 3.0
    live.gagal()
    jam.t += 0.5
    live.berhasil(Bacaan(kg=14820))
    # The same number as before the cut is not 3.5 s of holding: one read since it came back.
    assert live.berat_layak(1000) is None
    jam.t += 2.0
    live.berhasil(Bacaan(kg=14820))
    assert live.berat_layak(1000) == 14820


def test_tidak_dipakai_tidak_pernah_layak():
    live = TimbanganLive(dipakai=False)
    assert live.berat_layak(1000) is None


def test_satu_bacaan_lalu_macet_bukan_tahan_2_detik():
    live, jam = _live()
    live.berhasil(Bacaan(kg=15000))
    jam.t += 2.5  # no new read: the link stalls
    assert live.berat_layak(1000) is None
