"""End-to-end: `GET /api/console/dev/log` on a real console app, over real HTTP.

Unit tests cover `DevService` and the route with a stub console; neither
exercises the full wiring - a real session cookie from a real login, a role
read from the same store the rest of the console uses, and `get_dev_service`
resolving to a real `LogStore` through the actual dependency graph.

Assembled here rather than through `create_console_app()`, which would reach
for the developer's own `state/*.db` and leave test rows in it.
"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.operator_error import BUKAN_SUPPORT
from palmgrade.domain.peran import PERAN_OPERATOR, PERAN_SUPPORT
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.console import get_auth_service, get_console_service, get_dev_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.dev_service import DevService

SANDI = "sokongan2026"


class _StubConsole:
    """The dev lane touches no console service; only the store is shared."""

    def __init__(self, store: ConsoleStore) -> None:
        self.store = store


@pytest.fixture
def gerbang(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    log_store = LogStore(tmp_path / "log.db")
    store.upsert_operator_lokal(
        {
            "email": "operator@pks.test",
            "nama": "Operator Biasa",
            "password_hash": hash_password(SANDI),
            "peran": PERAN_OPERATOR,
        }
    )
    store.upsert_operator_lokal(
        {
            "email": "support@pks.test",
            "nama": "Akun Support",
            "password_hash": hash_password(SANDI),
            "peran": PERAN_SUPPORT,
        }
    )

    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_dev_service] = lambda: DevService(log_store)
    return TestClient(app), store, log_store


def _masuk(client: TestClient, email: str) -> None:
    assert client.post(
        "/api/console/login", json={"email": email, "sandi": SANDI}
    ).status_code == 200


def test_support_membaca_log_dengan_total_dan_items(gerbang):
    client, _, log_store = gerbang
    log_store.tulis("ERROR", "line-1", "kamera putus", None, now=time.time())
    _masuk(client, "support@pks.test")

    jawab = client.get("/api/console/dev/log")

    assert jawab.status_code == 200
    data = jawab.json()
    assert data["total"] == 1
    assert data["items"][0]["pesan"] == "kamera putus"


def test_operator_biasa_ditolak_403(gerbang):
    client, _, log_store = gerbang
    log_store.tulis("ERROR", "line-1", "kamera putus", None, now=time.time())
    _masuk(client, "operator@pks.test")

    jawab = client.get("/api/console/dev/log")

    assert jawab.status_code == 403
    assert jawab.json()["detail"]["code"] == BUKAN_SUPPORT


def test_halaman_terakhir_membawa_total_yang_benar(gerbang):
    """The same pagination trap that bit the grading screen before: `total`
    has to come from the response, not from how many rows the last page
    happens to hold."""
    client, _, log_store = gerbang
    dasar = time.time()
    for i in range(23):
        log_store.tulis("ERROR", f"s{i}", f"pesan {i}", None, now=dasar + i)
    _masuk(client, "support@pks.test")

    halaman_pertama = client.get("/api/console/dev/log?limit=20&offset=0").json()
    halaman_terakhir = client.get("/api/console/dev/log?limit=20&offset=20").json()

    assert halaman_pertama["total"] == 23
    assert len(halaman_pertama["items"]) == 20
    assert halaman_terakhir["total"] == 23
    assert len(halaman_terakhir["items"]) == 3


def test_saring_level_bekerja_lewat_http(gerbang):
    client, _, log_store = gerbang
    dasar = time.time()
    log_store.tulis("ERROR", "a", "galat berat", None, now=dasar)
    log_store.tulis("WARNING", "b", "peringatan", None, now=dasar + 1)
    _masuk(client, "support@pks.test")

    hanya_error = client.get("/api/console/dev/log?level=ERROR").json()
    hanya_warning = client.get("/api/console/dev/log?level=WARNING").json()

    assert hanya_error["total"] == 1
    assert hanya_error["items"][0]["level"] == "ERROR"
    assert hanya_warning["total"] == 1
    assert hanya_warning["items"][0]["level"] == "WARNING"
