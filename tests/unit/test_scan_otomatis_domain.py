"""One scan field (user 2026-10-06): the step comes from the truck's state, decided here.

Pure rules, no store: tickets and arrivals are the rows the store would hand over.
"""
from __future__ import annotations

from palmgrade.domain.gerbang import (
    GANDA,
    LANGKAH_DATANG,
    LANGKAH_ISI,
    LANGKAH_KELUAR,
    LANGKAH_KOSONG,
    Langkah,
    perlu_konfirmasi,
    putuskan_langkah,
)
from palmgrade.domain.timbangan_live import berat_layak

JAM = "2026-10-06T10:00:00+00:00"


def _tiket(id_="t1", masuk="2026-10-06T09:00:00+00:00", tara=None, keluar=None, pergi=None):
    return {"id": id_, "plate_number": "BE 1 AB", "entered_at": masuk, "tare_kg": tara,
            "exited_at": keluar, "left_at": pergi}


def _datang(jam="2026-10-06T09:50:00+00:00"):
    return {"id": "a1", "arrived_at": jam}


def test_truk_baru_tanpa_apa_pun_datang():
    assert putuskan_langkah([], [], JAM) == Langkah(LANGKAH_DATANG)


def test_sudah_datang_belum_ditimbang_timbang_isi():
    langkah = putuskan_langkah([], [_datang()], JAM)
    assert (langkah.nama, langkah.sebelumnya) == (LANGKAH_ISI, "2026-10-06T09:50:00+00:00")


def test_kedatangan_kemarin_lewat_jendela_dibaca_datang_baru():
    assert putuskan_langkah([], [_datang("2026-10-05T08:00:00+00:00")], JAM).nama == LANGKAH_DATANG


def test_tiket_tanpa_tara_timbang_kosong():
    langkah = putuskan_langkah([_tiket()], [], JAM)
    assert (langkah.nama, langkah.weighing["id"]) == (LANGKAH_KOSONG, "t1")
    assert langkah.sebelumnya == "2026-10-06T09:00:00+00:00"


def test_tiket_terbuka_menang_atas_kedatangan_baru():
    # Weighed in and not out: a waiting arrival of the same truck is a mistake, the ticket wins.
    assert putuskan_langkah([_tiket()], [_datang()], JAM).nama == LANGKAH_KOSONG


def test_dua_tiket_terbuka_ditolak_tidak_ditebak():
    langkah = putuskan_langkah([_tiket("t1"), _tiket("t2", masuk="2026-10-06T09:30:00+00:00")], [], JAM)
    assert langkah.nama == GANDA
    assert [w["id"] for w in langkah.pilihan] == ["t2", "t1"]


def test_tiket_terbuka_lewat_12_jam_tidak_dihitung():
    assert putuskan_langkah([_tiket(masuk="2026-10-05T20:00:00+00:00")], [], JAM).nama == LANGKAH_DATANG


def test_sudah_tara_belum_pergi_keluar():
    tiket = _tiket(tara=6000, keluar="2026-10-06T09:40:00+00:00")
    langkah = putuskan_langkah([tiket], [], JAM)
    assert (langkah.nama, langkah.weighing["id"], langkah.sebelumnya) == (
        LANGKAH_KELUAR, "t1", "2026-10-06T09:40:00+00:00")


def test_sudah_pergi_kunjungan_baru_datang():
    tiket = _tiket(tara=6000, keluar="2026-10-06T09:40:00+00:00", pergi="2026-10-06T09:45:00+00:00")
    langkah = putuskan_langkah([tiket], [], JAM)
    assert (langkah.nama, langkah.sebelumnya) == (LANGKAH_DATANG, "2026-10-06T09:45:00+00:00")


def test_selesai_tanpa_scan_4_kunjungan_baru_datang():
    tiket = _tiket(masuk="2026-10-05T07:00:00+00:00", tara=6000, keluar="2026-10-05T08:00:00+00:00")
    assert putuskan_langkah([tiket], [], JAM).nama == LANGKAH_DATANG


def test_konfirmasi_di_dalam_3_menit():
    langkah = Langkah(LANGKAH_ISI, sebelumnya="2026-10-06T09:58:30+00:00")
    assert perlu_konfirmasi(langkah, JAM) == 2


def test_konfirmasi_menit_nol_tetap_ditanya():
    langkah = Langkah(LANGKAH_ISI, sebelumnya="2026-10-06T09:59:59+00:00")
    assert perlu_konfirmasi(langkah, JAM) == 0


def test_tanpa_konfirmasi_sesudah_3_menit():
    assert perlu_konfirmasi(Langkah(LANGKAH_KOSONG, sebelumnya="2026-10-06T09:57:00+00:00"), JAM) is None


def test_keluar_tidak_pernah_ditanya():
    assert perlu_konfirmasi(Langkah(LANGKAH_KELUAR, sebelumnya="2026-10-06T09:59:50+00:00"), JAM) is None


def test_tanpa_langkah_sebelumnya_tidak_ditanya():
    assert perlu_konfirmasi(Langkah(LANGKAH_DATANG), JAM) is None


def test_jam_sebelumnya_di_masa_depan_tidak_ditanya():
    # A PC clock that moved back is not a double read.
    assert perlu_konfirmasi(Langkah(LANGKAH_ISI, sebelumnya="2026-10-06T10:05:00+00:00"), JAM) is None


def test_jam_sebelumnya_rusak_tidak_ditanya():
    assert perlu_konfirmasi(Langkah(LANGKAH_ISI, sebelumnya="jam sembilan"), JAM) is None


# ---- live weight fit to save --------------------------------------------------------


def _snap(keadaan, kg):
    return {"keadaan": keadaan, "kg": kg, "umur_detik": 0.2}


def test_berat_stabil_langsung_layak():
    assert berat_layak(_snap("stabil", 14820), None, 1000) == 14820


def test_berat_terbaca_layak_sesudah_tahan_2_detik():
    assert berat_layak(_snap("terbaca", 14820), 2.0, 1000) == 14820
    assert berat_layak(_snap("terbaca", 14820), 1.9, 1000) is None
    assert berat_layak(_snap("terbaca", 14820), None, 1000) is None


def test_berat_bergerak_putus_error_tidak_layak():
    for keadaan in ("bergerak", "putus", "error", "memeriksa", "tidak_dipakai"):
        assert berat_layak(_snap(keadaan, 14820), 10.0, 1000) is None, keadaan


def test_berat_layak_di_bawah_minimum():
    # An empty bridge reads near zero: never saved as a weight.
    assert berat_layak(_snap("stabil", 40), None, 1000) is None


def test_berat_tanpa_kg_tidak_layak():
    assert berat_layak(_snap("stabil", None), None, 1000) is None
