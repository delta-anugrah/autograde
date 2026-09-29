"""`AI_MATI_DETIK` (batch 2.1): bawaan aman, salah ketik tidak menahan line.

`.env` PC Lampung tidak punya variabel ini, dan compose host tidak ikut rilis:
tanpa apa pun yang diubah di sana, line harus jalan dengan bawaan 30 detik.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from palmgrade.core.config import Settings
from palmgrade.domain.kesehatan_ai import AMBANG_BAWAAN_DETIK, AMBANG_MIN_DETIK

ROOT = Path(__file__).resolve().parents[2]


def test_tanpa_env_memakai_bawaan(monkeypatch):
    monkeypatch.delenv("AI_MATI_DETIK", raising=False)
    assert Settings().ai_mati_detik == AMBANG_BAWAAN_DETIK == 30


def test_nilai_sah_dipakai(monkeypatch):
    monkeypatch.setenv("AI_MATI_DETIK", "45")
    assert Settings().ai_mati_detik == 45


def test_salah_ketik_tidak_menahan_boot_dan_dicatat(monkeypatch, caplog):
    monkeypatch.setenv("AI_MATI_DETIK", "30s")
    caplog.set_level(logging.WARNING, logger="palmgrade.core.config")
    assert Settings().ai_mati_detik == AMBANG_BAWAAN_DETIK
    assert "AI_MATI_DETIK" in caplog.text


@pytest.mark.parametrize("teks", ["0", "3"])
def test_terlalu_pendek_dijepit_dan_dicatat(monkeypatch, caplog, teks):
    monkeypatch.setenv("AI_MATI_DETIK", teks)
    caplog.set_level(logging.WARNING, logger="palmgrade.core.config")
    assert Settings().ai_mati_detik == AMBANG_MIN_DETIK
    assert "di luar batas" in caplog.text


def test_tiap_line_meneruskan_ai_mati_detik_dengan_bawaan_30():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for nama in ("ripe-line-1", "ripe-line-2", "ripe-line-3"):
        env = compose["services"][nama]["environment"]
        assert "AI_MATI_DETIK=${AI_MATI_DETIK:-30}" in env, nama


def test_contoh_env_menyebut_ai_mati_detik():
    assert "\nAI_MATI_DETIK=30\n" in (ROOT / ".env.example").read_text(encoding="utf-8")
