"""Scan QR: satu plat masuk, satu truk keluar (keputusan operator 2026-09-15).

Isi QR-nya **cuma nomor plat**, bukan seluruh data truk dan bukan id truk ERP:

- data truk (supplier, sopir, kelas) berubah di ERP sesudah QR dicetak, jadi QR
  yang membawanya jadi bohong tanpa ada yang tahu
- id truk ERP **buntu** untuk truk pinjaman: belum terdaftar = belum punya id =
  tidak bisa di-scan, padahal itu justru kasus yang mau dipecahkan (S4)

Dua tahap scan, dua-duanya di gerbang timbangan: **timbang masuk** dan **timbang
keluar**. Tahap sortir tidak di-scan — yang tahu bak sudah kosong itu operator
line, bukan supir yang datang membawa HP.

Yang dijaga di sini: scan **tidak boleh** jadi jalur kedua yang membuat truk atau
menyentuh tonase. Dia cuma mencari, dan mengembalikan apa yang sudah ada.
"""

from __future__ import annotations

import pytest

from palmgrade.domain.operator_error import OperatorError
from palmgrade.domain.plate import truck_id_for
from palmgrade.domain.qr import baca_qr, isi_qr_untuk
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.scan_service import ScanService


@pytest.fixture
def store(tmp_path):
    return ConsoleStore(tmp_path / "console.db")


@pytest.fixture
def scan(store):
    return ScanService(store)


def _truk(store: ConsoleStore, plat: str, **over) -> str:
    tid = truck_id_for(plat)
    row = {"id": tid, "plate_number": plat, "status": "active"}
    row.update(over)
    store.upsert_truck(row)
    return tid


# ── isi QR ───────────────────────────────────────────────────────────────────


def test_qr_isinya_cuma_plat():
    """Kalau QR membawa supplier atau nama sopir, dia jadi salinan kedua data yang
    berubah di ERP — dan yang menempel di truk tidak pernah ikut berubah."""
    isi = isi_qr_untuk("BE 4412 OFL")

    assert isi == "BE4412OFL"
    for jangan in ("supplier", "driver", "sopir", "erp", "{", "}"):
        assert jangan not in isi.lower()


def test_qr_disimpan_ternormalisasi_supaya_cetakan_lama_tetap_terbaca():
    """QR dicetak sekali dan dipakai bertahun-tahun. Kalau isinya plat apa adanya,
    cetakan `be-4412-ofl` dan `BE 4412 OFL` jadi dua QR untuk satu truk."""
    assert isi_qr_untuk("be-4412-ofl") == isi_qr_untuk("BE 4412 OFL")


def test_qr_yang_dibaca_boleh_tulisan_apa_pun():
    """Scanner kadang membaca dari kertas fotokopi atau layar HP retak, dan QR lama
    mungkin dicetak sebelum aturan normalisasi ada."""
    for teks in ("BE4412OFL", "BE 4412 OFL", "be-4412-ofl", "  BE 4412 OFL  "):
        assert baca_qr(teks) == "BE4412OFL"


def test_qr_kosong_ditolak_bukan_dianggap_plat_kosong():
    """Scanner gagal baca mengirim string kosong. Itu tidak boleh jadi truk
    berplat kosong yang lalu dibuat di ERP."""
    for teks in ("", "   ", "\n"):
        with pytest.raises(OperatorError):
            baca_qr(teks)


def test_qr_yang_isinya_bukan_plat_ditolak():
    """QR apa pun bisa masuk ke scanner: struk parkir, tautan promo, id ERP. Yang
    tidak berbentuk plat harus ditolak, bukan jadi truk baru bernama aneh."""
    for teks in ("https://contoh.id/x", "TRK-0001-a-b-c-d-e-f-g-h", "!!!", "-"):
        with pytest.raises(OperatorError):
            baca_qr(teks)


# ── cari truk dari hasil scan ────────────────────────────────────────────────


def test_scan_truk_terdaftar_mengembalikan_truknya(store, scan):
    _truk(store, "BE 4412 OFL", erp_name="TRK-0001")

    hasil = scan.cari("BE4412OFL")

    assert hasil["ditemukan"] is True
    assert hasil["truck"]["plate_number"] == "BE 4412 OFL"
    assert hasil["truck"]["erp_name"] == "TRK-0001"


def test_scan_memakai_plat_ternormalisasi_bukan_teks_mentah(store, scan):
    """Truk terdaftar sebagai `BE 4412 OFL`, QR-nya berisi `BE4412OFL`. Kalau
    pencariannya membandingkan teks mentah, truk yang ada terbaca tidak ada."""
    _truk(store, "BE 4412 OFL")

    assert scan.cari("BE4412OFL")["ditemukan"] is True
    assert scan.cari("be-4412-ofl")["ditemukan"] is True


def test_scan_truk_belum_terdaftar_mengembalikan_tidak_ditemukan(store, scan):
    """Truk pinjaman. Jawabannya "belum ada", dan layar menawarkan input manual —
    scan TIDAK boleh membuat truknya sendiri."""
    hasil = scan.cari("BE9999XYZ")

    assert hasil["ditemukan"] is False
    assert hasil["plate_number"] == "BE9999XYZ"
    assert hasil.get("truck") is None


def test_scan_tidak_pernah_membuat_truk(store, scan):
    """Ini pagarnya: kalau scan ikut membuat truk, satu QR salah baca menambah truk
    hantu ke master data, dan itu naik ke AutoERP."""
    sebelum = len(store.trucks_semua())

    scan.cari("BE9999XYZ")

    assert len(store.trucks_semua()) == sebelum


def test_scan_tidak_pernah_menyentuh_timbangan(store, scan):
    """Scan cuma mencari. Yang mencatat berat tetap `catat_timbangan`, satu jalur,
    supaya tidak ada dua tempat yang bisa menulis angka yang dibayar."""
    _truk(store, "BE 4412 OFL")

    scan.cari("BE4412OFL")

    assert store.weighings("2026-09-15") == []


def test_truk_nonaktif_terbaca_tapi_ditandai(store, scan):
    """Truk yang dipensiunkan tetap harus terbaca — supir tidak tahu soal itu, dan
    layar harus bisa mengatakan kenapa truknya tidak bisa dipakai. Tapi tidak boleh
    diam-diam terbaca seperti truk normal."""
    _truk(store, "BE 4412 OFL", status="inactive")

    hasil = scan.cari("BE4412OFL")

    assert hasil["ditemukan"] is True
    assert hasil["truck"]["status"] == "inactive"


def test_hasil_scan_membawa_id_yang_sama_dengan_jalur_timbangan(store, scan):
    """`catat_timbangan` menurunkan `truck_id` dari plat. Kalau scan mengembalikan id
    lain, satu kunjungan bisa mendarat di dua truk."""
    tid = _truk(store, "BE 4412 OFL")

    assert scan.cari("BE4412OFL")["truck"]["id"] == tid == truck_id_for("BE 4412 OFL")
