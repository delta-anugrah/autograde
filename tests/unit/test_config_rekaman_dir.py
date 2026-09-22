"""Folder rekaman video developer.

Satu-satunya bagian fitur rekam yang tetap di `.env`, karena jalurnya berbeda
antara container dan host dan karena itu harus bisa di-mount. Resolusi, fps,
dan bitrate diatur dari layar developer (`domain/setelan_rekam.py`).
"""
from __future__ import annotations

from pathlib import Path

from palmgrade.core.config import Settings


def test_bawaan_folder_videos_di_repo(monkeypatch):
    monkeypatch.delenv("REKAMAN_DIR", raising=False)
    s = Settings()
    assert s.videos_dir.name == "videos"
    assert s.videos_dir.parent == s.repo_root


def test_bisa_ditimpa_env(monkeypatch):
    monkeypatch.setenv("REKAMAN_DIR", "/data/rekaman")
    assert Settings().videos_dir == Path("/data/rekaman")


def test_env_kosong_jatuh_ke_bawaan(monkeypatch):
    # Compose menulis `REKAMAN_DIR=${REKAMAN_DIR:-}` — string kosong harus
    # diperlakukan sebagai "tidak disetel", bukan sebagai Path("").
    monkeypatch.setenv("REKAMAN_DIR", "   ")
    s = Settings()
    assert s.videos_dir.name == "videos"


def test_terpisah_dari_artifacts(monkeypatch):
    """Rekaman BUKAN bukti grading dan tidak boleh ikut retensi otomatis.

    `BatchUploadWorker._retention()` menyapu isi `artifacts/`; rekaman yang
    duduk di sana akan terhapus diam-diam di tengah penelusuran masalah.
    """
    monkeypatch.delenv("REKAMAN_DIR", raising=False)
    s = Settings()
    assert s.videos_dir != s.artifacts_dir
    assert s.artifacts_dir not in s.videos_dir.parents
