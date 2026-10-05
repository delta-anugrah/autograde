"""End-to-end: the label size set on the Settings screen reaches every line, and survives a
line restart (2026-10-05).

The three joints that each broke once for an earlier setting (see `test_garis_capture_lane.py`):
screen to console (validated and stored), console to line (`kirim_setelan` carries it), and a
line that restarts asks the console again. Console assembled here, never `create_console_app()`.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes import console as console_routes
from palmgrade.routes.console_ingest import ingest_router
from palmgrade.services.console_service import ConsoleService

SECRET = "e2e-secret"
DASAR = {"conf_threshold": 0.5, "minimum_size": 3000}


class _LineMerekam:
    def __init__(self) -> None:
        self.setelan: list[dict] = []

    async def kirim_setelan(self, line, **kw) -> dict:
        self.setelan.append({"line_code": line.line_code, **kw})
        return kw


@pytest.fixture()
def konsol(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    settings = Settings()
    line = _LineMerekam()
    service = ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), line)
    app = FastAPI()
    app.include_router(console_routes.router)
    app.include_router(ingest_router, prefix=settings.backend_api_ver)
    app.dependency_overrides[console_routes.get_console_service] = lambda: service
    app.dependency_overrides[console_routes.require_support] = lambda: {"email": "support@test", "role": "support"}
    with TestClient(app) as c:
        yield c, line


def test_ukuran_label_sampai_ke_tiga_line(konsol):
    c, line = konsol

    res = c.post("/api/console/dev/setelan", json={**DASAR, "ukuran_label": "160"})

    assert res.status_code == 200, res.text
    assert res.json()["ukuran_label"] == 160
    assert len(line.setelan) == 3 and all(s["ukuran_label"] == 160 for s in line.setelan), line.setelan
    assert c.get("/api/console/dev/setelan").json()["ukuran_label"] == 160


def test_line_yang_restart_menanyakan_ulang_ukurannya(konsol):
    c, _line = konsol
    c.post("/api/console/dev/setelan", json={**DASAR, "ukuran_label": 220})

    res = c.get("/api/v1/internal/setelan", headers={"x-webhook-secret": SECRET})

    assert res.status_code == 200, res.text
    assert res.json()["ukuran_label"] == 220


def test_konsol_yang_belum_pernah_menyetel_menjawab_seratus(konsol):
    c, _line = konsol

    assert c.get("/api/console/dev/setelan").json()["ukuran_label"] == 100
    assert c.get("/api/v1/internal/setelan", headers={"x-webhook-secret": SECRET}).json()["ukuran_label"] == 100


def test_ukuran_di_luar_batas_ditolak_dan_tidak_dikirim(konsol):
    c, line = konsol

    res = c.post("/api/console/dev/setelan", json={**DASAR, "ukuran_label": 900})

    assert res.status_code == 400
    assert "ukuran_label" in res.text
    assert line.setelan == []
