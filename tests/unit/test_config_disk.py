"""`DISK_PERINGATAN_GB` / `DISK_KRITIS_GB` (batch 3.7): bawaan aman, salah ketik
tidak menahan line, dan compose meneruskannya.

`.env` PC Lampung tidak punya variabel ini dan compose host tidak ikut rilis:
tanpa apa pun yang diubah di sana, line jalan dengan 15 / 5 GB.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from palmgrade.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]


def test_tanpa_env_memakai_bawaan(monkeypatch):
    monkeypatch.delenv("DISK_PERINGATAN_GB", raising=False)
    monkeypatch.delenv("DISK_KRITIS_GB", raising=False)
    s = Settings()
    assert (s.disk_peringatan_gb, s.disk_kritis_gb) == (15.0, 5.0)


def test_nilai_sah_dan_nol_dipakai(monkeypatch):
    monkeypatch.setenv("DISK_PERINGATAN_GB", "12.5")
    monkeypatch.setenv("DISK_KRITIS_GB", "0")
    s = Settings()
    assert (s.disk_peringatan_gb, s.disk_kritis_gb) == (12.5, 0.0)


def test_salah_ketik_tidak_menahan_boot_dan_dicatat(monkeypatch, caplog):
    monkeypatch.setenv("DISK_KRITIS_GB", "5GB")
    caplog.set_level(logging.WARNING, logger="palmgrade.core.config")
    assert Settings().disk_kritis_gb == 5.0
    assert "DISK_KRITIS_GB" in caplog.text


def test_tiap_line_meneruskan_ambang_disk_dengan_bawaan():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for nama in ("ripe-line-1", "ripe-line-2", "ripe-line-3"):
        env = compose["services"][nama]["environment"]
        assert "DISK_PERINGATAN_GB=${DISK_PERINGATAN_GB:-15}" in env, nama
        assert "DISK_KRITIS_GB=${DISK_KRITIS_GB:-5}" in env, nama


def test_contoh_env_menyebut_ambang_disk():
    isi = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "\nDISK_PERINGATAN_GB=15\n" in isi and "\nDISK_KRITIS_GB=5\n" in isi
