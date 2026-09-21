"""Compose meneruskan setelan sumber per line dan me-mount media.

Setelan yang dibaca `Settings` tapi tidak diteruskan compose tidak terlihat di
container dan diam-diam jatuh ke bawaan. Itu cara ERP_COMPANY dulu terkirim
tanpa pernah terbaca — membaca kedua berkas satu sama lain adalah satu-satunya
pemeriksaan yang menangkapnya.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))

LINES = ("ripe-line-1", "ripe-line-2", "ripe-line-3")


def _env(service: str) -> dict[str, str]:
    entries = COMPOSE["services"][service]["environment"]
    return dict(e.split("=", 1) for e in entries)


def _volumes(service: str) -> list[str]:
    return COMPOSE["services"][service].get("volumes", [])


def test_tiap_line_memakai_prefix_line_sendiri():
    for i, service in enumerate(LINES, start=1):
        env = _env(service)
        assert env["CAMERA_TYPE"] == f"${{LINE_{i}_CAMERA_TYPE:-hikrobot}}"
        assert env["MEDIA_FILE"] == f"${{LINE_{i}_MEDIA_FILE:-}}"
        assert env["CAMERA_VIDEO_LOOP"] == f"${{LINE_{i}_VIDEO_LOOP:-false}}"


def test_line_memount_media_read_only():
    for service in LINES:
        assert "./media:/media:ro" in _volumes(service)


def test_konsol_memount_media_dan_berkas_setelan():
    vols = _volumes("console")
    assert "./media:/media:ro" in vols
    # Berkas setelan writable; itulah satu-satunya yang konsol boleh tulis.
    assert "./media.env:/config/media.env" in vols


def test_konsol_tidak_memount_dotenv():
    # `.env` memuat lisensi, R2, dan webhook secret. Konsol tidak boleh bisa
    # menulisnya, dan tidak perlu membacanya lewat mount.
    vols = _volumes("console")
    assert not any(v.startswith("./.env") for v in vols)


def test_bind_mount_video_lama_dibuang():
    # Bind-mount per berkas memilih berkasnya saat container DIBUAT; itulah yang
    # membuat memilih berkas dari layar mustahil sebelum ini.
    for service in LINES:
        assert not any("/videos/video-in" in v for v in _volumes(service))


def test_env_file_dipasang_di_keempat_service():
    for service in (*LINES, "console"):
        env_file = COMPOSE["services"][service].get("env_file")
        assert env_file, f"{service} tidak memakai env_file"
        assert "media.env" in str(env_file)


def test_konsol_tahu_letak_media():
    env = _env("console")
    assert env["MEDIA_DIR"] == "${MEDIA_DIR:-/media}"
    assert env["MEDIA_ENV_PATH"] == "${MEDIA_ENV_PATH:-/config/media.env}"
