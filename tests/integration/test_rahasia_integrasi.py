"""Integrasi pembanding secret: yang ditolak tidak meninggalkan jejak apa pun."""
from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.integrations.notifications.line_client import LineClient, LinePlcTolak
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console_deps import get_console_service
from palmgrade.routes.console_ingest import ingest_router
from palmgrade.routes.internal_bahaya import buat_router
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.hapus_data_line import PENANDA
from palmgrade.workers.runtime_state import RuntimeState

SECRET = "kunci-mesin-palsu"
LINE = LineEndpoint("line-1", "Line 1", 8001, "m-1")
TIMBANG = {"ref": "TKT-1", "plate_number": "B 1234 XY", "gross_kg": 14820, "entered_at": "2026-09-28T08:00:00+07:00"}


@pytest.fixture
def konsol(tmp_path):
    settings = replace(Settings(), repo_root=tmp_path, webhook_secret=SECRET, factory_tz="Asia/Jakarta")
    service = ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), line_client=None)
    app = FastAPI()
    app.include_router(ingest_router, prefix=settings.backend_api_ver)
    app.dependency_overrides[get_console_service] = lambda: service
    return TestClient(app), service


@pytest.mark.parametrize("header", [{}, {"x-webhook-secret": ""}, {"x-webhook-secret": SECRET + "x"}])
def test_timbangan_dengan_secret_salah_tidak_menulis_tiket(konsol, header):
    client, service = konsol

    assert client.post("/api/v1/internal/scale/weighing", json=TIMBANG, headers=header).status_code == 401
    assert service.weighings("2026-09-28") == []


def test_timbangan_dengan_secret_benar_tercatat(konsol):
    client, service = konsol

    jawab = client.post("/api/v1/internal/scale/weighing", json=TIMBANG, headers={"x-webhook-secret": SECRET})

    assert jawab.status_code in (200, 201), jawab.text
    assert len(service.weighings("2026-09-28")) == 1


def test_perintah_hapus_dengan_secret_salah_tidak_menyentuh_line(tmp_path, monkeypatch):
    monkeypatch.setenv("REKAMAN_DIR", str(tmp_path / "videos"))
    line_settings = replace(Settings(), repo_root=tmp_path / "line-1", internal_secret=SECRET)
    keluar: list[float] = []
    app = FastAPI()
    app.include_router(buat_router(settings=lambda: line_settings, state=RuntimeState, keluar=keluar.append))
    klien = LineClient(
        replace(Settings(), console_line_host="http://line", internal_secret="bukan-" + SECRET),
        transport=httpx.ASGITransport(app=app),
    )

    with pytest.raises(LinePlcTolak) as info:
        asyncio.run(klien.hapus_data(LINE, mode="semua", diminta_oleh="penyusup"))

    assert info.value.status_code == 401
    assert keluar == []
    assert not (line_settings.artifacts_dir / PENANDA).exists()
