"""Integration (batch 5.3, 6.4): the page and its two polls, real routes on real SQLite.

- `/console` tells the browser to ask again every time, so a kiosk that reloads after an
  update gets the new page, not the one it kept.
- `/api/console/state` no longer carries grading rows; `/api/console/history` is the one
  source of the Grading table and still answers with rows and a total.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.vision_event import build_event_payload
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import (
    get_auth_service,
    get_console_service,
    get_dev_service,
    get_pembaruan_service,
)
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService

SANDI = "sandi-integrasi-segar"


class _Dev:
    async def license_state(self) -> dict:
        return {}

    def app_version(self) -> str:
        return "v-integrasi"


class _Keadaan:
    def as_dict(self) -> dict:
        return {}


class _Pembaruan:
    def keadaan(self) -> _Keadaan:
        return _Keadaan()


@pytest.fixture
def konsol(tmp_path):
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
    app.dependency_overrides[get_dev_service] = lambda: _Dev()
    app.dependency_overrides[get_pembaruan_service] = lambda: _Pembaruan()
    klien = TestClient(app)
    assert klien.post("/api/console/login", json={"email": "operator@pks.test", "sandi": SANDI}).status_code == 200
    return klien, service


def _janjang(service: ConsoleService, nomor: int) -> dict:
    return build_event_payload(
        machine_id=service.lines[0].machine_id, file_ts=f"2026-10-04_07-41-0{nomor}_000000",
        timestamp=datetime.now(UTC).isoformat(), ripeness_status="ACC", ripeness_confidence=0.9,
        capture_type="auto", image_path=f"captures/results/2026-10-04/{nomor}.webp",
        truck_id=None, assignment_id=None,
    )


def test_the_page_is_never_served_from_a_kept_copy(konsol):
    klien, _ = konsol

    halaman = klien.get("/console")

    assert halaman.status_code == 200
    assert halaman.headers["cache-control"] == "no-cache"


def test_the_grading_rows_come_from_history_and_not_from_state(konsol):
    klien, service = konsol
    for nomor in (1, 2, 3):
        service.ingest(_janjang(service, nomor))

    state = klien.get("/api/console/state").json()
    history = klien.get("/api/console/history?limit=2&offset=0").json()

    assert "recent" not in state
    assert state["lines"][0]["total"] == 3, "the counts still ride the 2 s poll"
    assert state["versi"] == "v-integrasi", "what the page compares to reload itself"
    assert history["total"] == 3 and len(history["items"]) == 2
