"""End-to-end layar Akun: semuanya lewat HTTP, seperti yang dialami di layar.

Login sungguhan (cookie sesi), salah sandi lewat rute login yang sama dengan
gerbang, lalu tab Akun membaca hasilnya. Rute dirakit lewat dependency graph
yang asli dengan dependensi di-override — bukan `create_console_app()`, yang
menyentuh `state/*.db` milik developer.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.domain.operator_auth import hash_password
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.console import get_auth_service, get_console_service, get_dev_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.dev_service import DevService

SANDI = "sandi-e2e-akun"


class _StubConsole:
    def __init__(self, store: ConsoleStore) -> None:
        self.store = store


@pytest.fixture
def app(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    aplikasi = FastAPI()
    aplikasi.include_router(console_router)
    aplikasi.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    aplikasi.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    aplikasi.dependency_overrides[get_dev_service] = lambda: DevService(
        LogStore(tmp_path / "log.db"), console_store=store
    )
    for email, role in (("support@pks.test", "support"), ("operator@pks.test", "operator")):
        store.upsert_operator_manual(
            {"email": email, "full_name": email.split("@")[0], "password_hash": hash_password(SANDI)}
        )
        store.set_role(store.operator_by_email(email)["id"], role)
    return aplikasi


def _masuk(aplikasi, email: str) -> TestClient:
    client = TestClient(aplikasi)
    res = client.post("/api/console/login", json={"email": email, "sandi": SANDI})
    assert res.status_code == 200, res.text
    return client


def test_operator_tidak_bisa_membuka_tab_akun(app):
    assert TestClient(app).get("/api/console/dev/akun").status_code == 401
    assert _masuk(app, "operator@pks.test").get("/api/console/dev/akun").status_code == 403


def test_salah_sandi_di_gerbang_terbaca_terkunci_di_tab_akun(app):
    gerbang = TestClient(app)
    for _ in range(5):
        res = gerbang.post(
            "/api/console/login", json={"email": "operator@pks.test", "sandi": "bukan-sandinya"}
        )
        assert res.status_code in (401, 429)

    support = _masuk(app, "support@pks.test")
    res = support.get("/api/console/dev/akun")

    assert res.status_code == 200
    akun = {a["email"]: a for a in res.json()["akun"]}
    assert akun["operator@pks.test"]["keadaan"] == "terkunci"
    assert akun["support@pks.test"]["keadaan"] == "aktif"
    assert akun["support@pks.test"]["sedang_masuk"] is True
    assert "password_hash" not in res.text
    assert "scrypt$" not in res.text


def test_logout_terbaca_tidak_lagi_masuk(app):
    operator = _masuk(app, "operator@pks.test")
    operator.post("/api/console/logout")

    support = _masuk(app, "support@pks.test")
    akun = {a["email"]: a for a in support.get("/api/console/dev/akun").json()["akun"]}

    assert akun["operator@pks.test"]["sedang_masuk"] is False
