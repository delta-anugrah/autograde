"""End-to-end: `require_support` in front of `/api/console/dev/*`, on a real
console app, over real HTTP.

Unit tests cover the guard function directly and route tests use a stub
console; neither exercises the wiring — a real session cookie from a real
login, and a role read from the same store the rest of the console uses.

Assembled here rather than through `create_console_app()`, which would reach
for the developer's own `state/console.db` and leave test rows in it.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.operator_error import BELUM_MASUK, BUKAN_SUPPORT
from palmgrade.domain.peran import ROLE_OPERATOR, ROLE_SUPPORT
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService

SANDI = "sokongan2026"


class _StubConsole:
    """The dev lane and `/me` touch no console service; only the store is shared."""

    def __init__(self, store: ConsoleStore) -> None:
        self.store = store


@pytest.fixture
def gerbang(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual(
        {
            "email": "operator@pks.test",
            "full_name": "Operator Biasa",
            "password_hash": hash_password(SANDI),
            "peran": ROLE_OPERATOR,
        }
    )
    store.upsert_operator_manual(
        {
            "email": "support@pks.test",
            "full_name": "Akun Support",
            "password_hash": hash_password(SANDI),
            "peran": ROLE_SUPPORT,
        }
    )

    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    return TestClient(app), store


def _masuk(client: TestClient, email: str) -> None:
    assert client.post(
        "/api/console/login", json={"email": email, "sandi": SANDI}
    ).status_code == 200


def test_operator_ditolak_dari_lane_dev(gerbang):
    """A plain `operator` account gets 403 off a developer lane, not the page."""
    client, _ = gerbang
    _masuk(client, "operator@pks.test")

    jawab = client.get("/api/console/dev/ping")

    assert jawab.status_code == 403
    assert jawab.json()["detail"]["code"] == BUKAN_SUPPORT


def test_support_masuk_lane_dev(gerbang):
    """A `support` account is let through to the same lane."""
    client, _ = gerbang
    _masuk(client, "support@pks.test")

    jawab = client.get("/api/console/dev/ping")

    assert jawab.status_code == 200
    assert jawab.json() == {"status": "ok"}


def test_tanpa_sesi_dijawab_401_bukan_403(gerbang):
    """No cookie must read as "sign in again", never as "wrong role" — the
    session gate has to run before the role gate."""
    client, _ = gerbang

    jawab = client.get("/api/console/dev/ping")

    assert jawab.status_code == 401
    assert jawab.json()["detail"]["code"] == BELUM_MASUK


def test_me_membawa_peran_untuk_kedua_akun(gerbang):
    """`role` has to reach the screen so it can hide the developer tab."""
    client, _ = gerbang

    _masuk(client, "operator@pks.test")
    assert client.get("/api/console/me").json()["operator"]["role"] == ROLE_OPERATOR

    client.post("/api/console/logout")
    _masuk(client, "support@pks.test")
    assert client.get("/api/console/me").json()["operator"]["role"] == ROLE_SUPPORT


def test_peran_dicabut_ditolak_pada_sesi_lama(gerbang):
    """The important case: demote a support account mid-session, on the exact
    token it already holds. If the guard ever cached the role at login instead
    of reading it live, this stays 200 and the regression goes unnoticed."""
    client, store = gerbang
    _masuk(client, "support@pks.test")
    assert client.get("/api/console/dev/ping").status_code == 200

    operator_id = client.get("/api/console/me").json()["operator"]["id"]
    store.set_role(operator_id, ROLE_OPERATOR)

    jawab = client.get("/api/console/dev/ping")

    assert jawab.status_code == 403
    assert jawab.json()["detail"]["code"] == BUKAN_SUPPORT
