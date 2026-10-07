"""Failures the operator reads: a stable code the console screen translates.

The screen is bilingual and a server sentence is not, so the sentence is built
on the screen from `code` + `params`. The server text stays as the exception
message — for logs, and for machine callers (the scale program) that read it.
"""
from __future__ import annotations

# Codes are part of the console ↔ console.html contract: renaming one leaves the
# screen showing the raw server text again. `test_console_html.py` checks both
# languages translate every code listed in CODES.
PLAT_KOSONG = "plat_kosong"
# Its own code, NOT shared with PLAT_KOSONG: the screen translates per code, and a
# QR holding a URL answered with "cannot be empty" would be the wrong message in
# front of the gate operator. Found in the browser, not in a test.
BUKAN_PLAT = "bukan_plat"
BUKAN_ANGKA = "bukan_angka"
NEGATIF = "negatif"
DI_BAWAH_MINIMUM = "di_bawah_minimum"
TARA_LEBIH_BESAR = "tara_lebih_besar"
LINE_TIDAK_DIKENAL = "line_tidak_dikenal"
LINE_TIDAK_MENJAWAB = "line_tidak_menjawab"
LINE_MENOLAK = "line_menolak"
# Login (Fase 4). `SANDI_SALAH` deliberately says nothing about which of the two was
# wrong, and is the same answer for an operator switched off.
SANDI_PENDEK = "sandi_pendek"
SANDI_SALAH = "sandi_salah"
TERKUNCI = "terkunci"
BELUM_MASUK = "belum_masuk"
# Signed in, but not a `support` account.
BUKAN_SUPPORT = "bukan_support"
# PLC test screen (support only) — the only console lane that moves hardware.
# ⚠️ `konfirmasi_kurang` dipensiunkan 2026-09-24 (ketikan UJI dicabut): tidak ada
# lagi yang melemparkannya. Kodenya sengaja TIDAK dihapus — konsol yang belum
# dimuat ulang masih bisa menerimanya dari server versi lama, dan kode tanpa
# terjemahan tampil mentah di layar operator.
KONFIRMASI_KURANG = "konfirmasi_kurang"
PLC_SIBUK = "plc_sibuk"
COIL_TIDAK_DIKENAL = "coil_tidak_dikenal"
# Danger Zone (support) sedang menghapus data; yang membacanya operator gerbang
# yang menekan Pasang truk di detik itu, jadi kodenya ikut daftar ini.
HAPUS_BERJALAN = "hapus_berjalan"
# Tab Akun (support): mengurus akun lokal dari layar (2026-09-26). Isian yang
# salah 400, akun yang tidak ada 404, sisanya 409 (keadaannya yang menolak).
AKUN_EMAIL_TIDAK_SAH = "akun_email_tidak_sah"
AKUN_NAMA_KOSONG = "akun_nama_kosong"
AKUN_SANDI_BEDA = "akun_sandi_beda"
AKUN_SUDAH_ADA = "akun_sudah_ada"
AKUN_MILIK_ERP = "akun_milik_erp"
AKUN_TIDAK_ADA = "akun_tidak_ada"
AKUN_DIRI_SENDIRI = "akun_diri_sendiri"
# Tab Riwayat (2026-09-26): filter tanggal yang ditolak, semuanya 400.
RIWAYAT_TANGGAL_TIDAK_SAH = "riwayat_tanggal_tidak_sah"
RIWAYAT_RENTANG_TERBALIK = "riwayat_rentang_terbalik"
RIWAYAT_RENTANG_PANJANG = "riwayat_rentang_panjang"
# Impor grading dari CSV Per janjang (2026-09-27, support saja). Berkasnya yang
# ditolak 400 (413 kalau terlalu besar); keadaannya yang menolak 409; batch tak ada 404.
IMPOR_KOSONG = "impor_kosong"
IMPOR_BUKAN_UTF8 = "impor_bukan_utf8"
IMPOR_BUKAN_JANJANG = "impor_bukan_janjang"
IMPOR_RUSAK = "impor_rusak"
IMPOR_TERLALU_BESAR = "impor_terlalu_besar"
IMPOR_SIDIK_BEDA = "impor_sidik_beda"
IMPOR_ADA_SALAH = "impor_ada_salah"
IMPOR_TIDAK_ADA_BARU = "impor_tidak_ada_baru"
IMPOR_BERJALAN = "impor_berjalan"
IMPOR_TIDAK_ADA = "impor_tidak_ada"
IMPOR_SUDAH_DIBATALKAN = "impor_sudah_dibatalkan"
IMPOR_HAPUS_BERJALAN = "impor_hapus_berjalan"
# A body of the wrong shape on an operator route (a list, or a number where text belongs),
# refused by the Pydantic model before the domain sees it (2026-09-30, standard B1).
INPUT_TIDAK_SAH = "input_tidak_sah"
# Penugasan line otomatis (2026-10-01). Setelan tanpa line ditolak 400; antrean bongkar yang
# sudah berubah sejak layar menggambarnya ditolak 409.
PENUGASAN_TANPA_LINE = "penugasan_tanpa_line"
BUKAN_ANTREAN = "bukan_antrean"
LINE_SEMUA_TERPAKAI = "line_semua_terpakai"
# Batch 4.6, the Update now button (operator and support). `pembaruan_ada_truk` now only
# means an assign still waiting for its line (Update now releases the other trucks itself);
# it carries param `line` ("L1, L3").
PEMBARUAN_ADA_TRUK = "pembaruan_ada_truk"
PEMBARUAN_TIDAK_ADA = "pembaruan_tidak_ada"
PEMBARUAN_BERJALAN = "pembaruan_berjalan"
PEMBARUAN_BELUM_TERPASANG = "pembaruan_belum_terpasang"
# Update now releases the trucks itself; a line that does not answer stops it. Carries param
# `line` (the line code): the screen tells the operator to use Lepas paksa on it.
PEMBARUAN_LEPAS_GAGAL = "pembaruan_lepas_gagal"
# Reconnect camera button (2026-10-04, every account): the line's image source is a video
# file or a photo, so there is no camera to reconnect. Carries param `line` (the card name).
KAMERA_TANPA_SAMBUNG_ULANG = "kamera_tanpa_sambung_ulang"
# Line to console only (camera settings, spec §3.2), never worded as an operator error: the console turns them
# into a `sebab_kode` (`domain/setelan_kamera.py`), so they stay out of `CODES`.
KAMERA_TANPA_SETELAN = "kamera_tanpa_setelan"
KAMERA_TIDAK_MENJAWAB = "kamera_tidak_menjawab"
# Printable grading slip (batch 5.9): refused while support has it switched off (403), and
# for a truck with no bunch on that working day (404).
SLIP_MATI = "slip_mati"
SLIP_TIDAK_ADA = "slip_tidak_ada"
# Shift cutoff (batch 5.11): HH:MM between 00:00 and 23:59.
CUTOFF_TIDAK_SAH = "cutoff_tidak_sah"

CODES = (
    PLAT_KOSONG,
    BUKAN_PLAT,
    BUKAN_ANGKA,
    NEGATIF,
    DI_BAWAH_MINIMUM,
    TARA_LEBIH_BESAR,
    LINE_TIDAK_DIKENAL,
    LINE_TIDAK_MENJAWAB,
    LINE_MENOLAK,
    SANDI_PENDEK,
    SANDI_SALAH,
    TERKUNCI,
    BELUM_MASUK,
    BUKAN_SUPPORT,
    KONFIRMASI_KURANG,
    PLC_SIBUK,
    COIL_TIDAK_DIKENAL,
    HAPUS_BERJALAN,
    AKUN_EMAIL_TIDAK_SAH,
    AKUN_NAMA_KOSONG,
    AKUN_SANDI_BEDA,
    AKUN_SUDAH_ADA,
    AKUN_MILIK_ERP,
    AKUN_TIDAK_ADA,
    AKUN_DIRI_SENDIRI,
    RIWAYAT_TANGGAL_TIDAK_SAH,
    RIWAYAT_RENTANG_TERBALIK,
    RIWAYAT_RENTANG_PANJANG,
    IMPOR_KOSONG,
    IMPOR_BUKAN_UTF8,
    IMPOR_BUKAN_JANJANG,
    IMPOR_RUSAK,
    IMPOR_TERLALU_BESAR,
    IMPOR_SIDIK_BEDA,
    IMPOR_ADA_SALAH,
    IMPOR_TIDAK_ADA_BARU,
    IMPOR_BERJALAN,
    IMPOR_TIDAK_ADA,
    IMPOR_SUDAH_DIBATALKAN,
    IMPOR_HAPUS_BERJALAN,
    INPUT_TIDAK_SAH,
    PENUGASAN_TANPA_LINE,
    BUKAN_ANTREAN,
    LINE_SEMUA_TERPAKAI,
    PEMBARUAN_ADA_TRUK,
    PEMBARUAN_TIDAK_ADA,
    PEMBARUAN_BERJALAN,
    PEMBARUAN_BELUM_TERPASANG,
    PEMBARUAN_LEPAS_GAGAL,
    KAMERA_TANPA_SAMBUNG_ULANG,
    SLIP_MATI,
    SLIP_TIDAK_ADA,
    CUTOFF_TIDAK_SAH,
)


class OperatorError(Exception):
    """A failure with a code the operator screen can put into words."""

    def __init__(self, code: str, message: str, **params: str | float) -> None:
        super().__init__(message)
        self.code = code
        self.params = params

    def as_detail(self) -> dict:
        """HTTP error body for the operator routes."""
        return {"code": self.code, "params": self.params, "message": str(self)}


class InvalidInput(OperatorError, ValueError):
    """Bad input — still a ValueError, so existing 400/404 handling holds."""
