"""Operator route bodies are Pydantic models; their content rules stay in the domain.

The models only fix the shape: which fields, and which JSON types. Whatever the domain
already rejects with its own code (`bukan_plat`, `bukan_angka`, a wrong password) keeps that
code, because the screen words each one differently. A body of the wrong shape gets one
code of its own, `input_tidak_sah`, with 400 like every other operator refusal.

The weighing body keeps its figures as text: the screen sends `"14820,5"` from an Indonesian
keypad and `_kg` reads the comma. A float field would refuse exactly that.

The four support setting routes and the machine lane keep a dict on purpose (standard B1):
their domain parsers accept `"8"` for 8 and ignore fields from a newer screen, and the lines
on the factory floor send a frozen contract.

Built on a bare app, never `create_console_app()` (it opens the developer's console.db).
"""

from __future__ import annotations

import inspect
import typing

import pytest
from fastapi import FastAPI
from fastapi.params import Body
from fastapi.testclient import TestClient

from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.operator_error import BUKAN_PLAT, INPUT_TIDAK_SAH, SANDI_SALAH
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import (
    get_auth_service,
    get_console_service,
    get_scan_service,
    require_operator,
)
from palmgrade.routes.console import router as console_router
from palmgrade.routes.console_deps import pasang_penangan_validasi
from palmgrade.routes.console_ingest import ingest_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.scan_service import ScanService

EMAIL = "budi@pks.test"
SANDI = "sawit2026"

# Routes that keep `Annotated[dict, Body()]` on purpose, each with a domain parser
# (`bersihkan_setelan`, `bersihkan_setelan_rekam`, `bersihkan_sumber`, `bersihkan_pilihan_model`).
DICT_ON_PURPOSE = {
    "dev_setelan_simpan",
    "dev_rekam_setelan",
    "dev_sumber_kamera_simpan",
    "dev_model_deteksi_simpan",
}


class _StubConsole:
    """Records what the routes hand the service; nothing else is under test."""

    def __init__(self) -> None:
        self.weighing: dict | None = None
        self.truck: tuple | None = None

    async def record_weighing(self, payload: dict) -> dict:
        self.weighing = payload
        return {"id": "w1"}

    def register_manual_truck(self, plate_number, *, supplier_id=None, capacity=None) -> dict:
        self.truck = (plate_number, supplier_id, capacity)
        return {"plate_number": plate_number}


@pytest.fixture
def console(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual({"email": EMAIL, "full_name": "Pak Budi", "password_hash": hash_password(SANDI)})
    stub = _StubConsole()
    app = FastAPI()
    app.include_router(console_router)
    app.include_router(ingest_router, prefix="/api/v1")  # as console_main mounts it
    pasang_penangan_validasi(app)
    app.dependency_overrides[get_console_service] = lambda: stub
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_scan_service] = lambda: ScanService(store)
    app.dependency_overrides[require_operator] = lambda: {"email": EMAIL, "role": "operator"}
    return TestClient(app), stub


def _code(response) -> str:
    return response.json()["detail"]["code"]


# ── a body of the right shape behaves exactly as before ────────────────────


def test_login_still_signs_in(console):
    client, _ = console
    assert client.post("/api/console/login", json={"email": EMAIL, "sandi": SANDI}).status_code == 200


def test_a_missing_password_is_still_the_domain_refusal(console):
    client, _ = console
    response = client.post("/api/console/login", json={"email": EMAIL})
    assert response.status_code == 401
    assert _code(response) == SANDI_SALAH


def test_a_scan_that_is_not_a_plate_keeps_its_own_code(console):
    client, _ = console
    response = client.post("/api/console/scan", json={"qr": "https://promo.example"})
    assert response.status_code == 400
    assert _code(response) == BUKAN_PLAT


def test_the_weighing_reaches_the_service_as_sent_with_its_comma(console):
    client, stub = console
    body = {"plate_number": "BE 1234 AB", "gross_kg": "14820,5", "entered_at": "2026-09-30T08:00:00Z"}
    assert client.post("/api/console/weighings", json=body).status_code == 201
    # Only what was sent: an absent tare must stay absent, or weigh-out would overwrite it.
    assert stub.weighing == body


def test_a_manual_truck_passes_its_fields_through(console):
    client, stub = console
    body = {"plate_number": "BE 1234 AB", "supplier_id": "s1", "capacity": "8000"}
    assert client.post("/api/console/trucks", json=body).status_code == 201
    assert stub.truck == ("BE 1234 AB", "s1", "8000")


# ── a body of the wrong shape is refused at the door, in the screen's terms ──


@pytest.mark.parametrize(
    ("path", "body", "field"),
    [
        ("/api/console/scan", {"qr": 123}, "qr"),
        ("/api/console/scan/keluar", {"qr": ["BE 1234 AB"]}, "qr"),
        ("/api/console/login", {"email": ["x"], "sandi": SANDI}, "email"),
        ("/api/console/trucks", {"plate_number": {"a": 1}}, "plate_number"),
        ("/api/console/weighings", {"plate_number": "BE 1234 AB", "gross_kg": {"kg": 1}}, "gross_kg"),
    ],
)
def test_a_wrong_shape_is_400_input_tidak_sah(console, path, body, field):
    client, _ = console
    response = client.post(path, json=body)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == INPUT_TIDAK_SAH
    assert response.json()["detail"]["params"]["field"] == field


def test_a_body_that_is_not_an_object_is_400_input_tidak_sah(console):
    client, _ = console
    response = client.post("/api/console/scan", json=["BE 1234 AB"])
    assert response.status_code == 400
    assert _code(response) == INPUT_TIDAK_SAH
    # "body" has its own KAMUS label, so the screen never shows a raw API name here.
    assert response.json()["detail"]["params"]["field"] == "body"


def test_the_machine_lane_keeps_the_default_answer(console):
    # The lines' outbox reads this lane; its answers must not change shape.
    client, _ = console
    response = client.post("/api/v1/internal/vision/events", json=["not", "an", "event"])
    assert response.status_code == 422


# ── the rule itself (standard B1) ───────────────────────────────────────────


def _takes_a_dict_body(endpoint) -> bool:
    for hint in typing.get_type_hints(endpoint, include_extras=True).values():
        if typing.get_origin(hint) is typing.Annotated:
            base, *extras = typing.get_args(hint)
            if base is dict and any(isinstance(e, Body) for e in extras):
                return True
    return False


def test_only_the_support_setting_routes_take_a_dict_body():
    takers = {
        route.endpoint.__name__
        for route in console_router.routes
        if inspect.isfunction(getattr(route, "endpoint", None)) and _takes_a_dict_body(route.endpoint)
    }
    assert takers == DICT_ON_PURPOSE
