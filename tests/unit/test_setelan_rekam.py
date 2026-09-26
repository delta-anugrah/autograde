"""Batas kewarasan setelan rekam video — murni, tanpa I/O.

Beda dari `setelan_grading`, angka di sini tidak mengubah uang: salah setel
cuma membuat videonya besar atau buram, bukan janjang salah dibuang. Jadi yang
dijaga cuma nilai yang pasti gagal di encoder.
"""
from __future__ import annotations

import pytest

from palmgrade.domain.setelan_rekam import (
    BAWAAN,
    SetelanRekamTidakSah,
    bersihkan_setelan_rekam,
)


def test_payload_kosong_memakai_nilai_bawaan():
    assert bersihkan_setelan_rekam({}) == BAWAAN


def test_nilai_sah_dipakai_apa_adanya():
    hasil = bersihkan_setelan_rekam({"width": 1920, "height": 1080, "fps": 10})
    assert hasil == {"width": 1920, "height": 1080, "fps": 10}


def test_bitrate_tidak_lagi_disetel():
    """`cv2.VideoWriter` tidak menerima bitrate, jadi angka ini tidak pernah
    sampai ke berkas. Dicabut 2026-09-25; kiriman lama yang masih membawanya
    (setelan tersimpan, layar versi lama) diabaikan, bukan ditolak."""
    assert "bitrate_kbps" not in BAWAAN
    assert "bitrate_kbps" not in bersihkan_setelan_rekam({"bitrate_kbps": 4000})


def test_field_yang_hilang_diisi_bawaan():
    hasil = bersihkan_setelan_rekam({"fps": 12})
    assert hasil["fps"] == 12
    assert hasil["width"] == BAWAAN["width"]


def test_string_angka_diterima():
    # Layar HTML mengirim value input sebagai string.
    assert bersihkan_setelan_rekam({"fps": "8"})["fps"] == 8


def test_float_dari_json_diterima():
    assert bersihkan_setelan_rekam({"fps": 8.0})["fps"] == 8


def test_none_dianggap_tidak_diisi():
    assert bersihkan_setelan_rekam({"fps": None})["fps"] == BAWAAN["fps"]


@pytest.mark.parametrize(
    "payload",
    [
        {"fps": 0},
        {"fps": 61},
        {"width": 0},
        {"width": 10_002},
        {"height": 0},
        {"height": 10_002},
    ],
)
def test_nilai_di_luar_batas_ditolak(payload):
    with pytest.raises(SetelanRekamTidakSah):
        bersihkan_setelan_rekam(payload)


def test_bukan_angka_ditolak():
    with pytest.raises(SetelanRekamTidakSah):
        bersihkan_setelan_rekam({"fps": "cepat"})


def test_pesan_salah_menyebut_field_dan_batasnya():
    # Yang membaca ini support lewat AnyDesk; "nilai tidak sah" tidak menolong.
    with pytest.raises(SetelanRekamTidakSah) as exc:
        bersihkan_setelan_rekam({"fps": 999})
    pesan = str(exc.value)
    assert "fps" in pesan
    assert "60" in pesan


def test_dimensi_ganjil_dibulatkan_ke_bawah():
    # H.264 menolak dimensi ganjil. Membulatkan di sini membuat encoder tidak
    # pernah menerima nilai yang pasti gagal — dan operator yang mengetik 1281
    # bermaksud "sekitar 1280", bukan "gagalkan saya".
    hasil = bersihkan_setelan_rekam({"width": 1281, "height": 1025})
    assert hasil["width"] == 1280
    assert hasil["height"] == 1024


def test_pembulatan_tidak_menjatuhkan_nilai_ke_bawah_batas():
    # Kontrol negatif: 3 dibulatkan jadi 2, dan 2 masih sah. Kalau batas bawah
    # dinaikkan tanpa memikirkan pembulatan, kasus ini yang menangkapnya.
    assert bersihkan_setelan_rekam({"width": 3})["width"] == 2


def test_field_asing_diabaikan_bukan_ditolak():
    # Layar versi berikutnya boleh mengirim field yang belum dikenal build ini.
    hasil = bersihkan_setelan_rekam({"fps": 5, "codec": "avc1"})
    assert "codec" not in hasil
    assert hasil["fps"] == 5


def test_bawaan_sendiri_lolos_validasi():
    # Kontrol negatif: nilai bawaan tidak boleh berada di luar batasnya sendiri.
    assert bersihkan_setelan_rekam(dict(BAWAAN)) == BAWAAN
