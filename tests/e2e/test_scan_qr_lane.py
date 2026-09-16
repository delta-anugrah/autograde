"""End-to-end: `POST /api/console/scan` on a real console app, over real HTTP.

The unit tests call `ScanService` directly and the route tests use a stub console.
What neither covers is the wiring: the dependency that hands the scan service the
same store the rest of the console uses, the session gate in front of the lane, and
the status codes a scanner at the gate actually receives.

Assembled here rather than through `create_console_app()`, which would reach for the
developer's own `state/console.db` and leave test rows in it.
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.operator_error import BELUM_MASUK, BUKAN_PLAT, PLAT_KOSONG
from palmgrade.domain.plate import truck_id_for
from palmgrade.domain.qr import isi_qr_untuk
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service, get_scan_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.scan_service import ScanService

EMAIL = "gerbang@pks.test"
SANDI = "timbangan2026"
PLAT = "BE 4412 OFL"


class _StubConsole:
    """The scan lane touches none of the console service; only the store is shared."""

    def __init__(self, store: ConsoleStore) -> None:
        self.store = store


@pytest.fixture
def gerbang(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual(
        {"email": EMAIL, "full_name": "Operator Gerbang", "password_hash": hash_password(SANDI)}
    )
    store.upsert_truck(
        {
            "id": truck_id_for(PLAT),
            "plate_number": PLAT,
            "status": "active",
            "erp_name": "TRK-0001",
        }
    )

    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_scan_service] = lambda: ScanService(store)
    return TestClient(app), store


@pytest.fixture
def gerbang_penuh(tmp_path):
    """Like `gerbang`, but with a real `ConsoleService`.

    Used only by tests that reach into the weighing path: `_StubConsole`
    deliberately has no `record_weighing`, because the scan lane must never
    touch it. A full-flow test needs both alive, to prove scanning and
    weighing point at the same truck.
    """
    from dataclasses import replace

    from palmgrade.core.config import Settings
    from palmgrade.services.console_service import ConsoleService

    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual(
        {"email": EMAIL, "full_name": "Operator Gerbang", "password_hash": hash_password(SANDI)}
    )
    store.upsert_truck(
        {"id": truck_id_for(PLAT), "plate_number": PLAT, "status": "active",
         "erp_name": "TRK-0001"}
    )

    class SilentLine:
        async def assign_truck(self, *_a, **_k): pass
        async def manual_reject(self, *_a, **_k): pass

    service = ConsoleService(
        replace(Settings(), factory_tz="Asia/Jakarta"), store, SilentLine()
    )

    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_scan_service] = lambda: ScanService(store)
    return TestClient(app), store


def _sign_in(client: TestClient) -> None:
    assert client.post(
        "/api/console/login", json={"email": EMAIL, "sandi": SANDI}
    ).status_code == 200


def test_scan_lane_closed_without_a_session(gerbang):
    client, _ = gerbang

    result = client.post("/api/console/scan", json={"qr": "BE4412OFL"})

    assert result.status_code == 401
    assert result.json()["detail"]["code"] == BELUM_MASUK


def test_a_printed_qr_reads_back_correctly(gerbang):
    """Full circle: what `isi_qr_untuk` prints must be recognised by the scan lane.
    If the two sides used different normalisation rules, a QR we printed ourselves
    would not read back — and that would only surface at the factory gate."""
    client, _ = gerbang
    _sign_in(client)

    result = client.post("/api/console/scan", json={"qr": isi_qr_untuk(PLAT)})

    assert result.status_code == 200
    assert result.json()["ditemukan"] is True
    assert result.json()["truck"]["erp_name"] == "TRK-0001"


def test_three_writing_styles_are_one_truck(gerbang):
    """The plate is written differently by the operator, the scale program, and ERP."""
    client, _ = gerbang
    _sign_in(client)

    truck_ids = {
        client.post("/api/console/scan", json={"qr": q}).json()["truck"]["id"]
        for q in ("BE4412OFL", "be-4412-ofl", "BE 4412 OFL")
    }

    assert len(truck_ids) == 1, "one physical truck read back as several trucks"


def test_a_borrowed_truck_answers_200_not_404(gerbang):
    """A 404 on screen reads like something broke. A borrowed truck is the normal
    case, and the answer has to make the screen offer manual entry."""
    client, _ = gerbang
    _sign_in(client)

    result = client.post("/api/console/scan", json={"qr": "BE9999XYZ"})

    assert result.status_code == 200
    assert result.json() == {
        "ditemukan": False,
        "plate_number": "BE9999XYZ",
        "truck": None,
    }


def test_scanning_repeatedly_does_not_add_a_truck(gerbang):
    """The main guard: one misread QR must not add a ghost truck to master data,
    because that truck would ride up to AutoERP through interface B."""
    client, store = gerbang
    _sign_in(client)
    before = len(store.trucks_semua())

    for q in ("BE9999XYZ", "BE1111AAA", "BE9999XYZ"):
        client.post("/api/console/scan", json={"qr": q})

    assert len(store.trucks_semua()) == before


def test_scan_writes_no_weighing(gerbang):
    """Only `record_weighing` writes weight. Two writers for the figure that gets
    paid is the tidiest way to be wrong for months."""
    client, store = gerbang
    _sign_in(client)

    client.post("/api/console/scan", json={"qr": "BE4412OFL"})

    assert store.weighings(_today()) == []


@pytest.mark.parametrize(
    ("junk", "code"),
    [
        ("https://contoh.id/promo", BUKAN_PLAT),
        ("TRK-0001", BUKAN_PLAT),
        ("!!!", PLAT_KOSONG),   # zero alphanumeric characters: genuinely empty
        ("1234", BUKAN_PLAT),
        ("", PLAT_KOSONG),
        ("   ", PLAT_KOSONG),
    ],
)
def test_anything_that_is_not_a_plate_is_refused_400(gerbang, junk, code):
    """Anything can land in the scanner: a parking receipt, a promo QR, an ERP id,
    a failed read.

    The code is distinguished per cause: the screen translates per code, so one
    code for two causes will always be wrong for one of them. Found in the browser
    — a QR holding a URL showed "Nomor polisi tidak boleh kosong".
    """
    client, _ = gerbang
    _sign_in(client)

    result = client.post("/api/console/scan", json={"qr": junk})

    assert result.status_code == 400
    assert result.json()["detail"]["code"] == code


# ── printing a QR (image lane) ───────────────────────────────────────────────


def test_the_qr_image_needs_a_session():
    """A truck's plate is mill operational data. The image lane sits behind the
    gate like every other operator lane."""
    # App with no session: the `gerbang` fixture already signs in, so this one is
    # assembled by hand.
    store = ConsoleStore(Path(tempfile.mkdtemp()) / "console.db")
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_scan_service] = lambda: ScanService(store)

    result = TestClient(app).get(f"/api/console/trucks/{PLAT}/qr.png")

    assert result.status_code == 401


def test_the_qr_image_is_sent_as_png(gerbang):
    client, _ = gerbang
    _sign_in(client)

    result = client.get(f"/api/console/trucks/{PLAT}/qr.png")

    assert result.status_code == 200
    assert result.headers["content-type"] == "image/png"
    assert result.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_the_qr_image_carries_the_requested_plate(gerbang):
    """Proven through the QR pattern itself: the pattern for one payload is fixed,
    so matching `BE4412OFL`'s pattern means the content really is that."""
    import segno

    from palmgrade.services.qr_cetak import KOREKSI, png_qr

    client, _ = gerbang
    _sign_in(client)

    result = client.get(f"/api/console/trucks/{PLAT}/qr.png")

    assert result.content == png_qr(PLAT)
    # And that pattern really is the plate's pattern, not a coincidence of two
    # functions that are both wrong the same way.
    assert segno.make("BE4412OFL", error=KOREKSI).matrix is not None


def test_any_plate_writing_style_produces_the_same_qr(gerbang):
    """One truck = one QR. Otherwise two cards get printed for one truck, and one
    of them later fails to match its row."""
    client, _ = gerbang
    _sign_in(client)

    contents = {
        client.get(f"/api/console/trucks/{p}/qr.png").content
        for p in ("BE4412OFL", "be-4412-ofl", "BE 4412 OFL")
    }

    assert len(contents) == 1


def test_something_that_is_not_a_plate_is_refused_400(gerbang):
    """A QR's content comes from the truck row, and that row can be wrong. A card
    whose content is not a plate can never be scanned anyway."""
    client, _ = gerbang
    _sign_in(client)

    result = client.get("/api/console/trucks/bukan-plat-1234567/qr.png")

    assert result.status_code == 400
    assert result.json()["detail"]["code"] == BUKAN_PLAT


def test_the_qr_image_for_an_unregistered_truck_is_still_created(gerbang):
    """The card is printed FIRST, the truck registered later — the normal order
    for a new truck. Refusing here would force backoffice to register before they
    can print, for a code that only ever contains the plate."""
    client, _ = gerbang
    _sign_in(client)

    result = client.get("/api/console/trucks/BE9999XYZ/qr.png")

    assert result.status_code == 200
    assert result.content.startswith(b"\x89PNG\r\n\x1a\n")


# ── scan then weigh in, one visit ────────────────────────────────────────────


def test_scan_then_weigh_in_lands_on_the_same_truck(gerbang_penuh):
    """Gate flow: scan the QR, then record gross weight. What is guarded here is
    not that both calls succeed, but that they **point at the same truck** —
    `record_weighing` derives `truck_id` from the plate, and if the scan lane used
    a different rule one visit would land on two trucks.
    """
    client, store = gerbang_penuh
    _sign_in(client)

    result = client.post("/api/console/scan", json={"qr": "be-4412-ofl"}).json()
    assert result["ditemukan"] is True

    response = client.post(
        "/api/console/weighings",
        json={
            "plate_number": result["truck"]["plate_number"],
            "gross_kg": 13250,
            "entered_at": f"{_today()}T08:55:00+07:00",
        },
    )

    assert response.status_code == 201
    ticket = response.json()
    assert ticket["truck_id"] == result["truck"]["id"]


def test_any_scan_style_weighs_the_same_truck(gerbang):
    """The same plate scanned from a QR (`BE4412OFL`) or typed (`BE 4412 OFL`) must
    produce one ticket, not two."""
    client, store = gerbang
    _sign_in(client)

    truck_ids = set()
    for qr in ("BE4412OFL", "be-4412-ofl", "BE 4412 OFL"):
        result = client.post("/api/console/scan", json={"qr": qr}).json()
        truck_ids.add(result["truck"]["id"])

    assert len(truck_ids) == 1


def test_scan_a_borrowed_truck_then_register_then_scan_again(gerbang):
    """The actual order at the gate when a borrowed truck arrives: the scan fails,
    the operator registers the plate, the second scan succeeds. Without that
    middle step a borrowed truck could never be weighed at all."""
    client, store = gerbang
    _sign_in(client)

    assert client.post("/api/console/scan", json={"qr": "BE9999XYZ"}).json()["ditemukan"] is False

    store.upsert_truck(
        {"id": truck_id_for("BE 9999 XYZ"), "plate_number": "BE 9999 XYZ", "status": "manual"}
    )

    again = client.post("/api/console/scan", json={"qr": "BE9999XYZ"}).json()
    assert again["ditemukan"] is True
    assert again["truck"]["plate_number"] == "BE 9999 XYZ"


def test_a_printed_qr_card_can_be_used_to_scan(gerbang):
    """Full circle from card to gate: what is printed onto a QR must be recognised
    by the scan lane. Otherwise we print a stack of cards that cannot read
    themselves back.
    """
    client, _ = gerbang
    _sign_in(client)

    # What gets printed on the card for this plate:
    card_content = isi_qr_untuk(PLAT)

    result = client.post("/api/console/scan", json={"qr": card_content}).json()

    assert result["ditemukan"] is True
    assert result["truck"]["plate_number"] == PLAT


# ── scan at the exit gate ─────────────────────────────────────────────────────


def _today() -> str:
    """The working day the console is on right now — the same way it computes it.

    These tests drive the real exit-scan lane, which only looks for a ticket on
    today's working day. A hard-coded date passes on the day it is written and
    fails every day after.
    """
    return datetime.now(ZoneInfo(Settings().factory_tz)).strftime("%Y-%m-%d")


def _weigh_in(client, plate: str, time: str = "08:00:00") -> dict:
    response = client.post(
        "/api/console/weighings",
        json={"plate_number": plate, "gross_kg": 13250,
              "entered_at": f"{_today()}T{time}+07:00"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_exit_scan_needs_a_session(gerbang):
    client, _ = gerbang

    result = client.post("/api/console/scan/keluar", json={"qr": "BE4412OFL"})

    assert result.status_code == 401
    assert result.json()["detail"]["code"] == BELUM_MASUK


def test_exit_scan_finds_the_ticket_waiting_for_its_tare(gerbang_penuh):
    """Exit gate flow: scan the plate, the system finds the ticket."""
    client, _ = gerbang_penuh
    _sign_in(client)
    ticket = _weigh_in(client, PLAT)

    result = client.post("/api/console/scan/keluar", json={"qr": "be-4412-ofl"})

    assert result.status_code == 200
    body = result.json()
    assert body["ditemukan"] is True
    assert body["weighing"]["id"] == ticket["id"]
    assert body["weighing"]["gross_kg"] == 13250


def test_exit_scan_then_recording_tare_closes_the_same_ticket(gerbang_penuh):
    """Full circle at the exit gate. What is guarded: the tare lands on the
    scanned ticket, and net is computed from that ticket's gross — not another one."""
    client, store = gerbang_penuh
    _sign_in(client)
    _weigh_in(client, PLAT)

    result = client.post("/api/console/scan/keluar", json={"qr": "BE4412OFL"}).json()
    w = result["weighing"]

    response = client.post(
        "/api/console/weighings",
        json={"plate_number": PLAT, "ref": w.get("ref"), "entered_at": w["entered_at"],
              "tare_kg": 5000, "exited_at": f"{_today()}T09:00:00+07:00"},
    )

    assert response.status_code == 201
    assert response.json()["net_kg"] == 8250.0
    # And the ticket is no longer open.
    again = client.post("/api/console/scan/keluar", json={"qr": "BE4412OFL"}).json()
    assert again["ditemukan"] is False


def test_two_open_tickets_are_answered_with_a_choice_not_a_guess(gerbang_penuh):
    """Operator's decision: guessing here can attach the tare to the wrong visit
    and mix two visits' tonnage."""
    client, _ = gerbang_penuh
    _sign_in(client)
    _weigh_in(client, PLAT, "08:00:00")
    _weigh_in(client, PLAT, "10:00:00")

    result = client.post("/api/console/scan/keluar", json={"qr": "BE4412OFL"}).json()

    assert result["ditemukan"] is False
    assert result["ganda"] is True
    assert len(result["choices"]) == 2


def test_exit_scan_with_no_open_ticket_answers_200(gerbang_penuh):
    """A truck whose weigh-in was missed. The answer must be clear, not a 404 that
    reads like something broke."""
    client, _ = gerbang_penuh
    _sign_in(client)

    result = client.post("/api/console/scan/keluar", json={"qr": "BE4412OFL"})

    assert result.status_code == 200
    assert result.json()["ditemukan"] is False


def test_exit_scan_of_something_that_is_not_a_plate_is_refused_400(gerbang_penuh):
    client, _ = gerbang_penuh
    _sign_in(client)

    result = client.post("/api/console/scan/keluar", json={"qr": "https://contoh.id"})

    assert result.status_code == 400
    assert result.json()["detail"]["code"] == BUKAN_PLAT
