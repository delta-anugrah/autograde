"""Layar Akun (support): bentuk satu baris akun — murni, tanpa I/O.

Yang paling penting di sini bukan kolom yang ADA, tapi kolom yang TIDAK: hash
sandi tidak pernah boleh ikut, walau barisnya kebetulan membawanya. Sandi aslinya
tidak bisa dibaca dari hash, tapi hash yang bocor bisa ditebak di luar pabrik
tanpa batas percobaan — dan layar ini dibuka lewat AnyDesk.
"""
from __future__ import annotations

from palmgrade.domain.daftar_akun import ringkas_akun

SEKARANG = 1_800_000_000.0


def _baris(**ubah):
    dasar = {
        "email": "ani@pks.id",
        "full_name": "Ani",
        "role": "operator",
        "origin": "lokal",
        "status": "active",
        "created_at": 1_700_000_000.0,
        "fail_count": 0,
        "last_failed_at": None,
        "sesi_aktif": 0,
    }
    return {**dasar, **ubah}


def test_akun_aktif():
    hasil = ringkas_akun(_baris(), now=SEKARANG)
    assert hasil["keadaan"] == "aktif"
    assert hasil["terkunci_detik"] == 0
    assert hasil["email"] == "ani@pks.id"
    assert hasil["nama"] == "Ani"
    assert hasil["role"] == "operator"
    assert hasil["dibuat"] == 1_700_000_000.0


def test_akun_mati_tetap_mati_walau_juga_terkunci():
    """Mati mengalahkan terkunci: akun mati tidak bisa masuk sama sekali, jadi
    menulis "terkunci 3 menit" menyuruh orang menunggu hal yang tidak akan terjadi."""
    hasil = ringkas_akun(
        _baris(status="off", fail_count=9, last_failed_at=SEKARANG - 5), now=SEKARANG
    )
    assert hasil["keadaan"] == "mati"


def test_akun_terkunci_menyebut_sisa_detik():
    # Lima salah = kunci 60 detik (aturan yang sama dengan layar login).
    hasil = ringkas_akun(_baris(fail_count=5, last_failed_at=SEKARANG - 10), now=SEKARANG)
    assert hasil["keadaan"] == "terkunci"
    assert hasil["terkunci_detik"] == 50


def test_kunci_yang_sudah_lewat_kembali_aktif():
    hasil = ringkas_akun(_baris(fail_count=5, last_failed_at=SEKARANG - 61), now=SEKARANG)
    assert hasil["keadaan"] == "aktif"
    assert hasil["terkunci_detik"] == 0


def test_salah_sandi_di_bawah_batas_belum_terkunci():
    hasil = ringkas_akun(_baris(fail_count=4, last_failed_at=SEKARANG - 1), now=SEKARANG)
    assert hasil["keadaan"] == "aktif"


def test_sedang_masuk_dari_jumlah_sesi():
    assert ringkas_akun(_baris(sesi_aktif=2), now=SEKARANG)["sedang_masuk"] is True
    assert ringkas_akun(_baris(sesi_aktif=0), now=SEKARANG)["sedang_masuk"] is False


def test_asal_akun_diteruskan_apa_adanya():
    """Asal menentukan di mana sandinya diganti: `erp` di AutoERP, `lokal` di
    terminal PC itu. Itu jawaban untuk "user lupa sandi"."""
    assert ringkas_akun(_baris(origin="erp"), now=SEKARANG)["asal"] == "erp"
    assert ringkas_akun(_baris(origin="lokal"), now=SEKARANG)["asal"] == "lokal"


def test_hash_tidak_pernah_ikut_walau_ada_di_baris():
    baris = _baris(password_hash="scrypt$16384$8$1$abc$def", id="rahasia-id")
    hasil = ringkas_akun(baris, now=SEKARANG)
    assert "password_hash" not in hasil
    assert "scrypt$" not in repr(hasil)


def test_kolomnya_daftar_tertutup():
    """Kolom baru di tabel `operators` tidak boleh ikut keluar tanpa sengaja —
    yang dikirim ke layar ditulis satu per satu, bukan diteruskan."""
    hasil = ringkas_akun(_baris(kolom_baru="apa pun"), now=SEKARANG)
    assert set(hasil) == {
        "email", "nama", "role", "asal", "keadaan", "terkunci_detik",
        "sedang_masuk", "dibuat",
    }
