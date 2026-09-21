"""Settings menurunkan pilihan layar, dan main.py membangun kamera dari rencana."""
from __future__ import annotations

from pathlib import Path

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


def test_media_dir_jatuh_ke_folder_repo_tanpa_env(monkeypatch):
    """Tanpa `MEDIA_DIR`, bawaannya `media/` di repo — bukan `/media`.

    `/media` itu path DI DALAM container, hasil mount `./media:/media` di
    compose. Jalur native (`make console`, atau `uvicorn` langsung) tidak punya
    mount itu, jadi bawaan absolut membuat konsol menatap folder yang tidak ada
    di macOS.

    Gejalanya menipu: `MediaLibrary` sengaja memulangkan daftar KOSONG untuk
    folder yang tidak ada (layar kosong bisa dibaca, layar gagal-muat tidak),
    jadi folder yang salah terlihat persis seperti folder yang memang belum
    diisi — nol galat, nol petunjuk di log. Terjadi 2026-09-21.
    """
    monkeypatch.delenv("MEDIA_DIR", raising=False)
    s = Settings()
    assert s.media_dir.endswith("/media")
    assert s.media_dir != "/media", "bawaan absolut container bocor ke jalur native"
    assert Path(s.media_dir) == s.repo_root / "media"


def test_media_env_path_jatuh_ke_repo_tanpa_env(monkeypatch):
    monkeypatch.delenv("MEDIA_ENV_PATH", raising=False)
    s = Settings()
    assert Path(s.media_env_path) == s.repo_root / "media.env"


def test_env_tetap_menang_untuk_docker(monkeypatch):
    # Compose mengisi keduanya; jalur Docker tidak boleh ikut jatuh ke repo.
    monkeypatch.setenv("MEDIA_DIR", "/media")
    monkeypatch.setenv("MEDIA_ENV_PATH", "/config/media.env")
    s = Settings()
    assert s.media_dir == "/media"
    assert s.media_env_path == "/config/media.env"
