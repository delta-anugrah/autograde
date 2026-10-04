"""End-to-end: the Lepas paksa lane over HTTP, behind the session (2026-10-04).

Assembled here, not through `create_console_app()` (it opens the developer's
`state/console.db`). The line is a fake collaborator that never answers.
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.operator_error import LINE_TIDAK_MENJAWAB
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.routes.console_deps import pasang_penangan_validasi
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService

SANDI = "sawit2026"
OPERATOR = "op@pks.test"


class LineMati:
    def __init__(self) -> None:
        self.mati = False

    async def assign_truck(self, line, *, assignment_id, truck_id, assigned_at, ffb_source=None, plate=None):
        if self.mati:
            raise LineUnavailable(LINE_TIDAK_MENJAWAB, "line did not answer", line=line.name)


@pytest.fixture
def konsol(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual(
        {"email": OPERATOR, "full_name": "Bu Operator", "password_hash": hash_password(SANDI), "role": "operator"}
    )
    service = ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), store, LineMati())
    app = FastAPI()
    app.include_router(console_router)
    pasang_penangan_validasi(app)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    return app, service


def _masuk(app) -> TestClient:
    client = TestClient(app)
    assert client.post("/api/console/login", json={"email": OPERATOR, "sandi": SANDI}).status_code == 200
    return client


def test_without_a_session_the_lane_is_closed(konsol):
    app, _ = konsol
    jawab = TestClient(app).post("/api/console/lines/line-1/force-release")
    assert jawab.status_code == 401
    assert jawab.json()["detail"]["code"] == "belum_masuk"


def test_an_unknown_line_is_404_with_its_code(konsol):
    app, _ = konsol
    jawab = _masuk(app).post("/api/console/lines/line-9/force-release")
    assert jawab.status_code == 404
    assert jawab.json()["detail"]["code"] == "line_tidak_dikenal"


def test_an_operator_frees_a_dead_line_and_the_card_follows(konsol):
    app, service = konsol
    client = _masuk(app)
    truk = client.post("/api/console/trucks", json={"plate_number": "BE 9 ZZ"}).json()
    assert client.post("/api/console/lines/line-2/assign-truck", json={"truck_id": truk["id"]}).status_code == 200
    service.line_client.mati = True

    jawab = client.post("/api/console/lines/line-2/force-release")

    assert jawab.status_code == 200, jawab.text
    isi = jawab.json()
    assert (isi["line_code"], isi["truck_id"], isi["paksa"], isi["dipasang"]) == ("line-2", None, True, [])
    kartu = next(k for k in client.get("/api/console/state").json()["lines"] if k["line_code"] == "line-2")
    assert kartu["assignment"] is None
