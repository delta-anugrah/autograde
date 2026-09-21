"""Isi folder /media, untuk mengisi dropdown layar."""
from __future__ import annotations

import os
from unittest.mock import patch

from palmgrade.services.media_library import (
    EKSTENSI_FOTO,
    EKSTENSI_VIDEO,
    MediaLibrary,
)


def test_ekstensi_yang_dikenal():
    assert EKSTENSI_VIDEO == frozenset({".mp4", ".avi", ".mkv"})
    assert EKSTENSI_FOTO == frozenset({".jpg", ".jpeg", ".png"})


def test_folder_tidak_ada_memberi_daftar_kosong(tmp_path):
    # Layar kosong bisa dibaca ("belum ada berkas"); layar yang gagal dimuat tidak.
    lib = MediaLibrary(tmp_path / "tidak-ada")
    assert lib.daftar_video() == []
    assert lib.daftar_foto() == []


def test_folder_kosong(tmp_path):
    assert MediaLibrary(tmp_path).daftar_video() == []


def test_menyaring_ekstensi(tmp_path):
    for nama in ("a.mp4", "b.avi", "c.jpg", "d.png", "e.txt", "f.env"):
        (tmp_path / nama).touch()
    lib = MediaLibrary(tmp_path)
    assert lib.daftar_video() == ["a.mp4", "b.avi"]
    assert lib.daftar_foto() == ["c.jpg", "d.png"]


def test_ekstensi_huruf_besar_ikut(tmp_path):
    (tmp_path / "A.MP4").touch()
    (tmp_path / "B.JPG").touch()
    lib = MediaLibrary(tmp_path)
    assert lib.daftar_video() == ["A.MP4"]
    assert lib.daftar_foto() == ["B.JPG"]


def test_terurut(tmp_path):
    for nama in ("z.mp4", "a.mp4", "m.mp4"):
        (tmp_path / nama).touch()
    assert MediaLibrary(tmp_path).daftar_video() == ["a.mp4", "m.mp4", "z.mp4"]


def test_folder_diabaikan(tmp_path):
    (tmp_path / "bukan-berkas.mp4").mkdir()
    assert MediaLibrary(tmp_path).daftar_video() == []


def test_ada(tmp_path):
    (tmp_path / "a.mp4").touch()
    lib = MediaLibrary(tmp_path)
    assert lib.ada("a.mp4") is True
    assert lib.ada("b.mp4") is False


def test_ada_menolak_nama_berbahaya(tmp_path):
    # Lapis kedua: `bersihkan_sumber` sudah menolaknya, tapi `ada()` dipanggil
    # juga dari jalur lain dan tidak boleh mengintip keluar folder.
    (tmp_path.parent / "rahasia.env").touch()
    lib = MediaLibrary(tmp_path)
    assert lib.ada("../rahasia.env") is False
    assert lib.ada("/etc/passwd") is False


def test_stat_permission_error_pada_satu_berkas(tmp_path):
    # Berkas yang stat-nya ditolak PermissionError tidak menutup seluruh layar;
    # berkas lain tetap dikembalikan. Ini kasus nyata di PC pabrik: root-owned
    # files atau Docker volume dengan UID berbeda.
    (tmp_path / "a.mp4").touch()
    (tmp_path / "b.mp4").touch()
    lib = MediaLibrary(tmp_path)

    # Patch os.stat untuk menolak akses "b.mp4"
    real_stat = os.stat

    def stat_side_effect(path, **kwargs):
        if "b.mp4" in str(path):
            raise PermissionError(f"Permission denied: {path}")
        return real_stat(path)

    with patch("os.stat", side_effect=stat_side_effect):
        # Hanya "a.mp4" dikembalikan; "b.mp4" yang ditolak dihilangkan
        assert lib.daftar_video() == ["a.mp4"]
        # ada() mewariskan fault-tolerance dari _daftar(): "b.mp4" tidak ada
        # dalam listing, jadi ditolak
        assert lib.ada("a.mp4") is True
        assert lib.ada("b.mp4") is False
