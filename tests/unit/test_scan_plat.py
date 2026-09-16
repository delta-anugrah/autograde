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


def test_plat_menyimpang_diterima_karena_autoerp_boleh_mencetaknya():
    """Gerbang tidak boleh lebih ketat dari yang mencetak kartunya.

    AutoERP cuma **memperingatkan** backoffice waktu platnya tidak berbentuk plat
    sipil biasa; kalau dia bilang benar, trucknya jadi dan kartunya tercetak. Kalau
    scanner di sini menolaknya, kartu itu tertempel di kaca truk dan baru ketahuan
    tidak terbaca waktu sopirnya sampai di gerbang.
    """
    for teks in ("B 1234", "BE 12345 OFL", "B 1 A", "1234 AB", "B 1234 XYZW"):
        assert baca_qr(teks) == baca_qr(teks.lower())


def test_id_erp_tetap_ditolak_walau_bentuknya_mirip_plat():
    """`TRK0042` itu huruf-lalu-angka, persis bentuk plat. Yang membuatnya tertolak
    cuma batas **dua** huruf wilayah - kalau batasnya dinaikkan jadi tiga demi
    meloloskan satu plat aneh, id ERP ikut lolos, dan satu salah scan menambah truk
    hantu yang lalu naik ke AutoERP.
    """
    # `1234` ikut di sini, bukan di test plat menyimpang: angka telanjang itu bisa
    # nomor tiket, berat, atau harga - bukan plat.
    for teks in ("TRK-0042", "TRK0042", "INV-2026-0001", "PROMO2024DISKON", "1234"):
        with pytest.raises(OperatorError):
            baca_qr(teks)


# ── cari truk dari hasil scan ────────────────────────────────────────────────


def test_scan_truk_terdaftar_mengembalikan_truknya(store, scan):
    _truk(store, "BE 4412 OFL", erp_name="TRK-0001")

    hasil = scan.search("BE4412OFL")

    assert hasil["ditemukan"] is True
    assert hasil["truck"]["plate_number"] == "BE 4412 OFL"
    assert hasil["truck"]["erp_name"] == "TRK-0001"


def test_scan_memakai_plat_ternormalisasi_bukan_teks_mentah(store, scan):
    """Truk terdaftar sebagai `BE 4412 OFL`, QR-nya berisi `BE4412OFL`. Kalau
    pencariannya membandingkan teks mentah, truk yang ada terbaca tidak ada."""
    _truk(store, "BE 4412 OFL")

    assert scan.search("BE4412OFL")["ditemukan"] is True
    assert scan.search("be-4412-ofl")["ditemukan"] is True


def test_scan_truk_belum_terdaftar_mengembalikan_tidak_ditemukan(store, scan):
    """Truk pinjaman. Jawabannya "belum ada", dan layar menawarkan input manual —
    scan TIDAK boleh membuat truknya sendiri."""
    hasil = scan.search("BE9999XYZ")

    assert hasil["ditemukan"] is False
    assert hasil["plate_number"] == "BE9999XYZ"
    assert hasil.get("truck") is None


def test_scan_tidak_pernah_membuat_truk(store, scan):
    """Ini pagarnya: kalau scan ikut membuat truk, satu QR salah baca menambah truk
    hantu ke master data, dan itu naik ke AutoERP."""
    sebelum = len(store.trucks_semua())

    scan.search("BE9999XYZ")

    assert len(store.trucks_semua()) == sebelum


def test_scan_tidak_pernah_menyentuh_timbangan(store, scan):
    """Scan cuma mencari. Yang mencatat berat tetap `catat_timbangan`, satu jalur,
    supaya tidak ada dua tempat yang bisa menulis angka yang dibayar."""
    _truk(store, "BE 4412 OFL")

    scan.search("BE4412OFL")

    assert store.weighings("2026-09-15") == []


def test_truk_nonaktif_terbaca_tapi_ditandai(store, scan):
    """Truk yang dipensiunkan tetap harus terbaca — supir tidak tahu soal itu, dan
    layar harus bisa mengatakan kenapa truknya tidak bisa dipakai. Tapi tidak boleh
    diam-diam terbaca seperti truk normal."""
    _truk(store, "BE 4412 OFL", status="inactive")

    hasil = scan.search("BE4412OFL")

    assert hasil["ditemukan"] is True
    assert hasil["truck"]["status"] == "inactive"


def test_hasil_scan_membawa_id_yang_sama_dengan_jalur_timbangan(store, scan):
    """`catat_timbangan` menurunkan `truck_id` dari plat. Kalau scan mengembalikan id
    lain, satu kunjungan bisa mendarat di dua truk."""
    tid = _truk(store, "BE 4412 OFL")

    assert scan.search("BE4412OFL")["truck"]["id"] == tid == truck_id_for("BE 4412 OFL")


# ── dua bug yang ketemu di browser, bukan di test ────────────────────────────


def test_bukan_plat_punya_kode_sendiri_bukan_dipakai_bersama_plat_kosong():
    """Ketemu di browser: QR berisi URL menampilkan "Nomor polisi tidak boleh kosong",
    padahal isinya justru tidak kosong. Layar menerjemahkan per KODE, jadi dua sebab
    berbeda yang memakai satu kode akan selalu memberi pesan yang salah untuk salah
    satunya — dan operator gerbang yang membacanya.
    """
    from palmgrade.domain.operator_error import BUKAN_PLAT, PLAT_KOSONG

    assert BUKAN_PLAT != PLAT_KOSONG

    with pytest.raises(OperatorError) as kosong:
        baca_qr("   ")
    assert kosong.value.code == PLAT_KOSONG

    with pytest.raises(OperatorError) as bukan:
        baca_qr("https://contoh.id/promo")
    assert bukan.value.code == BUKAN_PLAT


def test_kode_bukan_plat_terdaftar_supaya_wajib_diterjemahkan():
    """`CODES` itu yang dipakai penjaga terjemahan. Kode yang tidak terdaftar akan
    lolos ke layar sebagai teks server mentah dalam satu bahasa saja."""
    from palmgrade.domain.operator_error import BUKAN_PLAT, CODES

    assert BUKAN_PLAT in CODES


# ── scan di timbang keluar ───────────────────────────────────────────────────


def _timbang_masuk(store: ConsoleStore, wid: str, plat: str, **over) -> None:
    row = {
        "id": wid, "ref": None, "plate_number": plat,
        "plate_norm": "".join(c for c in plat.upper() if c.isalnum()),
        "truck_id": truck_id_for(plat), "work_date": "2026-09-15",
        "gross_kg": 13000.0, "tare_kg": None, "net_kg": None,
        "entered_at": "2026-09-15T08:00:00+07:00", "exited_at": None,
    }
    row.update(over)
    store.upsert_weighing(row)


def test_scan_keluar_menemukan_tiket_terbuka_truk_itu(store, scan):
    """Operator scan platnya, sistem yang mencari tiketnya — bukan operator yang
    menyusuri tabel mencari baris truk itu."""
    _truk(store, "BE 4412 OFL")
    _timbang_masuk(store, "w-1", "BE 4412 OFL")

    hasil = scan.open_ticket("BE4412OFL", "2026-09-15")

    assert hasil["ditemukan"] is True
    assert hasil["weighing"]["id"] == "w-1"


def test_tiket_yang_sudah_ada_taranya_bukan_tiket_terbuka(store, scan):
    """Sudah ditimbang keluar. Menawarkannya lagi berarti tara pertama ditimpa dan
    neto berubah tanpa ada yang tahu."""
    _truk(store, "BE 4412 OFL")
    _timbang_masuk(store, "w-1", "BE 4412 OFL", tare_kg=5000.0, net_kg=8000.0,
                   exited_at="2026-09-15T09:00:00+07:00")

    hasil = scan.open_ticket("BE4412OFL", "2026-09-15")

    assert hasil["ditemukan"] is False


def test_dua_tiket_terbuka_ditolak_bukan_ditebak(store, scan):
    """Keputusan operator 2026-09-15: menebak di sini bisa mencampur tonase dua
    kunjungan — persis bug adopsi tiket yang kami laporkan ke AutoERP. Layar meminta
    operator memilih sendiri."""
    _truk(store, "BE 4412 OFL")
    _timbang_masuk(store, "w-1", "BE 4412 OFL")
    _timbang_masuk(store, "w-2", "BE 4412 OFL", entered_at="2026-09-15T10:00:00+07:00")

    hasil = scan.open_ticket("BE4412OFL", "2026-09-15")

    assert hasil["ditemukan"] is False
    assert hasil["ganda"] is True
    assert len(hasil["choices"]) == 2


def test_truk_tanpa_tiket_terbuka_dijawab_belum_ada(store, scan):
    """Truk baru masuk gerbang keluar tanpa pernah timbang masuk — kejadian kalau
    timbang masuknya terlewat. Jawabannya jelas, bukan error."""
    _truk(store, "BE 4412 OFL")

    hasil = scan.open_ticket("BE4412OFL", "2026-09-15")

    assert hasil["ditemukan"] is False
    assert hasil.get("ganda") is not True


def test_tiket_hari_lain_tidak_ikut_terbawa(store, scan):
    """Tiket kemarin yang taranya belum terisi tidak boleh muncul hari ini: netonya
    akan memakai bruto kemarin dan tara hari ini."""
    _truk(store, "BE 4412 OFL")
    _timbang_masuk(store, "w-kemarin", "BE 4412 OFL", work_date="2026-09-14")

    hasil = scan.open_ticket("BE4412OFL", "2026-09-15")

    assert hasil["ditemukan"] is False


def test_scan_keluar_menolak_yang_bukan_plat(store, scan):
    from palmgrade.domain.operator_error import BUKAN_PLAT

    with pytest.raises(OperatorError) as kena:
        scan.open_ticket("https://contoh.id", "2026-09-15")
    assert kena.value.code == BUKAN_PLAT


def test_scan_keluar_tidak_pernah_menulis_apa_pun(store, scan):
    """Mencari saja. Yang menulis tara tetap `catat_timbangan`, satu jalur."""
    _truk(store, "BE 4412 OFL")
    _timbang_masuk(store, "w-1", "BE 4412 OFL")

    scan.open_ticket("BE4412OFL", "2026-09-15")

    assert store.weighing("w-1")["tare_kg"] is None
