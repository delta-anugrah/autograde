"""Filter tab Riwayat: tanggal, rentang, dan isian lain dibersihkan di satu tempat.

Tab Riwayat (2026-09-26) membaca grading hari-hari sebelumnya. Aturannya murni,
tanpa I/O, supaya layar dan CSV memakai filter yang persis sama:

- tanpa tanggal = 7 hari terakhir sampai hari ini;
- paling panjang 31 hari: sebulan penuh muat, dan satu permintaan tidak bisa
  memaksa konsol memindai data bertahun-tahun;
- tanggal yang salah ketik ditolak dengan kode yang diterjemahkan layar, bukan
  diam-diam diganti tanggal lain.
"""

from __future__ import annotations

import pytest

from palmgrade.domain.operator_error import (
    RIWAYAT_RENTANG_PANJANG,
    RIWAYAT_RENTANG_TERBALIK,
    RIWAYAT_TANGGAL_TIDAK_SAH,
    OperatorError,
)
from palmgrade.domain.riwayat import (
    MAKS_HARI,
    FilterRiwayat,
    aman_untuk_csv,
    buat_filter,
    rasio_ripe,
)

HARI_INI = "2026-09-26"


def test_tanpa_tanggal_berarti_tujuh_hari_terakhir_sampai_hari_ini():
    f = buat_filter(hari_ini=HARI_INI)

    assert f == FilterRiwayat(dari="2026-09-20", sampai="2026-09-26")


def test_cuma_sampai_berarti_tujuh_hari_yang_berakhir_di_situ():
    assert buat_filter(sampai="2026-09-10", hari_ini=HARI_INI).dari == "2026-09-04"


def test_cuma_dari_berhenti_di_hari_ini_atau_di_batas_rentang():
    assert buat_filter(dari="2026-09-24", hari_ini=HARI_INI).sampai == "2026-09-26"
    # Tiga bulan lalu tanpa `sampai`: berhenti di batas 31 hari, bukan ditolak.
    jauh = buat_filter(dari="2026-06-01", hari_ini=HARI_INI)
    assert (jauh.dari, jauh.sampai) == ("2026-06-01", "2026-07-01")


def test_satu_hari_boleh():
    f = buat_filter(dari="2026-09-25", sampai="2026-09-25", hari_ini=HARI_INI)

    assert (f.dari, f.sampai) == ("2026-09-25", "2026-09-25")


def test_tiga_puluh_satu_hari_boleh_tiga_puluh_dua_ditolak():
    assert MAKS_HARI == 31
    buat_filter(dari="2026-08-01", sampai="2026-08-31", hari_ini=HARI_INI)

    with pytest.raises(OperatorError) as err:
        buat_filter(dari="2026-08-01", sampai="2026-09-01", hari_ini=HARI_INI)

    assert err.value.code == RIWAYAT_RENTANG_PANJANG
    assert err.value.params == {"maks": 31}


def test_rentang_terbalik_ditolak():
    with pytest.raises(OperatorError) as err:
        buat_filter(dari="2026-09-20", sampai="2026-09-10", hari_ini=HARI_INI)

    assert err.value.code == RIWAYAT_RENTANG_TERBALIK


@pytest.mark.parametrize("tanggal", ["26-09-2026", "2026-02-30", "kemarin", "2026-9-1"])
def test_tanggal_yang_bukan_tanggal_ditolak_dengan_kode(tanggal):
    with pytest.raises(OperatorError) as err:
        buat_filter(dari=tanggal, hari_ini=HARI_INI)

    assert err.value.code == RIWAYAT_TANGGAL_TIDAK_SAH
    assert err.value.params == {"tanggal": tanggal}


def test_kesalahan_tanggal_tetap_valueerror():
    """Rute konsol menjawab ValueError dengan 400; kode baru tidak boleh jadi 500."""
    with pytest.raises(ValueError):
        buat_filter(sampai="bukan", hari_ini=HARI_INI)


def test_isian_kosong_berarti_tanpa_saringan():
    f = buat_filter(line_code="  ", plat=" - ", hasil="", hari_ini=HARI_INI)

    assert (f.line_code, f.plat, f.hasil) == (None, None, None)


def test_plat_dibersihkan_seperti_di_timbangan():
    """Aturan yang sama dengan `normalisasi_plat`: operator mengetik "be 1234",
    truk tersimpan "BE 1234 AB", dan keduanya harus bertemu."""
    f = buat_filter(line_code=" line-2 ", plat=" be 1234-a ", hasil="JK", hari_ini=HARI_INI)

    assert (f.line_code, f.plat, f.hasil) == ("line-2", "BE1234A", "jk")


def test_hasil_yang_tidak_dikenal_ditolak():
    with pytest.raises(ValueError):
        buat_filter(hasil="busuk", hari_ini=HARI_INI)


@pytest.mark.parametrize(
    ("nilai", "harap"),
    [
        ("=HYPERLINK(\"http://x\")", "'=HYPERLINK(\"http://x\")"),
        ("+62812", "'+62812"),
        ("-5", "'-5"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("PT Sawit Jaya", "PT Sawit Jaya"),
        (None, ""),
        (1234, 1234),
        (12.5, 12.5),
    ],
)
def test_sel_csv_tidak_bisa_jadi_rumus_excel(nilai, harap):
    """Nama supplier datang dari AutoERP dan ketikan operator. Sel yang diawali
    `=`/`+`/`-`/`@` dijalankan Excel sebagai rumus saat berkasnya dibuka."""
    assert aman_untuk_csv(nilai) == harap


@pytest.mark.parametrize(
    ("acc", "total", "harap"),
    [(0, 0, None), (1, 8, 13), (1, 3, 33), (2, 3, 67), (5, 5, 100)],
)
def test_rasio_ripe_dibulatkan_seperti_layar(acc, total, harap):
    """`Math.round` di layar membulatkan 12,5 ke 13. `round()` Python ke 12
    (pembulatan bankir), jadi CSV dan layar akan berbeda satu persen."""
    assert rasio_ripe(acc, total) == harap
