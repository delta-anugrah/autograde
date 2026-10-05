"""End-to-end: the Scanner QR switch over real HTTP, behind a session.

Assembled here, not through `create_console_app()` (that opens the developer's
`state/console.db`).
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.routes.console_deps import pasang_penangan_validasi
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService

SANDI = "sawit2026"
OPERATOR = "op@pks.test"
SUPPORT = "sp@pks.test"
RUTE = "/api/console/dev/scanner-qr"


class _TanpaLine:
    async def assign_truck(self, *args, **kwargs):
        return None


@pytest.fixture
def app(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    for email, role in ((OPERATOR, "operator"), (SUPPORT, "support")):
        store.upsert_operator_manual(
            {"email": email, "full_name": email, "password_hash": hash_password(SANDI), "role": role}
        )
    service = ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), store, _TanpaLine())
    app = FastAPI()
    app.include_router(console_router)
    pasang_penangan_validasi(app)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    return app


def _masuk(app, email) -> TestClient:
    client = TestClient(app)
    r = client.post("/api/console/login", json={"email": email, "sandi": SANDI})
    assert r.status_code == 200, r.text
    return client


def test_support_menyalakan_dan_operator_melihatnya_di_polling(app):
    support = _masuk(app, SUPPORT)
    assert support.get(RUTE).json() == {"aktif": False}
    r = support.post(RUTE, json={"aktif": True})
    assert r.status_code == 200, r.text
    assert r.json() == {"aktif": True}
    assert _masuk(app, OPERATOR).get("/api/console/state").json()["scanner_qr"] is True


def test_badan_kosong_menyimpan_mati(app):
    support = _masuk(app, SUPPORT)
    support.post(RUTE, json={"aktif": True})
    assert support.post(RUTE, json={}).json() == {"aktif": False}


def test_bentuk_salah_ditolak_400(app):
    r = _masuk(app, SUPPORT).post(RUTE, json={"aktif": "ya"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "input_tidak_sah"


def test_operator_ditolak_dan_setelan_tidak_berubah(app):
    operator = _masuk(app, OPERATOR)
    for r in (operator.get(RUTE), operator.post(RUTE, json={"aktif": True})):
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "bukan_support"
    assert _masuk(app, SUPPORT).get(RUTE).json() == {"aktif": False}
