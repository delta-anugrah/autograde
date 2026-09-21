"""Settings menurunkan pilihan layar, dan main.py membangun kamera dari rencana."""
from __future__ import annotations

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.sumber_kamera_resolver import rencana_kamera


@pytest.fixture(autouse=True)
def _bersihkan_env(monkeypatch):
    for nama in ("CAMERA_TYPE", "MEDIA_FILE", "CAMERA_VIDEO_PATH", "CAMERA_PHOTO_PATH"):
        monkeypatch.delenv(nama, raising=False)


def test_media_file_terbaca(monkeypatch):
    monkeypatch.setenv("MEDIA_FILE", "konveyor.mp4")
    assert Settings().media_file == "konveyor.mp4"


def test_media_file_bawaan_kosong():
    assert Settings().media_file == ""


def test_sumber_hikrobot_bawaan():
    assert Settings().sumber_kamera() == "hikrobot"


def test_sumber_webcam(monkeypatch):
    monkeypatch.setenv("CAMERA_TYPE", "opencv")
    assert Settings().sumber_kamera() == "webcam"


def test_sumber_video(monkeypatch):
    monkeypatch.setenv("CAMERA_TYPE", "opencv")
    monkeypatch.setenv("MEDIA_FILE", "a.mp4")
    assert Settings().sumber_kamera() == "video"


def test_sumber_foto(monkeypatch):
    monkeypatch.setenv("CAMERA_TYPE", "photo")
    monkeypatch.setenv("MEDIA_FILE", "a.jpg")
    assert Settings().sumber_kamera() == "foto"


def test_camera_type_asing_jatuh_ke_hikrobot(monkeypatch):
    # Line tetap boot memakai kamera sungguhan, bukan gagal.
    monkeypatch.setenv("CAMERA_TYPE", "gopro")
    assert Settings().sumber_kamera() == "hikrobot"


def test_rencana_dari_settings(monkeypatch):
    monkeypatch.setenv("CAMERA_TYPE", "opencv")
    monkeypatch.setenv("MEDIA_FILE", "konveyor.mp4")
    monkeypatch.setenv("CAMERA_VIDEO_LOOP", "true")
    s = Settings()
    r = rencana_kamera(s.sumber_kamera(), s.media_file, s.camera_video_loop)
    assert r.camera_type == "opencv"
    assert r.video_path == "/media/konveyor.mp4"
    assert r.loop is True


def test_env_lama_video_path_masih_jalan(monkeypatch):
    # .env lama menulis path penuh, bukan nama berkas. Tetap terbaca sebagai
    # "video" supaya PC yang belum pindah ke media.env tidak berhenti.
    monkeypatch.setenv("CAMERA_TYPE", "opencv")
    monkeypatch.setenv("CAMERA_VIDEO_PATH", "/videos/video-in")
    assert Settings().sumber_kamera() == "video"
