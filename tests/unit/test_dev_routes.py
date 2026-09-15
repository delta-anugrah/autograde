"""`/api/console/dev/log` — support-only, paginated, level-filtered.

Built the same way as `test_console_routes_auth.py`: a bare app with the
console router, `get_console_service`/`get_auth_service` overridden onto a
real store on `tmp_path`, and `get_dev_service` overridden onto a `DevService`
wrapping its own `LogStore` — never `create_console_app()`, which would touch
a developer's real `state/*.db`.
"""

from __future__ import annotations

import time

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

SANDI = "pendukung2026"


class _StubConsole:
    """The dev lane touches no console service; only the store is shared."""

    def __init__(self, store: ConsoleStore) -> None:
        self.store = store


def _app_dev(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    log_store = LogStore(tmp_path / "log.db")

    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_dev_service] = lambda: DevService(log_store)
    return app, store, log_store


def _client_support(app, store) -> TestClient:
    store.upsert_operator_lokal(
        {"email": "s@b.c", "nama": "Support", "password_hash": hash_password(SANDI)}
    )
    store.set_peran(store.operator_by_email("s@b.c")["id"], "support")
    client = TestClient(app)
    assert client.post(
        "/api/console/login", json={"email": "s@b.c", "sandi": SANDI}
    ).status_code == 200
    return client


@pytest.fixture
def dev(tmp_path):
    return _app_dev(tmp_path)


def test_log_butuh_peran_support(dev):
    app, store, _ = dev
    store.upsert_operator_lokal(
        {"email": "o@b.c", "nama": "O", "password_hash": hash_password(SANDI)}
    )
    client = TestClient(app)
    client.post("/api/console/login", json={"email": "o@b.c", "sandi": SANDI})

    assert client.get("/api/console/dev/log").status_code == 403


def test_log_tanpa_sesi_401(dev):
    app, _, _ = dev
    client = TestClient(app)

    response = client.get("/api/console/dev/log")

    assert response.status_code == 401


def test_log_mengembalikan_halaman_dan_total(dev):
    app, store, log_store = dev
    # Real-clock timestamps: DevService's own hourly purge (below) compares
    # against wall-clock time.time(), so a fixed-epoch stub like 1000.0 would
    # read as 180 days expired and vanish before the assertion runs.
    dasar = time.time()
    for i in range(25):
        log_store.tulis("ERROR", f"s{i}", f"pesan {i}", None, now=dasar + i)
    client = _client_support(app, store)

    data = client.get("/api/console/dev/log?limit=10").json()

    assert data["total"] == 25
    assert len(data["items"]) == 10


def test_log_saring_level(dev):
    app, store, log_store = dev
    dasar = time.time()
    log_store.tulis("ERROR", "a", "satu", None, now=dasar)
    log_store.tulis("WARNING", "b", "dua", None, now=dasar + 1)
    client = _client_support(app, store)

    assert client.get("/api/console/dev/log?level=ERROR").json()["total"] == 1


def test_log_limit_dibatasi_atas(dev):
    """Satu permintaan tidak boleh menarik 180 hari riwayat sekaligus."""
    app, store, _ = dev
    client = _client_support(app, store)

    assert client.get("/api/console/dev/log?limit=99999").status_code == 422


def test_log_offset_tidak_boleh_negatif(dev):
    app, store, _ = dev
    client = _client_support(app, store)

    assert client.get("/api/console/dev/log?offset=-1").status_code == 422


def test_log_cari_menyaring_pesan(dev):
    app, store, log_store = dev
    dasar = time.time()
    log_store.tulis("ERROR", "a", "kamera putus", None, now=dasar)
    log_store.tulis("ERROR", "b", "antrean penuh", None, now=dasar + 1)
    client = _client_support(app, store)

    assert client.get("/api/console/dev/log?cari=kamera").json()["total"] == 1
