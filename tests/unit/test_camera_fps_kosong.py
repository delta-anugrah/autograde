"""`CAMERA_FPS` kosong berarti "tanya sumbernya", bukan line yang gagal start.

`.env.example` sendiri menyuruh mengosongkannya untuk sumber yang bisa melaporkan
lajunya sendiri, tapi `int("")` melempar `ValueError` saat `Settings` dibuat —
line mati sebelum sempat jalan, dengan pesan yang tidak menyebut `CAMERA_FPS`
sama sekali (`invalid literal for int() with base 10: ''`).

Untuk file video ini bukan kosmetik: `OpenCVCamera` hanya membaca fps bawaan
berkas kalau nilai ini tidak diisi. Diisi `24` sementara videonya 0,5 fps
membuatnya diputar 48x lebih cepat dari aslinya — terlihat seperti video yang
"lari lalu berhenti", bukan seperti salah setelan.
"""
from __future__ import annotations

import importlib

import pytest


def _camera_fps(monkeypatch, nilai: str | None) -> int:
    if nilai is None:
        monkeypatch.delenv("CAMERA_FPS", raising=False)
    else:
        monkeypatch.setenv("CAMERA_FPS", nilai)
    from palmgrade.core import config

    importlib.reload(config)
    return config.Settings().camera_fps


@pytest.mark.parametrize("nilai", ["", "   ", "\t"])
def test_kosong_jadi_nol_bukan_crash(monkeypatch, nilai):
    """0 = "jangan patok, tanya kameranya" (lihat `frame_capture_worker`)."""
    assert _camera_fps(monkeypatch, nilai) == 0


def test_nol_tetap_nol(monkeypatch):
    assert _camera_fps(monkeypatch, "0") == 0


def test_angka_biasa_tidak_berubah(monkeypatch):
    assert _camera_fps(monkeypatch, "20") == 20


def test_tanpa_env_pakai_bawaan(monkeypatch):
    assert _camera_fps(monkeypatch, None) == 20


def test_nilai_ngawur_tetap_gagal_keras(monkeypatch):
    """Kosong itu pilihan yang sah; `abc` itu salah ketik, dan menelannya diam-
    diam akan memutar video pada laju yang tidak pernah diminta siapa pun."""
    with pytest.raises(ValueError):
        _camera_fps(monkeypatch, "abc")


@pytest.fixture(autouse=True)
def _pulihkan_config():
    """`Settings` dibaca modul lain; kembalikan ke keadaan env asli sesudah tes."""
    yield
    from palmgrade.core import config

    importlib.reload(config)
