"""Aturan sumber kamera per line — tanpa I/O, tanpa cv2."""
from __future__ import annotations

import pytest

from palmgrade.domain.sumber_kamera import (
    BUTUH_BERKAS,
    CAMERA_TYPE_UNTUK,
    SUMBER,
    SumberTidakSah,
    bersihkan_sumber,
)


def test_empat_pilihan_layar():
    assert SUMBER == ("hikrobot", "webcam", "video", "foto")


def test_pemetaan_ke_camera_type():
    # Empat pilihan layar memetakan ke tiga nilai CAMERA_TYPE: webcam dan video
    # sama-sama OpenCVCamera, yang membedakan cuma ada-tidaknya berkas.
    assert CAMERA_TYPE_UNTUK == {
        "hikrobot": "hikrobot",
        "webcam": "opencv",
        "video": "opencv",
        "foto": "photo",
    }


def test_hikrobot_tanpa_berkas_sah():
    assert bersihkan_sumber({"sumber": "hikrobot"}) == {
        "sumber": "hikrobot",
        "berkas": "",
        "ulang": False,
    }


def test_video_dengan_berkas_sah():
    hasil = bersihkan_sumber({"sumber": "video", "berkas": "konveyor.mp4", "ulang": True})
    assert hasil == {"sumber": "video", "berkas": "konveyor.mp4", "ulang": True}


def test_pilihan_asing_ditolak():
    with pytest.raises(SumberTidakSah, match="sumber harus salah satu"):
        bersihkan_sumber({"sumber": "gopro"})


def test_video_tanpa_berkas_ditolak():
    # Tanpa ini line boot, PhotoCamera/OpenCVCamera raise, container mati,
    # restart:unless-stopped menyalakannya lagi — loop yang cuma bisa
    # dihentikan lewat AnyDesk.
    with pytest.raises(SumberTidakSah, match="video butuh berkas"):
        bersihkan_sumber({"sumber": "video", "berkas": ""})


def test_foto_tanpa_berkas_ditolak():
    with pytest.raises(SumberTidakSah, match="foto butuh berkas"):
        bersihkan_sumber({"sumber": "foto"})


def test_hikrobot_dengan_berkas_ditolak():
    # Berkas yang diisi tapi tidak pernah dibaca adalah keadaan yang terlihat
    # benar di layar dan tidak melakukan apa-apa.
    with pytest.raises(SumberTidakSah, match="hikrobot tidak memakai berkas"):
        bersihkan_sumber({"sumber": "hikrobot", "berkas": "konveyor.mp4"})


@pytest.mark.parametrize(
    "nama",
    [
        "../rahasia.env",
        "/etc/passwd",
        "sub/dir.mp4",
        "..",
        "a\\b.mp4",
        # Newline DI TENGAH nama: `tulis()` menulis nama apa adanya, jadi ini
        # menyuntikkan baris kedua ke `media.env` dan menggandakan kuncinya.
        # Harus di tengah, bukan di ujung — ujungnya sudah dimakan `.strip()`,
        # jadi kasus itu tidak membuktikan penyaringnya bekerja.
        "a.mp4\nLINE_1_CAMERA_TYPE=photo",
        "a.mp4\rLINE_1_MEDIA_FILE=/etc/passwd",
    ],
)
def test_nama_berkas_berbahaya_ditolak(nama):
    with pytest.raises(SumberTidakSah, match="nama berkas"):
        bersihkan_sumber({"sumber": "video", "berkas": nama})


def test_berkas_dipangkas_spasi():
    hasil = bersihkan_sumber({"sumber": "foto", "berkas": "  sawit.jpg  "})
    assert hasil["berkas"] == "sawit.jpg"


def test_ulang_dari_string():
    # Input HTML mengirim "true"/"on", bukan boolean JSON.
    assert bersihkan_sumber({"sumber": "video", "berkas": "a.mp4", "ulang": "true"})["ulang"] is True
    assert bersihkan_sumber({"sumber": "video", "berkas": "a.mp4", "ulang": "off"})["ulang"] is False


def test_field_asing_ditolak():
    with pytest.raises(SumberTidakSah, match="field tidak dikenal"):
        bersihkan_sumber({"sumber": "hikrobot", "warna": "merah"})


def test_payload_bukan_objek_ditolak():
    with pytest.raises(SumberTidakSah, match="harus objek"):
        bersihkan_sumber(["hikrobot"])


def test_butuh_berkas_isinya_video_dan_foto():
    assert BUTUH_BERKAS == frozenset({"video", "foto"})
