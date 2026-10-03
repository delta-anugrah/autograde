"""A weighed-out ticket that never got its Keluar (user 2026-10-03): 24 h, then done.

Decided in the domain, never written: no fake `left_at`. A ticket with a tare and no leave
time counts as finished ("tanpa scan 4") once its weigh-out is more than 24 h old, or as
soon as the same truck is seen again after that weigh-out (a new arrival or a new
weigh-in). Its Total then runs to the weigh-out. A ticket WITHOUT a tare keeps the 12 h
visit window: yesterday morning's forgotten ticket must never take today's tare.
"""
from __future__ import annotations

from datetime import timedelta

from palmgrade.domain.gerbang import (
    JENDELA_KELUAR,
    JENDELA_TANPA_KELUAR,
    SUDAH_KELUAR,
    TAHAP_SELESAI,
    TAHAP_TIMBANG_KOSONG,
    TERCATAT,
    TIDAK_ADA_TIKET,
    baca_waktu,
    durasi_kunjungan,
    putuskan_keluar,
    selesai_tanpa_scan_4,
    tahap_tiket,
)
from palmgrade.domain.working_day import JENDELA_KUNJUNGAN_DETIK, JENDELA_TANPA_KELUAR_DETIK

MASUK = "2026-10-01T01:00:00Z"
KOSONG = "2026-10-01T02:00:00Z"


def _tiket(id_="w1", *, masuk=MASUK, keluar=KOSONG, tara=6000.0, pergi=None, datang=None) -> dict:
    return {"id": id_, "entered_at": masuk, "exited_at": keluar, "tare_kg": tara,
            "left_at": pergi, "arrived_at": datang, "plate_number": "BE 1 AA"}


def _jam(teks: str, **selisih):
    return baca_waktu(teks) + timedelta(**selisih)


# ── the two windows ──────────────────────────────────────────────────────────


def test_dua_jendela_bernama_dan_berbeda():
    assert JENDELA_TANPA_KELUAR_DETIK == 24 * 60 * 60
    assert JENDELA_KUNJUNGAN_DETIK == 12 * 60 * 60
    assert JENDELA_TANPA_KELUAR == timedelta(seconds=JENDELA_TANPA_KELUAR_DETIK)
    # Untared tickets keep the visit window at scan 4, too.
    assert JENDELA_KELUAR == timedelta(seconds=JENDELA_KUNJUNGAN_DETIK)


# ── selesai_tanpa_scan_4 ─────────────────────────────────────────────────────


def test_23_jam_59_masih_menunggu_keluar():
    assert selesai_tanpa_scan_4(_tiket(), _jam(KOSONG, hours=23, minutes=59)) is False


def test_24_jam_01_dianggap_selesai():
    assert selesai_tanpa_scan_4(_tiket(), _jam(KOSONG, hours=24, minutes=1)) is True


def test_jam_timbang_kosong_kosong_memakai_jam_timbang_isi():
    """Like `putuskan_keluar`: the scale program may send a tare without `exited_at`."""
    tiket = _tiket(keluar=None)
    assert selesai_tanpa_scan_4(tiket, _jam(MASUK, hours=23, minutes=59)) is False
    assert selesai_tanpa_scan_4(tiket, _jam(MASUK, hours=24, minutes=1)) is True


def test_tanpa_tara_tidak_pernah_tanpa_scan_4():
    assert selesai_tanpa_scan_4(_tiket(tara=None, keluar=None), _jam(MASUK, days=3)) is False


def test_sudah_keluar_bukan_tanpa_scan_4():
    tiket = _tiket(pergi="2026-10-01T02:10:00Z")
    assert selesai_tanpa_scan_4(tiket, _jam(KOSONG, days=3)) is False


def test_jam_tak_terbaca_tidak_dianggap_lewat():
    """No readable weigh-out time: unknown age, so the Keluar button stays."""
    tiket = _tiket(masuk="bukan jam", keluar=None)
    assert selesai_tanpa_scan_4(tiket, _jam(KOSONG, days=3)) is False


def test_truk_datang_lagi_menutup_kunjungan_lama():
    sekarang = _jam(KOSONG, hours=3)
    assert selesai_tanpa_scan_4(_tiket(), sekarang, ["2026-10-01T04:00:00Z"]) is True


def test_truk_timbang_isi_lagi_menutup_kunjungan_lama():
    """The newer ticket's weigh-in, offset spelling different from the old one's."""
    sekarang = _jam(KOSONG, hours=3)
    assert selesai_tanpa_scan_4(_tiket(), sekarang, ["2026-10-01T11:30:00+07:00"]) is True


def test_jejak_sebelum_timbang_kosong_tidak_menutup():
    """The ticket's own arrival and its own weigh-in are before its weigh-out."""
    sekarang = _jam(KOSONG, hours=3)
    jejak = ["2026-10-01T00:30:00Z", MASUK, "bukan jam", None]
    assert selesai_tanpa_scan_4(_tiket(), sekarang, jejak) is False


# ── stage and minutes ────────────────────────────────────────────────────────


def test_tahap_selesai_kalau_ditandai_tanpa_scan_4():
    assert tahap_tiket(_tiket()) == TAHAP_TIMBANG_KOSONG
    assert tahap_tiket({**_tiket(), "tanpa_scan_4": True}) == TAHAP_SELESAI


def test_total_tanpa_scan_4_sampai_timbang_kosong():
    tiket = {**_tiket(datang="2026-10-01T00:30:00Z"), "tanpa_scan_4": True}
    assert durasi_kunjungan(tiket) == {"antre_menit": 30, "total_menit": 90, "tanpa_scan_1": False}


def test_total_tanpa_scan_1_dan_tanpa_scan_4_dari_timbang_isi_ke_timbang_kosong():
    tiket = {**_tiket(), "tanpa_scan_4": True}
    assert durasi_kunjungan(tiket) == {"antre_menit": None, "total_menit": 60, "tanpa_scan_1": True}


def test_total_tanpa_scan_4_tanpa_jam_timbang_kosong_sampai_timbang_isi():
    tiket = {**_tiket(keluar=None, datang="2026-10-01T00:30:00Z"), "tanpa_scan_4": True}
    assert durasi_kunjungan(tiket)["total_menit"] == 30


def test_total_belum_tanpa_scan_4_tetap_kosong():
    assert durasi_kunjungan(_tiket())["total_menit"] is None


# ── scan 4 and the row button ────────────────────────────────────────────────


def test_keluar_dalam_24_jam_masih_menutup():
    at = _jam(KOSONG, hours=23).isoformat()
    k = putuskan_keluar([_tiket()], at)
    assert (k.hasil, k.weighing["id"]) == (TERCATAT, "w1")


def test_scan_keluar_sesudah_24_jam_tidak_ada_yang_ditutup():
    at = _jam(KOSONG, hours=24, minutes=1).isoformat()
    assert putuskan_keluar([_tiket()], at).hasil == TIDAK_ADA_TIKET


def test_tombol_baris_sesudah_24_jam_tidak_ada_yang_ditutup():
    at = _jam(KOSONG, hours=24, minutes=1).isoformat()
    assert putuskan_keluar([_tiket()], at, jendela=None).hasil == SUDAH_KELUAR


def test_tiket_tanpa_tara_tetap_jendela_12_jam_di_scan_keluar():
    tiket = [_tiket(tara=None, keluar=None)]
    assert putuskan_keluar(tiket, _jam(MASUK, hours=11).isoformat()).hasil == "belum_timbang_kosong"
    assert putuskan_keluar(tiket, _jam(MASUK, hours=13).isoformat()).hasil == TIDAK_ADA_TIKET


def test_kunjungan_baru_tidak_pernah_menutup_tiket_lama():
    """Old visit weighed out at 02:00, never left; the truck came back at 05:00 and its new
    ticket is weighed out at 06:00. Scan 4 closes the new one; a second scan 4 finds the
    old one finished, not open."""
    lama = _tiket("lama")
    baru = _tiket("baru", masuk="2026-10-01T05:30:00Z", keluar="2026-10-01T06:00:00Z")
    jejak = ["2026-10-01T05:00:00Z", "2026-10-01T05:30:00Z"]
    k = putuskan_keluar([baru, lama], "2026-10-01T06:10:00Z", kembali=jejak)
    assert (k.hasil, k.weighing["id"]) == (TERCATAT, "baru")

    baru["left_at"] = "2026-10-01T06:10:00Z"
    k = putuskan_keluar([baru, lama], "2026-10-01T06:20:00Z", kembali=jejak)
    assert (k.hasil, k.weighing["id"]) == (SUDAH_KELUAR, "baru")


def test_datang_lagi_tanpa_timbang_isi_tiket_lama_tidak_ditutup():
    k = putuskan_keluar([_tiket()], "2026-10-01T05:10:00Z", kembali=["2026-10-01T05:00:00Z"])
    assert k.hasil == SUDAH_KELUAR


def test_tombol_baris_tiket_yang_digantikan_tidak_ditutup():
    k = putuskan_keluar([_tiket()], "2026-10-01T05:10:00Z", jendela=None, kembali=["2026-10-01T05:00:00Z"])
    assert k.hasil == SUDAH_KELUAR
