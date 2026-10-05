"""Integration (batch 5.7): a session that slides with the operator's activity.

Real routes, real SQLite, a clock the test moves. The screen's polls do not slide the
session; only `POST /api/console/session/renew`, which the screen sends when the operator
touched it, does. The cookie is sent again with a fresh lifetime, or the browser would
drop it at the old end while the server still holds the session.
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import SESSION_TTL_S, hash_password
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service, get_dev_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService

SANDI = "sandi-integrasi-sesi"
JAM = 60 * 60


class _Dev:
    async def license_state(self) -> dict:
        return {}

    def app_version(self) -> str:
        return "v-integrasi"


@pytest.fixture
def rakitan(tmp_path):
    settings = replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta")
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual(
        {"email": "operator@pks.test", "full_name": "Operator", "password_hash": hash_password(SANDI)}
    )
    jam = [1_000_000.0]
    auth = AuthService(store, now=lambda: jam[0])
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: ConsoleService(settings, store, line_client=None)
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_dev_service] = lambda: _Dev()
    klien = TestClient(app)
    masuk = klien.post("/api/console/login", json={"email": "operator@pks.test", "sandi": SANDI})
    assert masuk.status_code == 200, masuk.text
    return klien, jam, masuk


def test_sign_in_and_me_say_how_long_the_session_has_left(rakitan):
    klien, jam, masuk = rakitan
    assert masuk.json()["sisa_detik"] == SESSION_TTL_S
    jam[0] += 2 * JAM

    assert klien.get("/api/console/me").json()["sisa_detik"] == SESSION_TTL_S - 2 * JAM


def test_renew_slides_the_session_and_sends_the_cookie_again(rakitan):
    klien, jam, _ = rakitan
    jam[0] += 11 * JAM

    jawab = klien.post("/api/console/session/renew")

    assert jawab.status_code == 200, jawab.text
    assert jawab.json() == {"sisa_detik": SESSION_TTL_S}
    assert f"Max-Age={SESSION_TTL_S}" in jawab.headers["set-cookie"]
    jam[0] += 11 * JAM
    assert klien.get("/api/console/me").status_code == 200, "22 h after sign-in, still in"


def test_polls_alone_do_not_keep_a_session_alive(rakitan):
    klien, jam, _ = rakitan
    for _ in range(12):
        jam[0] += JAM - 1
        assert klien.get("/api/console/me").status_code == 200
    jam[0] += 13

    assert klien.get("/api/console/me").status_code == 401


def test_a_renew_after_the_end_is_refused_with_the_sign_in_code(rakitan):
    klien, jam, _ = rakitan
    jam[0] += SESSION_TTL_S + 1

    jawab = klien.post("/api/console/session/renew")

    assert jawab.status_code == 401
    assert jawab.json()["detail"]["code"] == "belum_masuk"
