"""Integration (batch 5.10, 5.12): `/api/console/history` filtered the way the Grading tab
asks, every row naming its small photo, on real routes and real SQLite.
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
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService

SANDI = "sandi-integrasi-saring"


@pytest.fixture
def rakitan(tmp_path):
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
    return klien, service


def _janjang(service, nomor: int, line: int, truk: str | None) -> None:
    service.ingest(build_event_payload(
        machine_id=service.lines[line].machine_id, file_ts=f"2026-10-05_07-41-0{nomor}_000000",
        timestamp=datetime.now(UTC).isoformat(), ripeness_status="ACC", ripeness_confidence=0.9,
        capture_type="auto", image_path=f"captures/results/2026-10-05/x/bbox/Ripe/{nomor}.webp",
        truck_id=truk, assignment_id=None,
    ))


def test_history_filters_by_line_and_truck_and_names_the_small_photo(rakitan):
    klien, service = rakitan
    truk = klien.post("/api/console/trucks", json={"plate_number": "BE 1 AA"}).json()["id"]
    _janjang(service, 1, 0, truk)
    _janjang(service, 2, 0, None)
    _janjang(service, 3, 1, truk)

    semua = klien.get("/api/console/history?limit=25&offset=0").json()
    line_1 = klien.get("/api/console/history?limit=25&offset=0&line_code=line-1").json()
    truknya = klien.get(f"/api/console/history?limit=25&offset=0&truck_id={truk}").json()
    keduanya = klien.get(f"/api/console/history?limit=25&offset=0&line_code=line-2&truck_id={truk}").json()

    assert (semua["total"], line_1["total"], truknya["total"], keduanya["total"]) == (3, 2, 2, 1)
    assert {r["line_code"] for r in line_1["items"]} == {"line-1"}
    baris = keduanya["items"][0]
    assert baris["thumb_url"] == "/captures/line-2/results/2026-10-05/x/thumb/Ripe/3.webp"
    assert baris["image_url"] == "/captures/line-2/results/2026-10-05/x/bbox/Ripe/3.webp"
