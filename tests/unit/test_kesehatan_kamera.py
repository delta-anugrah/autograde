"""Camera health without a temperature sensor: the rules that turn camera numbers into a level.

The Lampung cameras (MV-CS050-10GC) have no `DeviceTemperature` node, so an overheating or
failing camera is read from what it does instead: a frame rate that stays low, frames lost
on the wire, and disconnects. Pure rules, fed a fake clock.
"""
from __future__ import annotations

import pytest

from palmgrade.domain.kesehatan_kamera import (
    AMAN,
    KRITIS,
    WASPADA,
    HitungPutus,
    JendelaFrameHilang,
    PenilaiLaju,
    StatistikAliran,
    ringkas_kesehatan_kamera,
    tingkat_frame_hilang,
    tingkat_putus,
    tingkat_terburuk,
)

# ── frame rate held low ──────────────────────────────────────────────────────


def _jalan(penilai: PenilaiLaju, fps: float, dari: float, sampai: float, target: float = 20.0) -> list:
    """Feed one reading every 10 s, as the capture worker does; collect the transitions."""
    hasil, t = [], dari
    while t <= sampai:
        hasil.append(penilai.nilai(fps, target, t))
        t += 10.0
    return [h for h in hasil if h is not None]


def test_laju_normal_tidak_pernah_turun():
    p = PenilaiLaju()
    assert _jalan(p, 20.0, 0, 600) == []
    assert p.turun is False


def test_laju_rendah_sebentar_tidak_dilaporkan():
    p = PenilaiLaju()
    assert _jalan(p, 12.0, 0, 110) == []          # 110 s below: not yet two minutes
    assert _jalan(p, 20.0, 120, 200) == []
    assert p.turun is False


def test_laju_rendah_dua_menit_jadi_turun_sekali():
    p = PenilaiLaju()
    assert _jalan(p, 12.0, 0, 300) == [True]       # one start, not one per reading
    assert p.turun is True


def test_tepat_di_ambang_masih_normal():
    """90 % of 20 fps is 18: a camera at 18.0 is fine, 17.9 is not."""
    assert _jalan(PenilaiLaju(), 18.0, 0, 300) == []
    assert _jalan(PenilaiLaju(), 17.9, 0, 300) == [True]


def test_pulih_butuh_satu_menit_normal_berturut():
    p = PenilaiLaju()
    _jalan(p, 12.0, 0, 200)
    assert _jalan(p, 20.0, 210, 260) == []         # 50 s back: still marked low
    assert p.turun is True
    assert _jalan(p, 20.0, 270, 270) == [False]    # 60 s back: one end
    assert p.turun is False


def test_naik_turun_tidak_berkedip():
    """A rate that dips and recovers every 30 s never holds two minutes either way."""
    p = PenilaiLaju()
    hasil = []
    for siklus in range(10):
        hasil += _jalan(p, 12.0, siklus * 60, siklus * 60 + 20)
        hasil += _jalan(p, 20.0, siklus * 60 + 30, siklus * 60 + 50)
    assert hasil == []


@pytest.mark.parametrize("target", [0.0, -1.0])
def test_tanpa_target_tidak_dinilai(target):
    """A source with no rate of its own (CAMERA_FPS=0) has nothing to fall short of."""
    assert _jalan(PenilaiLaju(), 3.0, 0, 600, target=target) == []


# ── frames lost in the last 10 minutes ───────────────────────────────────────


def test_belum_ada_bacaan_none():
    assert JendelaFrameHilang().ringkas(0.0) is None


def test_hitung_selisih_bukan_total_sejak_nyala():
    """The SDK counts since grabbing started; the card wants the last 10 minutes."""
    j = JendelaFrameHilang()
    j.tambah(StatistikAliran(diterima=10_000, hilang=50), 0.0)     # baseline only
    j.tambah(StatistikAliran(diterima=10_200, hilang=52), 10.0)
    assert j.ringkas(10.0) == (2, 202)


def test_bacaan_lebih_tua_dari_jendela_dibuang():
    j = JendelaFrameHilang()
    j.tambah(StatistikAliran(diterima=0, hilang=0), 0.0)
    j.tambah(StatistikAliran(diterima=200, hilang=10), 10.0)
    j.tambah(StatistikAliran(diterima=400, hilang=10), 20.0)
    assert j.ringkas(20.0) == (10, 410)
    assert j.ringkas(10.0 + 600.0 + 1) == (0, 200)    # the lossy 10 s slid out


def test_sambung_ulang_mereset_hitungan_sdk():
    """A new handle counts from zero again: a smaller number is a restart, not a negative."""
    j = JendelaFrameHilang()
    j.tambah(StatistikAliran(diterima=50_000, hilang=7), 0.0)
    j.tambah(StatistikAliran(diterima=150, hilang=3), 10.0)
    assert j.ringkas(10.0) == (3, 153)


def test_jendela_kosong_sesudah_lama_tanpa_bacaan_none():
    j = JendelaFrameHilang()
    j.tambah(StatistikAliran(diterima=0, hilang=0), 0.0)
    j.tambah(StatistikAliran(diterima=200, hilang=0), 10.0)
    assert j.ringkas(5_000.0) is None


# ── disconnects in the last 24 hours ─────────────────────────────────────────


def test_putus_dihitung_dalam_24_jam():
    h = HitungPutus()
    for t in (0.0, 100.0, 50_000.0):
        h.catat(t)
    assert h.jumlah(50_000.0) == 3
    assert h.jumlah(86_400.0 + 101.0) == 1


# ── levels ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("hilang", "total", "tingkat"), [
    (0, 12_000, AMAN),
    (1, 12_000, WASPADA),
    (599, 12_000, WASPADA),       # 4.99 %
    (600, 12_000, KRITIS),        # 5 %
    (0, 0, AMAN),
])
def test_tingkat_frame_hilang(hilang, total, tingkat):
    assert tingkat_frame_hilang(hilang, total) == tingkat


@pytest.mark.parametrize(("jumlah", "tingkat"), [(0, AMAN), (1, WASPADA), (2, WASPADA), (3, KRITIS), (9, KRITIS)])
def test_tingkat_putus(jumlah, tingkat):
    assert tingkat_putus(jumlah) == tingkat


def test_tingkat_terburuk():
    assert tingkat_terburuk(AMAN, AMAN) == AMAN
    assert tingkat_terburuk(AMAN, WASPADA, AMAN) == WASPADA
    assert tingkat_terburuk(WASPADA, KRITIS) == KRITIS
    assert tingkat_terburuk() == AMAN


# ── what /health/detail carries ──────────────────────────────────────────────


def test_ringkasan_sehat():
    r = ringkas_kesehatan_kamera(laju_turun=False, frame_hilang=(0, 12_000), putus=0)
    assert r == {
        "fps_kamera_turun": False,
        "frame_hilang": {"hilang": 0, "total": 12_000, "persen": 0.0, "tingkat": AMAN},
        "putus_kamera": {"jumlah": 0, "tingkat": AMAN},
        "kamera_tingkat": AMAN,
    }


def test_ringkasan_tingkat_kamera_yang_terburuk():
    assert ringkas_kesehatan_kamera(laju_turun=True, frame_hilang=None, putus=0)["kamera_tingkat"] == WASPADA
    r = ringkas_kesehatan_kamera(laju_turun=True, frame_hilang=(700, 12_000), putus=1)
    assert r["frame_hilang"]["persen"] == 5.8
    assert r["kamera_tingkat"] == KRITIS
    assert ringkas_kesehatan_kamera(laju_turun=False, frame_hilang=None, putus=3)["kamera_tingkat"] == KRITIS


def test_ringkasan_tanpa_hitungan_aliran():
    assert ringkas_kesehatan_kamera(laju_turun=False, frame_hilang=None, putus=0)["frame_hilang"] is None
