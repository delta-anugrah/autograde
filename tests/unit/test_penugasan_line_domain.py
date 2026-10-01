"""Penugasan line otomatis (keputusan user 2026-10-01): satu truk di line sampai selesai.

Aturan murni, tanpa database dan tanpa line: setelannya, line mana yang bebas, dan
apakah line masih dipakai truk yang belum timbang kosong.
"""
from __future__ import annotations

import pytest

from palmgrade.domain.operator_error import (
    LINE_TIDAK_DIKENAL,
    PENUGASAN_TANPA_LINE,
    InvalidInput,
)
from palmgrade.domain.penugasan_line import (
    JENDELA_ANTREAN_BONGKAR,
    KUNCI_PENUGASAN,
    SetelanPenugasan,
    baca_setelan,
    bersihkan_setelan_penugasan,
    line_bebas,
    line_sibuk,
    menit_menunggu,
    setelan_bawaan,
    simpan_teks,
)
from palmgrade.domain.working_day import JENDELA_KUNJUNGAN_DETIK

LINES = ["line-1", "line-2", "line-3"]


def test_bawaannya_mati_dengan_semua_line_terpilih():
    """Rilis yang membawa fitur ini tidak boleh mengubah cara kerja pabrik di hari datangnya."""
    assert setelan_bawaan(LINES) == SetelanPenugasan(aktif=False, lines=tuple(LINES))
    assert baca_setelan(None, LINES) == setelan_bawaan(LINES)


def test_kunci_selamat_dari_danger_zone():
    assert KUNCI_PENUGASAN.startswith("setelan_")


def test_setelan_tersimpan_terbaca_dan_line_asing_dibuang():
    teks = '{"aktif": true, "lines": ["line-3", "line-9", "line-1"]}'
    assert baca_setelan(teks, LINES) == SetelanPenugasan(aktif=True, lines=("line-1", "line-3"))


def test_setelan_rusak_kembali_ke_bawaan():
    assert baca_setelan("bukan json", LINES) == setelan_bawaan(LINES)


@pytest.mark.parametrize("teks", ["1", "[]", "null", '"teks"', "true", '[{"aktif": true}]'])
def test_json_sah_yang_bukan_objek_kembali_ke_bawaan(teks):
    """Dibaca di dalam poll state() tiap 2 detik: tidak boleh pernah melempar."""
    assert baca_setelan(teks, LINES) == setelan_bawaan(LINES)


@pytest.mark.parametrize(
    "teks",
    [
        '{"aktif": true, "lines": 5}',
        '{"aktif": true, "lines": "line-1"}',
        '{"aktif": true, "lines": [["line-1"], {"a": 1}, 3]}',
        '{"aktif": true}',
    ],
)
def test_daftar_line_yang_bentuknya_salah_dibaca_kosong_dan_mati(teks):
    assert baca_setelan(teks, LINES) == SetelanPenugasan(aktif=False, lines=())


def test_nyala_tanpa_line_tersisa_dibaca_mati():
    assert baca_setelan('{"aktif": true, "lines": ["line-9"]}', LINES).aktif is False


def test_simpan_lalu_baca_sama():
    s = SetelanPenugasan(aktif=True, lines=("line-1", "line-2"))
    assert baca_setelan(simpan_teks(s), LINES) == s


def test_bersihkan_mengurutkan_seperti_konfigurasi():
    s = bersihkan_setelan_penugasan(True, ["line-3", "line-1", "line-1"], LINES)
    assert s == SetelanPenugasan(aktif=True, lines=("line-1", "line-3"))


def test_bersihkan_menolak_line_asing():
    with pytest.raises(InvalidInput) as galat:
        bersihkan_setelan_penugasan(True, ["line-9"], LINES)
    assert galat.value.code == LINE_TIDAK_DIKENAL


def test_bersihkan_menolak_nyala_tanpa_line():
    with pytest.raises(InvalidInput) as galat:
        bersihkan_setelan_penugasan(True, [], LINES)
    assert galat.value.code == PENUGASAN_TANPA_LINE


def test_mati_tanpa_line_boleh():
    assert bersihkan_setelan_penugasan(False, [], LINES) == SetelanPenugasan(aktif=False, lines=())


def test_line_bebas_cuma_yang_tidak_memegang_truk():
    pegangan = {"line-1": {"truck_id": "A"}, "line-2": {"truck_id": None}, "line-3": {}}
    assert line_bebas(("line-1", "line-2", "line-3"), pegangan) == ["line-2", "line-3"]


def test_line_sibuk_selama_truknya_belum_timbang_kosong():
    pegangan = {"line-1": {"truck_id": "A"}}
    assert line_sibuk(("line-1", "line-2"), pegangan, {"A"}) is True


def test_truk_yang_sudah_timbang_kosong_tidak_menahan_antrean():
    """Pelepasannya gagal (line tidak menjawab): line itu dilewati, bukan menahan semua."""
    pegangan = {"line-1": {"truck_id": "A"}}
    assert line_sibuk(("line-1", "line-2"), pegangan, set()) is False


def test_line_di_luar_pilihan_tidak_dihitung():
    pegangan = {"line-3": {"truck_id": "A"}}
    assert line_sibuk(("line-1", "line-2"), pegangan, {"A"}) is False


def test_menit_menunggu_dibulatkan_ke_bawah_dan_tidak_negatif():
    assert menit_menunggu(1000.0, 1000.0 + 119) == 1
    assert menit_menunggu(1000.0, 900.0) == 0


def test_jendela_antrean_bongkar_dua_belas_jam_dan_satu_angka_dengan_kunjungan():
    """Satu angka untuk "berapa lama sebuah kunjungan": antrean bongkar memakai angka kunjungan."""
    assert JENDELA_ANTREAN_BONGKAR.total_seconds() == 12 * 3600
    assert JENDELA_ANTREAN_BONGKAR.total_seconds() == JENDELA_KUNJUNGAN_DETIK
