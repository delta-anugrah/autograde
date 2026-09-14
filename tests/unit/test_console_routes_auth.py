"""The console API is shut until someone signs in (Fase 4, plan §6.5).

Built on a bare app with the console router and both dependencies overridden — not on
`create_console_app()`, which would reach for the real `state/console.db` and leave test
rows in a developer's console.

What matters here is the wiring rather than the rules (those are in
`test_operator_login.py`): every operator lane refuses a request without a session, the
cookie that carries it cannot be read by scripts on the page, and signing out shuts the
lane again.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.domain.operator_auth import hash_pin, operator_id_for
from palmgrade.domain.operator_error import BELUM_MASUK, PIN_SALAH
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService

NAMA = "Pak Budi"
PIN = "142536"


class _StubConsole:
    """Only what the routes under test call. The real service needs a line client and
    settings, and none of that is what these tests are about."""

    def __init__(self) -> None:
        self.rejected_by: str | None = None

    def state(self) -> dict:
        return {"hari_ini": {}, "lines": []}

    async def manual_reject(self, line_code: str, requested_by: str) -> dict:
        self.rejected_by = requested_by
        return {"line_code": line_code, "requested_by": requested_by}


@pytest.fixture
def console(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator({"nama": NAMA, "pin_hash": hash_pin(PIN)})
    auth = AuthService(store)
    stub = _StubConsole()

    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: stub
    app.dependency_overrides[get_auth_service] = lambda: auth
    return TestClient(app), store, stub


def _sign_in(client: TestClient, pin: str = PIN):
    return client.post(
        "/api/console/login", json={"operator_id": operator_id_for(NAMA), "pin": pin}
    )


def test_the_screen_data_is_refused_without_a_session(console):
    client, _, _ = console

    response = client.get("/api/console/state")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == BELUM_MASUK


def test_the_right_pin_opens_every_lane(console):
    client, _, _ = console

    assert _sign_in(client).status_code == 200
    assert client.get("/api/console/state").status_code == 200
    assert client.get("/api/console/me").json()["operator"]["nama"] == NAMA


def test_the_session_cookie_cannot_be_read_by_a_script_on_the_page(console):
    """A console tab left open all shift is the likeliest place a token leaks from."""
    client, _, _ = console

    cookie = _sign_in(client).headers["set-cookie"].lower()

    assert "httponly" in cookie
    assert "samesite=strict" in cookie


def test_a_wrong_pin_hands_out_no_session(console):
    client, _, _ = console

    response = _sign_in(client, pin="998877")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == PIN_SALAH
    assert "set-cookie" not in response.headers
    assert client.get("/api/console/state").status_code == 401


def test_signing_out_shuts_the_lanes_again(console):
    client, _, _ = console
    _sign_in(client)

    assert client.post("/api/console/logout").status_code == 200
    assert client.get("/api/console/state").status_code == 401


def test_the_keypad_can_read_the_operator_list_before_anyone_is_in(console):
    """The gate has to draw the names it offers, so this one lane stays open — names
    and ids only, never a hash."""
    client, _, _ = console

    response = client.get("/api/console/operators")

    assert response.status_code == 200
    assert [item["nama"] for item in response.json()["items"]] == [NAMA]
    assert all("pin_hash" not in item for item in response.json()["items"])


def test_a_manual_reject_is_recorded_against_whoever_is_signed_in(console):
    """It used to be the literal string "operator" from the request body, which made the
    one operator action with a name on it anonymous."""
    client, _, stub = console
    _sign_in(client)

    client.post("/api/console/lines/line-1/manual-reject", json={"requested_by": "siapa saja"})

    assert stub.rejected_by == NAMA
