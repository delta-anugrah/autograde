"""When a line the console cannot read is worth a Log tab row (fix wave, 2026-10-01).

One rule for the three console readers (LineStatusWorker, Diagnostik, Antrean line):
the start is written once the failure lasted `TAK_TERBACA_POLL_BERTURUT` polls in a row,
naming the FIRST cause of the episode, the recovery once, with the duration counted from
the first failed poll; nothing per poll, nothing for a cause change. During
`TENGGANG_START_S` after the console starts (lines still loading their model) no start is
written; a line still unreadable after it is logged normally, counted from its first failure.
"""
from __future__ import annotations

from palmgrade.domain.episode_tak_terbaca import (
    TAK_TERBACA_POLL_BERTURUT,
    TENGGANG_START_S,
    EpisodeTakTerbaca,
)


class _Jam:
    def __init__(self, t: float = 1_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _episode(jam: _Jam, *, tenggang_s: float = 0.0) -> EpisodeTakTerbaca:
    return EpisodeTakTerbaca(mulai=jam.t, jam=jam, tenggang_s=tenggang_s)


def test_konstanta_bernama():
    assert (TAK_TERBACA_POLL_BERTURUT, TENGGANG_START_S) == (3, 120.0)


def test_mulai_ditulis_sekali_sesudah_tiga_poll():
    jam = _Jam()
    e = _episode(jam)
    hasil = []
    for _ in range(6):
        hasil.append(e.gagal("tak_terjangkau", "mati"))
        jam.t += 1
    assert hasil == [None, None, ("tak_terjangkau", "mati"), None, None, None]


def test_kedip_di_bawah_ambang_tidak_mulai_dan_tidak_pulih():
    jam = _Jam()
    e = _episode(jam)
    e.gagal("tak_terjangkau", "x")
    e.gagal("tak_terjangkau", "x")
    assert e.pulih() is None


def test_sebab_bergantian_cuma_sebab_pertama_dan_satu_pulih():
    jam = _Jam()
    e = _episode(jam)
    mulai = []
    for i in range(10):
        sebab = "tak_terjangkau" if i % 2 == 0 else "kunci_ditolak"
        hasil = e.gagal(sebab, f"mentah-{i}")
        if hasil is not None:
            mulai.append(hasil)
        jam.t += 1
    assert mulai == [("tak_terjangkau", "mentah-0")]
    assert e.pulih() is not None
    assert e.pulih() is None


def test_lama_pulih_dihitung_dari_poll_gagal_pertama():
    jam = _Jam(1_000.0)
    e = _episode(jam)
    for _ in range(3):
        e.gagal("tak_terjangkau", "x")
        jam.t += 1
    jam.t = 1_010.0
    assert e.pulih() == 10.0


def test_tenggang_start_tidak_menulis_mulai():
    jam = _Jam(1_000.0)
    e = _episode(jam, tenggang_s=120.0)
    for _ in range(100):                         # 100 s after start: lines still loading
        assert e.gagal("tak_terjangkau", "x") is None
        jam.t += 1
    jam.t = 1_050.0
    assert e.pulih() is None, "never written, so no recovery row either"


def test_masih_tak_terbaca_sesudah_tenggang_ditulis_dihitung_dari_gagal_pertama():
    jam = _Jam(1_000.0)
    e = _episode(jam, tenggang_s=120.0)
    hasil = []
    for _ in range(125):
        hasil.append(e.gagal("bukan_line", "404"))
        jam.t += 1
    mulai = [(i, h) for i, h in enumerate(hasil) if h is not None]
    assert mulai == [(120, ("bukan_line", "404"))]
    jam.t = 1_200.0
    assert e.pulih() == 200.0
