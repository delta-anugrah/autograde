"""Integration (batch 5.6): `/api/console/trucks` says which trucks are on site.

Real routes on real SQLite, the weigh-in and weigh-out through the operator's own lane
(`POST /api/console/weighings`). On site = weighed in and not yet weighed out, the same
open-ticket rule the unloading queue uses.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService

SANDI = "sandi-integrasi-pilih"
WIB = ZoneInfo("Asia/Jakarta")


@pytest.fixture
def klien(tmp_path):
    settings = replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta")
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual(
        {"email": "operator@pks.test", "full_name": "Operator", "password_hash": hash_password(SANDI)}
    )
    service = ConsoleService(settings, store, line_client=None)
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    klien = TestClient(app)
    assert klien.post("/api/console/login", json={"email": "operator@pks.test", "sandi": SANDI}).status_code == 200
    return klien


def _di_lokasi(klien) -> dict[str, bool]:
    return {t["plate_number"]: t["di_lokasi"] for t in klien.get("/api/console/trucks").json()["items"]}


def test_a_truck_is_on_site_from_weigh_in_to_weigh_out(klien):
    for plat in ("BE 1 AA", "BE 2 BB"):
        assert klien.post("/api/console/trucks", json={"plate_number": plat}).status_code == 201
    assert _di_lokasi(klien) == {"BE 1 AA": False, "BE 2 BB": False}

    masuk = datetime.now(WIB).isoformat()
    isi = klien.post("/api/console/weighings", json={"plate_number": "BE 2 BB", "gross_kg": "12000", "entered_at": masuk})
    assert isi.status_code == 201, isi.text
    assert _di_lokasi(klien) == {"BE 1 AA": False, "BE 2 BB": True}

    kosong = klien.post("/api/console/weighings", json={"plate_number": "BE 2 BB", "tare_kg": "4000", "entered_at": masuk})
    assert kosong.status_code == 201, kosong.text
    assert _di_lokasi(klien) == {"BE 1 AA": False, "BE 2 BB": False}
