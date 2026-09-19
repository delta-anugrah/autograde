"""The visit message AutoERP receives (contract §4.C).

Pinned: the shape AutoERP parses, that a section we have nothing for is left out
(every send replaces only the sections it carries), and the criteria mapping —
mentah is the rejected share, tangkai panjang the long stalks among accepted.
"""
from __future__ import annotations

from palmgrade.domain.erp_messages import VISIT, visit_message
from palmgrade.domain.plate import truck_id_for

VISIT_ID = "8f1d0f3e-0000-5000-8000-000000000001"
EMITTED = "2026-09-13T08:35:30+07:00"


def _visit(**over) -> dict:
    return {
        "id": VISIT_ID,
        "ref": "SCL-2026-000201",
        "plate_number": "BE 8821 KL",
        "truck_id": truck_id_for("BE 8821 KL"),
        "truck_erp_name": None,
        "supplier_erp_name": "KUD Sumber Makmur",
        "gross_kg": 14560.0,
        "tare_kg": None,
        "entered_at": "2026-09-13T07:41:00+07:00",
        "exited_at": None,
    } | over


def _grading(**over) -> dict:
    return {
        "assignment_id": "a1",
        "line_code": "line-1",
        "started_at": "2026-09-13T07:58:00+07:00",
        "ended_at": "2026-09-13T08:23:00+07:00",
        "total": 412,
        "acc": 371,
        "rej": 41,
        "tangkai_panjang": 23,
        "manual_reject": 3,
    } | over


def _payload(visit=None, grading=None, site="PT Sawit Rambang Lestari"):
    return visit_message(visit or _visit(), grading, site=site, emitted_at=EMITTED)


def test_one_visit_is_one_message():
    """The queue key is the visit id, so three stages replace each other rather
    than racing as three rows."""
    key, payload = _payload()

    assert key == VISIT_ID
    assert payload["visit_id"] == VISIT_ID


def test_the_gate_send_carries_the_weighing_and_no_grading():
    _, payload = _payload()

    assert payload["stage"] == "gate"
    assert payload["weighing"] == {"gross_kg": 14560.0, "time_in": "2026-09-13T07:41:00+07:00"}
    assert "grading" not in payload


def test_the_departure_send_adds_the_tare_and_the_time_out():
    _, payload = _payload(
        _visit(tare_kg=5400.0, exited_at="2026-09-13T08:35:00+07:00")
    )

    assert payload["stage"] == "departed"
    assert payload["weighing"] == {
        "gross_kg": 14560.0,
        "time_in": "2026-09-13T07:41:00+07:00",
        "tare_kg": 5400.0,
        "time_out": "2026-09-13T08:35:00+07:00",
    }


def test_the_truck_and_its_owner_travel_with_the_visit():
    """AutoERP resolves the truck by plate and keeps our id on it, so a ticket
    typed by hand is adopted by the visit later."""
    _, payload = _payload()

    assert payload["truck"] == {
        "plate_number": "BE 8821 KL",
        "autograde_id": truck_id_for("BE 8821 KL"),
    }
    assert payload["supplier_erp_name"] == "KUD Sumber Makmur"
    assert payload["scale_ticket_no"] == "SCL-2026-000201"


def test_the_erp_truck_name_travels_whenever_we_know_it():
    """AutoERP resolves `truck.erp_name` before the plate (`api.py::upsert_visit`).

    Without it a plate whose text the backoffice corrected in AutoERP normalises to
    something else here, and `get_or_create_truck` makes a SECOND Truck: the visit then
    books onto a twin that splits the plate's tonnage.
    """
    _, payload = _payload(_visit(truck_erp_name="BE 8821 KL"))

    assert payload["truck"] == {
        "plate_number": "BE 8821 KL",
        "autograde_id": truck_id_for("BE 8821 KL"),
        "erp_name": "BE 8821 KL",
    }


def test_a_truck_autoerp_has_not_seen_sends_no_erp_name():
    """Omitted, not null: AutoERP then resolves by normalised plate and creates the
    owner-less Truck that interface B is for."""
    _, payload = _payload(_visit(truck_erp_name=None))

    assert "erp_name" not in payload["truck"]


def test_an_unknown_owner_is_left_out_rather_than_guessed():
    """AutoERP owns the supplier: sending nothing keeps whatever it has."""
    _, payload = _payload(_visit(supplier_erp_name=None, ref=None))

    assert "supplier_erp_name" not in payload
    assert "scale_ticket_no" not in payload


def test_the_grading_send_carries_the_counts_and_the_shares_they_imply():
    """The demo's own numbers: 41 of 412 rejected is 9.95 %, 23 long stalks 5.58 %."""
    _, payload = _payload(grading=_grading())

    assert payload["stage"] == "grading"
    assert payload["grading"]["assignment_id"] == "a1"
    assert payload["grading"]["line_code"] == "line-1"
    assert payload["grading"]["started_at"] == "2026-09-13T07:58:00+07:00"
    assert payload["grading"]["ended_at"] == "2026-09-13T08:23:00+07:00"
    assert payload["grading"]["counts"] == {
        "total": 412, "acc": 371, "rej": 41,
        "mentah": 41, "tangkai_panjang": 23, "manual_reject": 3,
    }
    assert payload["grading"]["pct"] == {"mentah": 9.95, "tangkai_panjang": 5.58}


def test_a_weighed_out_truck_stays_departed_even_with_grading():
    """`stage` is informational, but it must not claim the truck is still here."""
    _, payload = _payload(_visit(tare_kg=5400.0), grading=_grading())

    assert payload["stage"] == "departed"
    assert "grading" in payload


def test_grading_with_no_bunches_sends_no_percentages():
    """An assignment that graded nothing must not divide by zero."""
    _, payload = _payload(grading=_grading(total=0, acc=0, rej=0, tangkai_panjang=0, manual_reject=0))

    assert payload["grading"]["pct"] == {"mentah": 0.0, "tangkai_panjang": 0.0}


def test_detail_url_rides_along_when_the_mill_has_one():
    """Since 2026-09-16 the detail page lives in R2, reachable from the cloud, so
    the contract's `detail_url` is sent again (it was blank while it could only
    point at the LAN-only console)."""
    _, payload = _payload(grading=_grading(detail_url="https://captures.smagri.id/viewer.html?visit=v-1"))

    assert payload["grading"]["detail_url"] == "https://captures.smagri.id/viewer.html?visit=v-1"


def test_no_detail_url_without_r2():
    """R2_PUBLIC_URL empty: nothing to point at, and an empty string would erase what AutoERP has."""
    _, payload = _payload(grading=_grading())

    assert "detail_url" not in payload["grading"]


def test_the_site_and_the_send_time_ride_along():
    _, payload = _payload()

    assert payload["site"] == "PT Sawit Rambang Lestari"
    assert payload["emitted_at"] == EMITTED


def test_a_console_without_a_company_configured_leaves_the_site_out():
    """AutoERP falls back to its own default company."""
    _, payload = _payload(site="")

    assert "site" not in payload


def test_the_kind_is_the_visit_lane():
    assert VISIT == "visit"
