"""Integrasi dua kunci: konsol memerintah line dengan INTERNAL_SECRET, kunci
program timbangan (WEBHOOK_SECRET) tidak bisa, dan konsol-line yang tidak
sepakat GAGAL TERLIHAT, bukan diam."""
from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.domain.operator_error import LINE_MENOLAK, LINE_TIDAK_MENJAWAB
from palmgrade.integrations.notifications.line_client import (
    LineClient,
    LinePlcTolak,
    LineUnavailable,
)
from palmgrade.routes.internal_bahaya import buat_router
from palmgrade.workers.runtime_state import RuntimeState

WEBHOOK = "kunci-timbangan-palsu"
INTERNAL = "kunci-perintah-palsu"
LINE = LineEndpoint("line-1", "Line 1", 8001, "m-1")


@pytest.fixture
def line(tmp_path, monkeypatch):
    monkeypatch.setenv("REKAMAN_DIR", str(tmp_path / "videos"))
    settings = replace(Settings(), repo_root=tmp_path / "line-1", webhook_secret=WEBHOOK, internal_secret=INTERNAL)
    keluar: list[float] = []
    app = FastAPI()
    app.include_router(buat_router(settings=lambda: settings, state=RuntimeState, keluar=keluar.append))
    return app, keluar


def _konsol(app, secret: str) -> LineClient:
    return LineClient(
        replace(Settings(), console_line_host="http://line", internal_secret=secret),
        transport=httpx.ASGITransport(app=app),
    )


def test_konsol_dengan_internal_secret_memerintah_line(line):
    app, _ = line
    assert "berkas" in asyncio.run(_konsol(app, INTERNAL).rekam_berkas(LINE))


def test_kunci_program_timbangan_tidak_bisa_menghapus_data_line(line):
    app, keluar = line
    with pytest.raises(LinePlcTolak) as info:
        asyncio.run(_konsol(app, WEBHOOK).hapus_data(LINE, mode="semua", diminta_oleh="timbangan"))
    assert info.value.status_code == 401
    assert keluar == []


def test_konsol_dan_line_tidak_sepakat_terlihat_sebagai_galat(line):
    """Review Focus 3: .env diedit, compose host cuma meneruskan ke sebagian container.

    `LineUnavailable` saja tidak cukup dibuktikan: sebuah line yang MATI SUNGGUHAN
    juga melempar itu (LINE_TIDAK_MENJAWAB), dan tab Log yang cuma menulis DEBUG
    untuk keduanya tidak bisa membedakan "kunci beda" dari "line mati" (Important
    #1 review). `rekam_berkas` di sini menjawab HTTP dengan kode `LINE_MENOLAK` dan
    `status=401`, bukan generik: layar dan Danger Zone bisa membedakan line yang
    hidup tapi menolak kuncinya dari line yang benar-benar tidak menjawab.
    """
    app, _ = line
    with pytest.raises(LineUnavailable) as info:
        asyncio.run(_konsol(app, "nilai-lama-di-konsol").rekam_berkas(LINE))
    assert info.value.code == LINE_MENOLAK
    assert info.value.code != LINE_TIDAK_MENJAWAB
    assert info.value.params.get("status") == 401
