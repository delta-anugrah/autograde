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

from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.operator_error import (
    BELUM_MASUK,
    BUKAN_PLAT,
    BUKAN_SUPPORT,
    SANDI_SALAH,
)
from palmgrade.domain.plate import truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import (
    get_auth_service,
    get_console_service,
    get_scan_service,
)
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.scan_service import ScanService

EMAIL = "budi@pks.test"
NAMA = "Pak Budi"
SANDI = "sawit2026"


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
    store.upsert_operator_manual(
        {"email": EMAIL, "full_name": NAMA, "password_hash": hash_password(SANDI)}
    )
    auth = AuthService(store)
    stub = _StubConsole()

    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: stub
    app.dependency_overrides[get_auth_service] = lambda: auth
    # Scanning reads trucks from the same store. The stub has none, so this is the
    # real service on the test database rather than a third fake to keep in step.
    app.dependency_overrides[get_scan_service] = lambda: ScanService(store)
    return TestClient(app), store, stub


def _sign_in(client: TestClient, sandi: str = SANDI, email: str = EMAIL):
    return client.post("/api/console/login", json={"email": email, "sandi": sandi})


def test_the_screen_data_is_refused_without_a_session(console):
    client, _, _ = console

    response = client.get("/api/console/state")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == BELUM_MASUK


def test_the_right_password_opens_every_lane(console):
    client, _, _ = console

    assert _sign_in(client).status_code == 200
    assert client.get("/api/console/state").status_code == 200
    assert client.get("/api/console/me").json()["operator"]["full_name"] == NAMA


def test_the_session_cookie_cannot_be_read_by_a_script_on_the_page(console):
    """A console tab left open all shift is the likeliest place a token leaks from."""
    client, _, _ = console

    cookie = _sign_in(client).headers["set-cookie"].lower()

    assert "httponly" in cookie
    assert "samesite=strict" in cookie


def test_a_wrong_password_hands_out_no_session(console):
    client, _, _ = console

    response = _sign_in(client, sandi="sawit2027")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == SANDI_SALAH
    assert "set-cookie" not in response.headers
    assert client.get("/api/console/state").status_code == 401


def test_signing_out_shuts_the_lanes_again(console):
    client, _, _ = console
    _sign_in(client)

    assert client.post("/api/console/logout").status_code == 200
    assert client.get("/api/console/state").status_code == 401


def test_the_screen_can_read_the_account_list_before_anyone_is_in(console):
    """The gate fills the email field from it on a touchscreen where typing one is slow,
    so this one lane stays open — emails and names only, never a hash."""
    client, _, _ = console

    response = client.get("/api/console/operators")

    assert response.status_code == 200
    assert [item["email"] for item in response.json()["items"]] == [EMAIL]
    assert all("password_hash" not in item for item in response.json()["items"])


def test_a_manual_reject_is_recorded_against_whoever_is_signed_in(console):
    """It used to be the literal string "operator" from the request body, which made the
    one operator action with a name on it anonymous."""
    client, _, stub = console
    _sign_in(client)

    client.post("/api/console/lines/line-1/manual-reject", json={"requested_by": "siapa saja"})

    assert stub.rejected_by == NAMA


# ── scan QR (2026-09-15) ──────────────────────────────────────────────────────


def test_scan_butuh_sesi_seperti_lane_operator_lain(console):
    """Hasil scan menyebut truk siapa yang datang. Itu data operasional pabrik, jadi
    lane-nya ikut di belakang gerbang seperti yang lain."""
    client, _, _ = console

    response = client.post("/api/console/scan", json={"qr": "BE4412OFL"})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == BELUM_MASUK


def test_scan_truk_terdaftar_dijawab_dengan_truknya(console):
    client, store, _ = console
    _sign_in(client)
    store.upsert_truck(
        {"id": truck_id_for("BE 4412 OFL"), "plate_number": "BE 4412 OFL", "status": "active"}
    )

    response = client.post("/api/console/scan", json={"qr": "BE4412OFL"})

    assert response.status_code == 200
    assert response.json()["ditemukan"] is True
    assert response.json()["truck"]["plate_number"] == "BE 4412 OFL"


def test_scan_truk_pinjaman_dijawab_belum_ada_bukan_error(console):
    """Truk pinjaman itu alasan fitur ini ada. 404 akan terbaca seperti kerusakan,
    padahal jawabannya normal: layar menawarkan input manual."""
    client, _, _ = console
    _sign_in(client)

    response = client.post("/api/console/scan", json={"qr": "BE9999XYZ"})

    assert response.status_code == 200
    assert response.json()["ditemukan"] is False
    assert response.json()["plate_number"] == "BE9999XYZ"


def test_scan_yang_bukan_plat_ditolak_400(console):
    """Struk parkir atau QR promo yang kebetulan ke-scan tidak boleh jadi truk."""
    client, _, _ = console
    _sign_in(client)

    response = client.post("/api/console/scan", json={"qr": "https://contoh.id/promo"})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == BUKAN_PLAT


# ── developer lane: require_support (2026-09-15) ──────────────────────────────


def test_lane_support_menolak_operator_biasa(console):
    """The backend enforces this, not just a hidden tab."""
    client, _, _ = console
    _sign_in(client)

    response = client.get("/api/console/dev/ping")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == BUKAN_SUPPORT


def test_lane_support_menerima_akun_support(console):
    client, store, _ = console
    oid = store.upsert_operator_manual(
        {"email": "s@b.c", "full_name": "S", "password_hash": hash_password(SANDI)}
    )
    store.set_role(oid, "support")

    _sign_in(client, email="s@b.c")
    response = client.get("/api/console/dev/ping")

    assert response.status_code == 200


def test_lane_support_tanpa_sesi_tetap_401(console):
    """Not signed in answers 401, not 403 — the screen shows the difference."""
    client, _, _ = console

    response = client.get("/api/console/dev/ping")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == BELUM_MASUK


def test_me_membawa_peran(console):
    client, store, _ = console
    oid = store.upsert_operator_manual(
        {"email": "s@b.c", "full_name": "S", "password_hash": hash_password(SANDI)}
    )
    store.set_role(oid, "support")

    _sign_in(client, email="s@b.c")
    response = client.get("/api/console/me")

    assert response.json()["operator"]["role"] == "support"
