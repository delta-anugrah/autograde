"""End-to-end: the operator console against a running AutoERP.

Real processes and real HTTP, no fakes. Skipped unless these are set:

    E2E_CONSOLE_URL          http://127.0.0.1:8100
    E2E_WEBHOOK_SECRET       the console's WEBHOOK_SECRET
    E2E_ERP_URL              http://pks.localhost:8000
    E2E_ERP_API_KEY          integration user key (create_integration_user)
    E2E_ERP_API_SECRET       integration user secret
    E2E_ERP_ADMIN_PASSWORD   Administrator password, used only to delete the test trucks

The console must point ERP_URL at the same AutoERP and run with
CONSOLE_SYNC_INTERVAL_S=5, or waiting for the pull times out.
"""
from __future__ import annotations

import os
import secrets
import time
import uuid
from datetime import UTC, datetime

import httpx
import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.plate import truck_id_for

_KEYS = (
    "E2E_CONSOLE_URL", "E2E_WEBHOOK_SECRET", "E2E_ERP_URL",
    "E2E_ERP_API_KEY", "E2E_ERP_API_SECRET", "E2E_ERP_ADMIN_PASSWORD",
)
ENV = {key: os.getenv(key, "") for key in _KEYS}
pytestmark = pytest.mark.skipif(not all(ENV.values()), reason="E2E services not configured")

SUPPLIER = "KUD Sumber Makmur"  # present in the demo dump
PULL_TIMEOUT_S = 60


@pytest.fixture(scope="module")
def erp():
    headers = {"Authorization": f"token {ENV['E2E_ERP_API_KEY']}:{ENV['E2E_ERP_API_SECRET']}"}
    with httpx.Client(base_url=ENV["E2E_ERP_URL"], headers=headers, timeout=30) as client:
        yield client


@pytest.fixture(scope="module")
def console():
    with httpx.Client(base_url=ENV["E2E_CONSOLE_URL"], timeout=15) as client:
        yield client


@pytest.fixture(scope="module")
def plates(erp):
    """Two fresh trucks made through AutoERP's own endpoint, deleted afterwards."""
    series = secrets.randbelow(9000) + 1000
    created: dict[str, str] = {}
    for role, suffix, supplier in (("owned", "TSA", SUPPLIER), ("ownerless", "TSB", None)):
        res = erp.post(
            "/api/method/erpnext.palm_mill.api.upsert_truck",
            json={"plate_number": f"BE {series} {suffix}", "supplier": supplier},
        )
        res.raise_for_status()
        created[role] = res.json()["message"]["name"]
    yield created
    _delete_trucks(created.values())


def _delete_trucks(names) -> None:
    with httpx.Client(base_url=ENV["E2E_ERP_URL"], timeout=30) as admin:
        login = {"usr": "Administrator", "pwd": ENV["E2E_ERP_ADMIN_PASSWORD"]}
        admin.post("/api/method/login", data=login).raise_for_status()
        for name in names:
            admin.delete(f"/api/resource/Truck/{name}").raise_for_status()


def _console_trucks(console) -> dict[str, dict]:
    return {t["plate_number"]: t for t in console.get("/api/console/trucks").json()["items"]}


@pytest.fixture(scope="module")
def pulled(console, plates):
    """Wait for the console's own worker to pull both trucks; nothing is triggered by hand."""
    deadline = time.monotonic() + PULL_TIMEOUT_S
    while time.monotonic() < deadline:
        trucks = _console_trucks(console)
        if all(name in trucks for name in plates.values()):
            return trucks
        time.sleep(1)
    pytest.fail(f"console did not pull {sorted(plates.values())} within {PULL_TIMEOUT_S}s")


def _secret() -> dict[str, str]:
    return {"x-webhook-secret": ENV["E2E_WEBHOOK_SECRET"]}


def test_trucks_from_autoerp_reach_the_console_with_its_source_rule(pulled, plates):
    owned, ownerless = pulled[plates["owned"]], pulled[plates["ownerless"]]

    assert (owned["supplier_name"], owned["sumber_label"], owned["status"]) == (SUPPLIER, "External", "active")
    assert (ownerless["supplier_name"], ownerless["sumber_label"], ownerless["status"]) == (None, "Internal", "active")


def test_a_graded_bunch_shows_its_trucks_source(console, pulled, plates):
    event_id = str(uuid.uuid4())
    res = console.post(
        "/api/v1/internal/vision/events",
        headers=_secret(),
        json={
            "event_id": event_id,
            "machine_id": Settings().console_lines[0].machine_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "prediction": "Acc",
            "ripeness_status": "ACC",
            "ripeness_confidence": 0.93,
            "tp_status": "PASS",
            "capture_type": "auto",
            # No image: a made-up path only makes the open console poll a 404.
            "image_path": None,
            "truck_id": truck_id_for(plates["owned"]),
            "assignment_id": None,
        },
    )
    assert res.status_code == 201, res.text

    history = console.get("/api/console/history", params={"tanggal_kerja": res.json()["tanggal_kerja"]})
    [row] = [r for r in history.json()["items"] if r["event_id"] == event_id]
    assert (row["plate_number"], row["sumber_label"]) == (plates["owned"], "External")


def test_a_weighing_shows_its_trucks_source(console, pulled, plates):
    res = console.post(
        "/api/v1/internal/scale/weighing",
        headers=_secret(),
        json={
            "ref": f"E2E-{uuid.uuid4().hex[:8]}",
            "plate_number": plates["ownerless"],
            "waktu_masuk": datetime.now(UTC).isoformat(),
            "bruto_kg": 14560,
            "tara_kg": 5400,
        },
    )
    assert res.status_code == 201, res.text
    ticket = res.json()

    weighings = console.get("/api/console/weighings", params={"tanggal_kerja": ticket["tanggal_kerja"]})
    [row] = [w for w in weighings.json()["items"] if w["id"] == ticket["id"]]
    assert (row["neto_kg"], row["sumber_label"]) == (9160, "Internal")


# Last on purpose: on a build with the bug it wipes the owned truck's supplier.
@pytest.mark.xfail(strict=True, reason="known bug: retyping a linked plate wipes its owner (fixed on feat/erp-outbox)")
def test_retyping_a_plate_autoerp_owns_keeps_its_owner(console, pulled, plates):
    res = console.post("/api/console/trucks", json={"plate_number": plates["owned"]})
    assert res.status_code == 201, res.text

    owned = _console_trucks(console)[plates["owned"]]
    assert (owned["supplier_name"], owned["sumber_label"]) == (SUPPLIER, "External")
