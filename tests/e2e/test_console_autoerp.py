"""End-to-end: the operator console against a running AutoERP.

Real processes and real HTTP, no fakes. Skipped unless these are set:

    E2E_CONSOLE_URL          http://127.0.0.1:8100
    E2E_WEBHOOK_SECRET       the console's WEBHOOK_SECRET
    E2E_ERP_URL              http://pks.localhost:8000
    E2E_ERP_API_KEY          integration user key (create_integration_user)
    E2E_ERP_API_SECRET       integration user secret
    E2E_ERP_ADMIN_PASSWORD   Administrator password, used only to delete the test trucks
    E2E_EMAIL                console operator email, made once with `make operator`
    E2E_SANDI                that operator's password (the console API needs a session, Fase 4)

The console must point ERP_URL at the same AutoERP and run with
CONSOLE_SYNC_INTERVAL_S=5, or waiting for the pull times out.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.plate import truck_id_for

_KEYS = (
    "E2E_CONSOLE_URL", "E2E_WEBHOOK_SECRET", "E2E_ERP_URL",
    "E2E_ERP_API_KEY", "E2E_ERP_API_SECRET", "E2E_ERP_ADMIN_PASSWORD",
    "E2E_EMAIL", "E2E_SANDI",
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
        _sign_in(client)
        yield client


def _sign_in(client: httpx.Client) -> None:
    """The console API is shut until someone signs in (Fase 4). The operator is made once
    with `make operator`; the suite never creates accounts on a console itself.

    No lookup first: the email is the account, so sign-in needs nothing the caller does
    not already have.
    """
    client.post(
        "/api/console/login",
        json={"email": ENV["E2E_EMAIL"], "sandi": ENV["E2E_SANDI"]},
    ).raise_for_status()


def test_the_console_api_is_shut_without_a_session():
    """Over real HTTP, not a test client: a fresh browser gets the gate's lanes and
    nothing else."""
    with httpx.Client(base_url=ENV["E2E_CONSOLE_URL"], timeout=15) as anonymous:
        assert anonymous.get("/api/console/operators").status_code == 200
        for path in ("/api/console/state", "/api/console/trucks", "/api/console/weighings"):
            assert anonymous.get(path).status_code == 401, path


def test_a_signed_in_console_reads_and_signing_out_shuts_it_again():
    with httpx.Client(base_url=ENV["E2E_CONSOLE_URL"], timeout=15) as client:
        _sign_in(client)
        assert client.get("/api/console/state").status_code == 200
        assert client.get("/api/console/me").json()["operator"]["nama"]

        client.post("/api/console/logout").raise_for_status()
        assert client.get("/api/console/state").status_code == 401


@pytest.fixture(scope="module")
def cleanup():
    """One teardown for everything this module makes in AutoERP, in the order
    AutoERP allows: a truck cannot be deleted while a ticket still points at it.

    Tickets are found by their scale number rather than remembered, because
    AutoERP adopts a truck's open ticket inside its matching window — one visit
    can land on a ticket another test made.
    """
    plates: list[str] = []
    yield plates
    with httpx.Client(base_url=ENV["E2E_ERP_URL"], timeout=30) as admin:
        login = {"usr": "Administrator", "pwd": ENV["E2E_ERP_ADMIN_PASSWORD"]}
        admin.post("/api/method/login", data=login).raise_for_status()
        _delete_e2e_tickets(admin)
        for plate in plates:
            admin.delete(f"/api/resource/Truck/{plate}")


def _delete_e2e_tickets(admin: httpx.Client) -> None:
    found = admin.get(
        "/api/resource/Weighbridge Ticket",
        params={
            "filters": json.dumps([["scale_ticket_no", "like", "E2E-%"]]),
            "fields": json.dumps(["name", "docstatus"]),
            "limit_page_length": 100,
        },
    )
    found.raise_for_status()
    for ticket in found.json()["data"]:
        if ticket["docstatus"] == 1:  # finalised: cancel before it can go
            admin.post(
                "/api/method/frappe.client.cancel",
                json={"doctype": "Weighbridge Ticket", "name": ticket["name"]},
            )
        admin.delete(f"/api/resource/Weighbridge Ticket/{ticket['name']}")


@pytest.fixture(scope="module")
def plates(erp, cleanup):
    """Two fresh trucks made through AutoERP's own endpoint."""
    series = secrets.randbelow(9000) + 1000
    created: dict[str, str] = {}
    for role, suffix, supplier in (("owned", "TSA", SUPPLIER), ("ownerless", "TSB", None)):
        res = erp.post(
            "/api/method/erpnext.palm_mill.api.upsert_truck",
            json={"plate_number": f"BE {series} {suffix}", "supplier": supplier},
        )
        res.raise_for_status()
        created[role] = res.json()["message"]["name"]
        cleanup.append(created[role])
    return created


@pytest.fixture(scope="module")
def mill_plate(cleanup):
    """A plate typed at the mill; the test never creates it in AutoERP itself."""
    plate = f"BE {secrets.randbelow(9000) + 1000} TSC"
    cleanup.append(plate)
    return plate


def _erp_trucks(erp, plate: str) -> list[dict]:
    res = erp.get(
        "/api/resource/Truck",
        params={
            "filters": json.dumps([["plate_number", "=", plate]]),
            "fields": json.dumps(["name", "source", "autograde_id"]),
        },
    )
    res.raise_for_status()
    return res.json()["data"]


def _eventually(read, message: str):
    """Poll until the two systems agree, or fail saying what never happened."""
    deadline = time.monotonic() + PULL_TIMEOUT_S
    while time.monotonic() < deadline:
        value = read()
        if value:
            return value
        time.sleep(1)
    pytest.fail(f"{message} within {PULL_TIMEOUT_S}s")


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


def test_a_truck_typed_at_the_mill_reaches_autoerp(console, erp, mill_plate):
    """Contract §4.B: an unknown plate becomes an ownerless Truck for the
    backoffice to complete, and comes back down on the next pull."""
    res = console.post("/api/console/trucks", json={"plate_number": mill_plate.lower()})
    assert res.status_code == 201, res.text

    truck = _eventually(
        lambda: next(iter(_erp_trucks(erp, mill_plate)), None),
        f"AutoERP never received {mill_plate}",
    )
    assert truck["source"] == "AutoGrade"
    assert truck["autograde_id"] == truck_id_for(mill_plate)

    adopted = _eventually(
        lambda: _console_trucks(console).get(mill_plate) if
        _console_trucks(console).get(mill_plate, {}).get("status") == "active" else None,
        f"console never adopted {mill_plate} back from AutoERP",
    )
    assert adopted["sumber_label"] == "Internal"  # ownerless until the backoffice fills it in


def test_retyping_a_plate_autoerp_owns_keeps_its_owner(console, pulled, plates):
    res = console.post("/api/console/trucks", json={"plate_number": plates["owned"]})
    assert res.status_code == 201, res.text

    owned = _console_trucks(console)[plates["owned"]]
    assert (owned["supplier_name"], owned["sumber_label"]) == (SUPPLIER, "External")


# ------------------------------------------------- the visit (contract §4.C)


@pytest.fixture(scope="module")
def fake_line():
    """Line 1, stood in for.

    The console refuses to assign a truck the line never acknowledged, so
    without a line there is no way to close an assignment — and closing one is
    what sends the grading.
    """

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802 - http.server's own naming
            # Read the body before answering: replying to an unread request
            # resets the connection, and the console reads that as "the line did
            # not answer" — which is exactly what it should do for a real line.
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST  # noqa: N815 - the console polls /health too

        def log_message(self, *_args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 8001), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield
    server.shutdown()


@pytest.fixture(scope="module")
def grading_plate(erp, cleanup):
    """A truck of its own for the grading test: a plate that already has a
    weighed-out ticket would finalise, and finalising writes to the ledger."""
    plate = f"BE {secrets.randbelow(9000) + 1000} TSD"
    erp.post(
        "/api/method/erpnext.palm_mill.api.upsert_truck", json={"plate_number": plate}
    ).raise_for_status()
    cleanup.append(plate)
    return plate


def _erp_ticket(erp, visit_id: str) -> dict | None:
    res = erp.get(
        "/api/resource/Weighbridge Ticket",
        params={
            "filters": json.dumps([["autograde_visit_id", "=", visit_id]]),
            "fields": json.dumps(
                ["name", "status", "gross_weight_kg", "scale_ticket_no",
                 "grading_total", "grading_acc", "grading_rej"]
            ),
        },
    )
    res.raise_for_status()
    return next(iter(res.json()["data"]), None)


def test_a_gate_weighing_becomes_a_weighbridge_ticket(console, erp, pulled, plates):
    reference = f"E2E-{uuid.uuid4().hex[:8]}"
    res = console.post(
        "/api/v1/internal/scale/weighing",
        headers=_secret(),
        json={
            "ref": reference,
            "plate_number": plates["owned"],
            "waktu_masuk": datetime.now(UTC).isoformat(),
            "bruto_kg": 14560,
        },
    )
    assert res.status_code == 201, res.text
    visit_id = res.json()["id"]

    ticket = _eventually(lambda: _erp_ticket(erp, visit_id), "AutoERP never received the visit")
    assert float(ticket["gross_weight_kg"]) == 14560.0
    assert ticket["scale_ticket_no"] == reference


def test_closing_the_line_assignment_sends_the_grading(console, erp, fake_line, grading_plate):
    """Three bunches: one long stalk among the accepted, one rejected."""
    plate = grading_plate
    console.post("/api/console/trucks", json={"plate_number": plate}).raise_for_status()
    visit_id = console.post(
        "/api/v1/internal/scale/weighing",
        headers=_secret(),
        json={
            "ref": f"E2E-{uuid.uuid4().hex[:8]}",
            "plate_number": plate,
            "waktu_masuk": datetime.now(UTC).isoformat(),
            "bruto_kg": 15200,
        },
    ).json()["id"]
    _eventually(lambda: _erp_ticket(erp, visit_id), "the visit never arrived")

    assigned = console.post(
        "/api/console/lines/line-1/assign-truck", json={"truck_id": truck_id_for(plate)}
    )
    assert assigned.status_code == 200, assigned.text
    for status, tp in (("ACC", None), ("ACC", 0.91), ("REJ", None)):
        console.post(
            "/api/v1/internal/vision/events",
            headers=_secret(),
            json={
                "event_id": str(uuid.uuid4()),
                "machine_id": Settings().console_lines[0].machine_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "prediction": "Acc" if status == "ACC" else "Rej",
                "ripeness_status": status,
                "ripeness_confidence": 0.9,
                "tp_status": "PASS" if tp else None,
                "tp_confidence": tp,
                "capture_type": "auto",
                "image_path": None,
                "truck_id": truck_id_for(plate),
                "assignment_id": assigned.json()["assignment_id"],
            },
        ).raise_for_status()

    released = console.post("/api/console/lines/line-1/release-truck")
    assert released.status_code == 200, released.text

    graded = _eventually(
        lambda: (_erp_ticket(erp, visit_id) or {}).get("grading_total") and _erp_ticket(erp, visit_id),
        "the grading never reached the ticket",
    )
    assert (graded["grading_total"], graded["grading_acc"], graded["grading_rej"]) == (3, 2, 1)


@pytest.fixture(scope="module")
def reconciling_plate(erp, cleanup):
    """Its own truck again: the assertion is about one visit's counts."""
    plate = f"BE {secrets.randbelow(9000) + 1000} TSE"
    erp.post(
        "/api/method/erpnext.palm_mill.api.upsert_truck", json={"plate_number": plate}
    ).raise_for_status()
    cleanup.append(plate)
    return plate


def test_a_bunch_without_a_verdict_never_reaches_the_ledger(
    console, erp, fake_line, reconciling_plate
):
    """A ripeness class is not a verdict. Refused at the door, so what AutoERP
    books still reconciles: grading_acc + grading_rej == grading_total.

    Before the check, such an event was stored, counted in `total` and in
    neither `acc` nor `rej` — the mill would have been paid on a summary that
    did not add up.
    """
    plate = reconciling_plate
    console.post("/api/console/trucks", json={"plate_number": plate}).raise_for_status()
    visit_id = console.post(
        "/api/v1/internal/scale/weighing",
        headers=_secret(),
        json={
            "ref": f"E2E-{uuid.uuid4().hex[:8]}",
            "plate_number": plate,
            "waktu_masuk": datetime.now(UTC).isoformat(),
            "bruto_kg": 13400,
        },
    ).json()["id"]
    _eventually(lambda: _erp_ticket(erp, visit_id), "the visit never arrived")

    assigned = console.post(
        "/api/console/lines/line-1/assign-truck", json={"truck_id": truck_id_for(plate)}
    )
    assert assigned.status_code == 200, assigned.text

    def bunch(status: str, **over) -> httpx.Response:
        return console.post(
            "/api/v1/internal/vision/events",
            headers=_secret(),
            json={
                "event_id": str(uuid.uuid4()),
                "machine_id": Settings().console_lines[0].machine_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "ripeness_status": status,
                "ripeness_confidence": 0.9,
                "capture_type": "auto",
                "truck_id": truck_id_for(plate),
                "assignment_id": assigned.json()["assignment_id"],
                **over,
            },
        )

    assert bunch("MATANG").status_code == 400
    assert bunch("ACC", prediction="Rej").status_code == 400
    bunch("ACC", prediction="Acc").raise_for_status()
    bunch("REJ", prediction="Rej").raise_for_status()

    console.post("/api/console/lines/line-1/release-truck").raise_for_status()

    graded = _eventually(
        lambda: (_erp_ticket(erp, visit_id) or {}).get("grading_total") and _erp_ticket(erp, visit_id),
        "the grading never reached the ticket",
    )
    assert graded["grading_acc"] + graded["grading_rej"] == graded["grading_total"] == 2


def test_operator_failures_come_back_as_codes_the_screen_translates(console):
    """The screen words a failure in the operator's language, so the console
    must send a code, not a sentence. Machine lanes keep plain text.

    Line 3 has no stand-in here: nothing listens on its port, exactly like a
    camera service that is down.
    """
    down = console.post("/api/console/lines/line-3/assign-truck", json={"truck_id": "t"})
    assert down.status_code == 502, down.text
    assert down.json()["detail"]["code"] == "line_tidak_menjawab"
    assert down.json()["detail"]["params"]["line"] == Settings().console_lines[2].name

    unknown = console.post("/api/console/lines/line-9/assign-truck", json={"truck_id": "t"})
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "line_tidak_dikenal"

    weighing = {
        "plate_number": "E2E 1 ERR",
        "bruto_kg": "14,82",
        "waktu_masuk": datetime.now(UTC).isoformat(),
    }
    typed = console.post("/api/console/weighings", json=weighing)
    assert typed.status_code == 400
    assert typed.json()["detail"]["code"] == "di_bawah_minimum"
    assert typed.json()["detail"]["params"]["value"] == 14.82

    scale = console.post("/api/v1/internal/scale/weighing", headers=_secret(), json=weighing)
    assert scale.status_code == 400
    assert isinstance(scale.json()["detail"], str)
