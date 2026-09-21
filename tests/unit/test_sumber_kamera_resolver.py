"""Pilihan layar -> kamera mana yang dipakai, dan path apa yang diberikan."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from palmgrade.domain.sumber_kamera_resolver import (
    MEDIA_DIR,
    RencanaKamera,
    rencana_kamera,
)


def test_media_dir_tetap():
    assert MEDIA_DIR == "/media"


def test_hikrobot():
    r = rencana_kamera("hikrobot", "", False)
    assert r == RencanaKamera(camera_type="hikrobot", video_path="", photo_path="", loop=False)


def test_webcam_tidak_memakai_path():
    # OpenCVCamera dengan video_path kosong = webcam lewat device index.
    r = rencana_kamera("webcam", "", False)
    assert r == RencanaKamera(camera_type="opencv", video_path="", photo_path="", loop=False)


def test_video_mengisi_video_path():
    r = rencana_kamera("video", "konveyor.mp4", True)
    assert r == RencanaKamera(
        camera_type="opencv", video_path="/media/konveyor.mp4", photo_path="", loop=True
    )


def test_foto_mengisi_photo_path():
    r = rencana_kamera("foto", "sawit.jpg", False)
    assert r == RencanaKamera(
        camera_type="photo", video_path="", photo_path="/media/sawit.jpg", loop=False
    )


def test_ulang_diabaikan_selain_video():
    # `loop` cuma berarti bagi OpenCVCamera yang membaca berkas video.
    assert rencana_kamera("foto", "sawit.jpg", True).loop is False
    assert rencana_kamera("hikrobot", "", True).loop is False
    assert rencana_kamera("webcam", "", True).loop is False


def test_media_dir_bisa_diganti_untuk_tes():
    r = rencana_kamera("video", "a.mp4", False, media_dir="/tmp/m")
    assert r.video_path == "/tmp/m/a.mp4"


def test_sumber_asing_ditolak():
    with pytest.raises(ValueError, match="sumber tidak dikenal"):
        rencana_kamera("gopro", "", False)


def test_rencana_beku():
    r = rencana_kamera("hikrobot", "", False)
    with pytest.raises(FrozenInstanceError):
        r.camera_type = "opencv"  # type: ignore[misc]
