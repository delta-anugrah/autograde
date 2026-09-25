"""Aturan Danger Zone — murni, tanpa I/O kecuali satu test yang membaca skema.

Yang diputuskan di sini menentukan apakah data pabrik boleh dihapus, jadi tiap
hambatan diuji dua arah: muncul pada keadaan yang tepat, dan TIDAK muncul pada
line yang sehat (hambatan palsu membuat tombolnya tidak pernah bisa dipakai).
"""
from __future__ import annotations

import sqlite3

import pytest

from palmgrade.domain.bahaya import (
    GOLONGAN_TABEL_KONSOL,
    KODE_HAMBATAN,
    KODE_PERINGATAN,
    KONFIRMASI_HAPUS,
    MODE_SEMUA,
    MODE_TRANSAKSI,
    KeadaanKonsol,
    KeadaanLine,
    hambatan_hapus_data,
    hambatan_mode_semua,
    konfirmasi_sah,
    kunci_state_dihapus,
    peringatan_hapus_data,
    peringatan_hapus_rekaman,
    peringatan_restart,
    tabel_dihapus,
)
from palmgrade.repositories.console_repository import ConsoleStore


def _sehat(kode: str = "line-1", **ubah) -> KeadaanLine:
    return KeadaanLine(**{"line_code": kode, "terjangkau": True, "outbox_pending": 0, **ubah})


TIGA_SEHAT = [_sehat("line-1"), _sehat("line-2"), _sehat("line-3")]
KONSOL_BERSIH = KeadaanKonsol(erp_aktif=True, erp_pending=0, erp_gagal=0)


def _kode(daftar: list[dict]) -> list[str]:
    return [d["kode"] for d in daftar]


# ── konfirmasi ──────────────────────────────────────────────────────────────


def test_kata_konfirmasinya_hapus():
    assert KONFIRMASI_HAPUS == "HAPUS"


@pytest.mark.parametrize("teks", ["HAPUS", " HAPUS ", "HAPUS\n"])
def test_konfirmasi_sah(teks):
    assert konfirmasi_sah(teks) is True


@pytest.mark.parametrize("teks", ["hapus", "Hapus", "HAPUS!", "", "   ", None, "YA"])
def test_konfirmasi_tidak_sah(teks):
    """Huruf besar-kecil dibedakan: konfirmasi ketik ada supaya tidak ada yang
    menghapus data pabrik tanpa sengaja, dan "hapus" yang diketik asal jadi
    adalah persis yang mau ditangkap."""
    assert konfirmasi_sah(teks) is False


# ── hambatan hapus data ─────────────────────────────────────────────────────


def test_tiga_line_sehat_tanpa_hambatan():
    assert hambatan_hapus_data(TIGA_SEHAT, KONSOL_BERSIH) == []


def test_line_mati_menghambat_dan_disebut_namanya():
    lines = [_sehat("line-1"), KeadaanLine("line-2", terjangkau=False), _sehat("line-3")]
    hambatan = hambatan_hapus_data(lines, KONSOL_BERSIH)
    assert hambatan == [{"kode": "line_mati", "line": "line-2"}]


def test_truk_terpasang_menghambat():
    lines = [_sehat("line-1", truk_terpasang=True), _sehat("line-2"), _sehat("line-3")]
    assert hambatan_hapus_data(lines, KONSOL_BERSIH) == [
        {"kode": "truk_terpasang", "line": "line-1"}
    ]


def test_antrean_line_belum_kosong_menghambat_dengan_jumlahnya():
    lines = [_sehat("line-1"), _sehat("line-2", outbox_pending=7), _sehat("line-3")]
    assert hambatan_hapus_data(lines, KONSOL_BERSIH) == [
        {"kode": "antrean_line", "line": "line-2", "jumlah": 7}
    ]


def test_antrean_line_tak_terbaca_dianggap_belum_kosong():
    """Line yang menjawab tapi tidak melapor antreannya = tidak diketahui, bukan
    nol. Menganggapnya nol membuang janjang persis saat paling tidak jelas."""
    lines = [_sehat("line-1"), KeadaanLine("line-2", terjangkau=True, outbox_pending=None),
             _sehat("line-3")]
    assert _kode(hambatan_hapus_data(lines, KONSOL_BERSIH)) == ["antrean_line"]


def test_line_mati_tidak_ikut_dituduh_antrean():
    """Satu sebab per line: line mati sudah cukup alasannya."""
    lines = [KeadaanLine("line-1", terjangkau=False), _sehat("line-2"), _sehat("line-3")]
    assert _kode(hambatan_hapus_data(lines, KONSOL_BERSIH)) == ["line_mati"]


def test_antrean_erp_menghambat_kalau_erp_aktif():
    konsol = KeadaanKonsol(erp_aktif=True, erp_pending=3, erp_gagal=0)
    assert hambatan_hapus_data(TIGA_SEHAT, konsol) == [{"kode": "antrean_erp", "jumlah": 3}]


def test_antrean_erp_tidak_menghambat_kalau_erp_mati():
    """Tanpa ERP_URL antrean itu tidak akan pernah terkirim; menghambat berarti
    tombolnya tidak bisa dipakai selamanya. Cukup diperingatkan."""
    konsol = KeadaanKonsol(erp_aktif=False, erp_pending=3, erp_gagal=0)
    assert hambatan_hapus_data(TIGA_SEHAT, konsol) == []


def test_tanpa_line_sama_sekali_tetap_menghambat():
    """Konsol yang tidak mengenal line satu pun tidak bisa menyuruh siapa pun
    menghapus foto — mengosongkan index-nya saja meninggalkan foto yatim."""
    assert _kode(hambatan_hapus_data([], KONSOL_BERSIH)) == ["tanpa_line"]


# ── peringatan hapus data ───────────────────────────────────────────────────


def test_peringatan_foto_r2_selalu_ada():
    peringatan = peringatan_hapus_data(TIGA_SEHAT, KONSOL_BERSIH, MODE_TRANSAKSI)
    assert _kode(peringatan) == ["foto_belum_r2"]


def test_peringatan_kiriman_gagal_membawa_jumlah():
    konsol = KeadaanKonsol(erp_aktif=True, erp_pending=0, erp_gagal=4)
    peringatan = peringatan_hapus_data(TIGA_SEHAT, konsol, MODE_TRANSAKSI)
    assert {"kode": "kiriman_gagal", "jumlah": 4} in peringatan


def test_peringatan_erp_mati_menyebut_antrean_yang_ikut_hilang():
    konsol = KeadaanKonsol(erp_aktif=False, erp_pending=5, erp_gagal=1)
    peringatan = peringatan_hapus_data(TIGA_SEHAT, konsol, MODE_TRANSAKSI)
    assert {"kode": "erp_mati", "jumlah": 6} in peringatan


def test_erp_mati_tanpa_antrean_tidak_perlu_diperingatkan():
    konsol = KeadaanKonsol(erp_aktif=False, erp_pending=0, erp_gagal=0)
    assert "erp_mati" not in _kode(peringatan_hapus_data(TIGA_SEHAT, konsol, MODE_TRANSAKSI))


def test_mode_semua_memperingatkan_semua_keluar():
    assert "semua_keluar" in _kode(peringatan_hapus_data(TIGA_SEHAT, KONSOL_BERSIH, MODE_SEMUA))
    assert "semua_keluar" not in _kode(
        peringatan_hapus_data(TIGA_SEHAT, KONSOL_BERSIH, MODE_TRANSAKSI)
    )


# ── restart & rekaman ───────────────────────────────────────────────────────


def test_restart_line_sehat_tanpa_peringatan():
    assert peringatan_restart(TIGA_SEHAT) == []


def test_restart_memperingatkan_truk_rekaman_dan_line_mati():
    lines = [
        _sehat("line-1", truk_terpasang=True),
        _sehat("line-2", merekam=True),
        KeadaanLine("line-3", terjangkau=False),
    ]
    assert peringatan_restart(lines) == [
        {"kode": "truk_terpasang", "line": "line-1"},
        {"kode": "line_merekam", "line": "line-2"},
        {"kode": "line_mati", "line": "line-3"},
    ]


def test_hapus_rekaman_memperingatkan_line_yang_dilewati():
    lines = [_sehat("line-1"), _sehat("line-2", merekam=True), KeadaanLine("line-3", terjangkau=False)]
    assert peringatan_hapus_rekaman(lines) == [
        {"kode": "line_merekam", "line": "line-2"},
        {"kode": "line_mati", "line": "line-3"},
    ]


# ── apa yang dihapus di console.db ──────────────────────────────────────────


def test_mode_transaksi_tidak_menyentuh_truk_akun_dan_sesi():
    dihapus = set(tabel_dihapus(MODE_TRANSAKSI))
    assert {"inspections", "assignments", "auto_releases", "weighings"} <= dihapus
    assert not dihapus & {"trucks", "suppliers", "operators", "sesi", "sync_state"}


def test_mode_semua_menambah_master_akun_dan_sesi():
    dihapus = set(tabel_dihapus(MODE_SEMUA))
    assert set(tabel_dihapus(MODE_TRANSAKSI)) < dihapus
    assert {"trucks", "suppliers", "operators", "sesi"} <= dihapus
    # sync_state tidak pernah dikosongkan utuh — setelan hidup di sana.
    assert "sync_state" not in dihapus


def test_mode_asing_ditolak():
    with pytest.raises(ValueError):
        tabel_dihapus("semuanya")


@pytest.mark.parametrize("mode", [MODE_TRANSAKSI, MODE_SEMUA])
def test_setelan_tidak_pernah_dihapus(mode):
    for kunci in ("setelan_grading", "setelan_rekam", "setelan_apa_pun_kelak"):
        assert kunci_state_dihapus(kunci, mode) is False


def test_kursor_erp_cuma_dihapus_mode_semua():
    """Mode transaksi menyisakan truk/supplier/akun, jadi kursornya harus ikut
    tetap — kursor mundur tanpa datanya ikut hilang cuma menarik ulang semuanya."""
    for kunci in ("erp_cursor_truck", "erp_cursor_supplier", "erp_cursor_operator"):
        assert kunci_state_dihapus(kunci, MODE_TRANSAKSI) is False
        assert kunci_state_dihapus(kunci, MODE_SEMUA) is True


def test_penanda_transaksi_lain_ikut_dihapus():
    for mode in (MODE_TRANSAKSI, MODE_SEMUA):
        assert kunci_state_dihapus("erp_visit_resend_day", mode) is True


def test_semua_tabel_konsol_digolongkan(tmp_path):
    """Tabel baru di console.db WAJIB diputuskan masuk golongan mana.

    Tanpa test ini tabel baru diam-diam tidak pernah terhapus (data "reset" yang
    ternyata masih ada) — atau, kalau aturannya dibalik, ikut terhapus padahal
    isinya setelan. Merah di sini artinya: tambahkan tabelnya ke
    `GOLONGAN_TABEL_KONSOL` dengan sadar.
    """
    ConsoleStore(tmp_path / "console.db")
    db = sqlite3.connect(tmp_path / "console.db")
    tabel = {
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    db.close()
    assert tabel == set(GOLONGAN_TABEL_KONSOL)


# ── mode semua: jangan sampai tidak ada yang bisa masuk lagi ────────────────


def test_mode_semua_tanpa_akun_bawaan_dan_tanpa_erp_menghambat():
    """Mode semua menghapus SEMUA akun. Tanpa hash akun bawaan di `.env` dan
    tanpa AutoERP, tidak ada satu akun pun yang bisa kembali — konsol terkunci
    sampai teknisi datang dengan terminal."""
    konsol = KeadaanKonsol(erp_aktif=False, akun_support_bawaan=False)
    assert hambatan_mode_semua(konsol) == [{"kode": "tanpa_sumber_akun"}]


def test_mode_semua_dengan_akun_bawaan_boleh():
    assert hambatan_mode_semua(KeadaanKonsol(erp_aktif=False, akun_support_bawaan=True)) == []


def test_mode_semua_dengan_erp_boleh():
    """Akun AutoERP turun lagi lewat tarikan master data."""
    assert hambatan_mode_semua(KeadaanKonsol(erp_aktif=True, akun_support_bawaan=False)) == []


# ── daftar kode: jembatan ke terjemahan di layar ────────────────────────────


def _semua_keluaran() -> tuple[set[str], set[str]]:
    """Setiap kode yang bisa dikeluarkan fungsi-fungsi di atas, dari keadaan
    yang menyalakan semuanya sekaligus."""
    lines = [
        KeadaanLine("line-1", terjangkau=False),
        _sehat("line-2", truk_terpasang=True, merekam=True),
        _sehat("line-3", outbox_pending=None),
        _sehat("line-4", merekam=True, outbox_gagal=2),
    ]
    aktif = KeadaanKonsol(
        erp_aktif=True, erp_pending=2, erp_gagal=1, akun_support_bawaan=False,
        tiket_terbuka=1, tiket_lama_terbuka=1,
    )
    mati = KeadaanKonsol(
        erp_aktif=False, erp_pending=2, erp_gagal=1, akun_support_bawaan=False,
        tiket_terbuka=1, tiket_lama_terbuka=1,
    )
    hambatan = {
        *_kode(hambatan_hapus_data(lines, aktif)),
        *_kode(hambatan_hapus_data([], aktif)),
        *_kode(hambatan_mode_semua(mati)),
    }
    peringatan = {
        *_kode(peringatan_hapus_data(lines, aktif, MODE_SEMUA)),
        *_kode(peringatan_hapus_data(lines, mati, MODE_SEMUA)),
        *_kode(peringatan_restart(lines)),
        *_kode(peringatan_hapus_rekaman(lines)),
    }
    return hambatan, peringatan


def test_daftar_kode_hambatan_lengkap_dan_tidak_berlebih():
    """Layar menerjemahkan tiap kode (`hambatan_<kode>` di KAMUS). Kode yang
    lolos dari daftar ini tampil mentah ke support; `test_console_html_bahaya`
    memeriksa daftar ini lawan kamus kedua bahasa."""
    hambatan, _ = _semua_keluaran()
    assert hambatan == set(KODE_HAMBATAN)


def test_daftar_kode_peringatan_lengkap_dan_tidak_berlebih():
    _, peringatan = _semua_keluaran()
    assert peringatan == set(KODE_PERINGATAN)


# ── fix pass review 2026-09-25 ──────────────────────────────────────────────


def test_tiket_terbuka_hari_ini_menghambat():
    """I-3a: tiket yang sudah timbang masuk tapi belum keluar HARI INI = truk di
    tengah kunjungan. Bruto-nya yang dibayar; menghapusnya membuat neto truk
    itu tidak pernah bisa dihitung."""
    konsol = KeadaanKonsol(erp_aktif=True, tiket_terbuka=2)
    assert hambatan_hapus_data(TIGA_SEHAT, konsol) == [{"kode": "tiket_terbuka", "jumlah": 2}]


def test_tiket_terbuka_hari_lama_cuma_diperingatkan():
    """Tiket terbuka dari hari kerja yang sudah lewat hampir pasti sisa uji
    coba; menghambat karenanya membuat reset tidak pernah bisa dipakai."""
    konsol = KeadaanKonsol(erp_aktif=True, tiket_lama_terbuka=5)
    assert hambatan_hapus_data(TIGA_SEHAT, konsol) == []
    assert {"kode": "tiket_lama_terbuka", "jumlah": 5} in peringatan_hapus_data(
        TIGA_SEHAT, konsol, MODE_TRANSAKSI
    )


def test_antrean_line_gagal_diperingatkan():
    """M-5: janjang yang ditolak konsol sesudah percobaan maksimum ikut hilang."""
    lines = [_sehat("line-1"), _sehat("line-2", outbox_gagal=3), _sehat("line-3")]
    assert {"kode": "antrean_line_gagal", "line": "line-2", "jumlah": 3} in peringatan_hapus_data(
        lines, KONSOL_BERSIH, MODE_TRANSAKSI
    )


def test_mode_semua_butuh_akun_support_bukan_sekadar_akun_bawaan():
    """M-3: hash akun operator saja tidak cukup — sesudah mode semua tidak ada
    akun support, dan Danger Zone beserta seluruh lane developer terkunci."""
    konsol = KeadaanKonsol(erp_aktif=False, akun_support_bawaan=False)
    assert hambatan_mode_semua(konsol) == [{"kode": "tanpa_sumber_akun"}]


def test_setiap_kunci_sync_state_di_kode_sudah_digolongkan():
    """M-4: `kunci_state_dihapus` memutuskan per awalan, dan kunci tak dikenal
    ikut terhapus. Setelan baru yang disimpan tanpa awalan `setelan_` akan
    hilang diam-diam — test ini merah begitu ada pemanggil `set_state` baru
    yang belum diputuskan golongannya."""
    import re
    from pathlib import Path

    from palmgrade.domain.setelan_grading import KUNCI_SETELAN
    from palmgrade.domain.setelan_rekam import KUNCI_SETELAN_REKAM
    from palmgrade.workers.master_data_worker import (
        OPERATOR_CURSOR_KEY,
        SUPPLIER_CURSOR_KEY,
        TRUCK_CURSOR_KEY,
    )
    from palmgrade.workers.visit_resend_worker import RESEND_DAY_KEY

    src = Path(__file__).resolve().parents[2] / "src/palmgrade"
    pemanggil = {
        m.group(1)
        for f in src.rglob("*.py")
        for m in re.finditer(r"\.set_state\(\s*([A-Za-z_.]+)", f.read_text())
    }
    assert pemanggil == {
        "KUNCI_SETELAN", "KUNCI_SETELAN_REKAM", "RESEND_DAY_KEY", "resource.cursor_key",
    }, pemanggil
    for kunci in (KUNCI_SETELAN, KUNCI_SETELAN_REKAM):
        assert not kunci_state_dihapus(kunci, MODE_SEMUA), kunci
    for kunci in (SUPPLIER_CURSOR_KEY, TRUCK_CURSOR_KEY, OPERATOR_CURSOR_KEY):
        assert not kunci_state_dihapus(kunci, MODE_TRANSAKSI), kunci
        assert kunci_state_dihapus(kunci, MODE_SEMUA), kunci
    assert kunci_state_dihapus(RESEND_DAY_KEY, MODE_TRANSAKSI)

