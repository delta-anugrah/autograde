"""OPS-2: one physical truck must become one row, once, when a PC is installed.

Why this exists: a factory PC already running stores trucks with a random id
from palmgrade-api (`gen_random_uuid()`), while AutoGrade derives its id from
the plate (`uuid5`). A plate has **no** unique index, so the first master-data
pull adds a second row for the same truck, and that truck's tonnage splits in
two with nothing on screen saying so.

What is guarded here is not "it works", but the things that, if wrong, corrupt
the figure the farmer gets paid on:

- an old random id **cannot** be recomputed from the plate, so the only bridge
  is the normalised plate; if the matching is even slightly different, the
  merge picks the wrong truck
- `truck_id` lives in **three** tables (`inspections`, `assignments`,
  `weighings`). Miss one and that row dangles off an id that no longer
  exists, and its tonnage disappears from the recap
- reconciliation is run by someone installing a PC, often twice out of doubt.
  The second run must change nothing
"""

from __future__ import annotations

import pytest

from palmgrade.domain.plate import truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.rekonsiliasi import rekonsiliasi_truk

# Id shape used by palmgrade-api: a random uuid4, unrelated to the plate.
ID_LAMA = "7f3a9b21-0000-4000-8000-000000000001"
ID_LAMA_2 = "7f3a9b21-0000-4000-8000-000000000002"


@pytest.fixture
def store(tmp_path):
    return ConsoleStore(tmp_path / "console.db")


def _old_style_truck(store: ConsoleStore, truck_id: str, plate: str, **overrides) -> None:
    """A truck row shaped like the ones palmgrade-api left on the factory PC."""
    row = {"id": truck_id, "plate_number": plate, "status": "active"}
    row.update(overrides)
    store.upsert_truck(row)


def _weighing(store: ConsoleStore, wid: str, truck_id: str, plate: str, **overrides) -> None:
    row = {
        "id": wid,
        "ref": None,
        "plate_number": plate,
        "plate_norm": plate.replace(" ", "").replace("-", "").upper(),
        "truck_id": truck_id,
        "work_date": "2026-09-15",
        "gross_kg": 13250.0,
        "tare_kg": None,
        "net_kg": None,
        "entered_at": "2026-09-15T08:55:00+07:00",
        "exited_at": None,
    }
    row.update(overrides)
    store.upsert_weighing(row)


def _inspection(store: ConsoleStore, event_id: str, truck_id: str) -> None:
    store.add_inspection(
        {
            "event_id": event_id,
            "machine_id": "m-1",
            "line_code": "line-1",
            "work_date": "2026-09-15",
            "timestamp": "2026-09-15T09:00:00+07:00",
            "ripeness_status": "ACC",
            "ripeness_confidence": 0.9,
            "capture_type": "auto",
            "image_path": "captures/results/2026-09-15/a.webp",
            "truck_id": truck_id,
            "assignment_id": "asg-1",
            "prediction": "Acc",
            "tp_status": None,
            "tp_confidence": None,
        }
    )


# ── core: two rows become one ──────────────────────────────────────────────


def test_trucks_with_the_same_plate_are_merged_into_one_row(store):
    """This is the entire reason OPS-2 exists. Before merging, the operator sees
    two trucks with the same plate in the dropdown and cannot tell which to pick."""
    _old_style_truck(store, ID_LAMA, "BE 4412 OFL")
    new_id = truck_id_for("BE 4412 OFL")
    store.upsert_truck({"id": new_id, "plate_number": "BE 4412 OFL", "status": "active",
                        "erp_name": "TRK-0001"})
    assert len([t for t in store.trucks() if t["plate_number"] == "BE 4412 OFL"]) == 2

    result = rekonsiliasi_truk(store)

    remaining = [t for t in store.trucks() if t["plate_number"] == "BE 4412 OFL"]
    assert len(remaining) == 1
    assert remaining[0]["id"] == new_id, "the surviving row must be the plate-derived id, not the random one"
    assert result.digabung == 1


def test_the_surviving_row_keeps_erp_name(store):
    """`erp_name` is the link to AutoERP. Losing it means the truck rides up again
    as a new owner-less truck, and backoffice fills in the same truck twice."""
    _old_style_truck(store, ID_LAMA, "BE 4412 OFL")
    new_id = truck_id_for("BE 4412 OFL")
    store.upsert_truck({"id": new_id, "plate_number": "BE 4412 OFL", "status": "active",
                        "erp_name": "TRK-0001"})

    rekonsiliasi_truk(store)

    assert store.truck(new_id)["erp_name"] == "TRK-0001"


def test_supplier_from_the_old_row_is_not_lost(store):
    """The FFB source label is read from the truck, not copied onto the grading row.
    A supplier lost during the merge changes the label across that truck's whole history."""
    store.upsert_supplier({"id": "sup-1", "name": "Koperasi A", "sumber": "Plasma"})
    _old_style_truck(store, ID_LAMA, "BE 4412 OFL", supplier_id="sup-1")
    new_id = truck_id_for("BE 4412 OFL")
    # The ERP pull arrives with no supplier (backoffice has not filled in the truck yet).
    store.upsert_truck({"id": new_id, "plate_number": "BE 4412 OFL", "status": "active"})

    rekonsiliasi_truk(store)

    assert store.truck(new_id)["supplier_id"] == "sup-1"


# ── the three tables that hold truck_id ─────────────────────────────────────


def test_weighings_move_too(store):
    """Otherwise: the net weight dangles off a deleted id and disappears from the
    recap, even though that is the figure that gets paid."""
    _old_style_truck(store, ID_LAMA, "BE 4412 OFL")
    _weighing(store, "w-1", ID_LAMA, "BE 4412 OFL")
    new_id = truck_id_for("BE 4412 OFL")
    store.upsert_truck({"id": new_id, "plate_number": "BE 4412 OFL", "status": "active"})

    rekonsiliasi_truk(store)

    assert store.weighing("w-1")["truck_id"] == new_id


def test_grading_moves_too(store):
    """A dangling bunch must not appear in any truck's recap."""
    _old_style_truck(store, ID_LAMA, "BE 4412 OFL")
    _inspection(store, "ev-1", ID_LAMA)
    new_id = truck_id_for("BE 4412 OFL")
    store.upsert_truck({"id": new_id, "plate_number": "BE 4412 OFL", "status": "active"})

    rekonsiliasi_truk(store)

    recap = {r["truck_id"]: r for r in store.truck_recap("2026-09-15")}
    assert new_id in recap
    assert ID_LAMA not in recap
    assert recap[new_id]["total"] == 1


def test_a_line_assignment_in_progress_moves_too(store):
    """Reconciliation is run while installing the PC, and the mill may already be
    running. A truck currently on a line must stay on that line after the merge."""
    _old_style_truck(store, ID_LAMA, "BE 4412 OFL")
    store.set_assignment("line-1", "asg-1", ID_LAMA)
    new_id = truck_id_for("BE 4412 OFL")
    store.upsert_truck({"id": new_id, "plate_number": "BE 4412 OFL", "status": "active"})

    rekonsiliasi_truk(store)

    assert store.assignments()["line-1"]["truck_id"] == new_id


# ── plate matching ───────────────────────────────────────────────────────────


def test_plate_written_differently_is_still_treated_as_one_truck(store):
    """The same plate typed by the operator, the scale program, and ERP in three
    different styles. Matching must use the same normalised form as
    `truck_id_for`, or a truck that should be merged gets skipped instead."""
    _old_style_truck(store, ID_LAMA, "be-4412-ofl")
    new_id = truck_id_for("BE 4412 OFL")
    store.upsert_truck({"id": new_id, "plate_number": "BE 4412 OFL", "status": "active"})

    result = rekonsiliasi_truk(store)

    assert result.digabung == 1
    assert len([t for t in store.trucks()]) == 1


def test_trucks_with_different_plates_are_never_touched(store):
    """A merge that is too aggressive combines two different trucks, and one
    farmer's tonnage lands on another's. This is the most expensive way to be wrong."""
    _old_style_truck(store, ID_LAMA, "BE 4412 OFL")
    _old_style_truck(store, ID_LAMA_2, "BE 9999 XYZ")
    _weighing(store, "w-2", ID_LAMA_2, "BE 9999 XYZ")
    new_id = truck_id_for("BE 4412 OFL")
    store.upsert_truck({"id": new_id, "plate_number": "BE 4412 OFL", "status": "active"})

    rekonsiliasi_truk(store)

    # The second truck gets its id fixed too (it should), but stays its own
    # row: its plate is intact and its weighing follows it there, not to the
    # first truck.
    other = truck_id_for("BE 9999 XYZ")
    assert store.truck(other)["plate_number"] == "BE 9999 XYZ"
    assert store.weighing("w-2")["truck_id"] == other
    assert len(store.trucks_semua()) == 2, "two different trucks must never become one row"


def test_an_old_truck_with_no_erp_match_yet_still_moves_to_the_plate_derived_id(store):
    """An old truck never yet seen in ERP still has to move to the plate-derived id.
    Left alone, tomorrow's ERP pull carrying that plate would create a second row,
    and the same problem comes back."""
    _old_style_truck(store, ID_LAMA, "BE 4412 OFL")
    _weighing(store, "w-1", ID_LAMA, "BE 4412 OFL")

    result = rekonsiliasi_truk(store)

    new_id = truck_id_for("BE 4412 OFL")
    assert store.truck(new_id) is not None
    assert store.truck(ID_LAMA) is None
    assert store.weighing("w-1")["truck_id"] == new_id
    assert result.dipindah == 1


def test_a_truck_whose_id_is_already_correct_is_skipped(store):
    """Most rows on a freshly installed factory PC are already correct. Touching
    them unnecessarily only adds a chance to break something."""
    new_id = truck_id_for("BE 4412 OFL")
    store.upsert_truck({"id": new_id, "plate_number": "BE 4412 OFL", "status": "active"})

    result = rekonsiliasi_truk(store)

    assert result.digabung == 0 and result.dipindah == 0
    assert result.dilewati == 1


# ── run by a person, often twice ─────────────────────────────────────────────


def test_running_it_twice_gives_the_same_result(store):
    """Whoever runs this is installing a PC and often unsure whether it already
    ran. The second run must change nothing."""
    _old_style_truck(store, ID_LAMA, "BE 4412 OFL")
    _weighing(store, "w-1", ID_LAMA, "BE 4412 OFL")
    new_id = truck_id_for("BE 4412 OFL")
    store.upsert_truck({"id": new_id, "plate_number": "BE 4412 OFL", "status": "active",
                        "erp_name": "TRK-0001"})

    rekonsiliasi_truk(store)
    second = rekonsiliasi_truk(store)

    assert second.digabung == 0 and second.dipindah == 0
    assert store.weighing("w-1")["truck_id"] == new_id
    assert store.truck(new_id)["erp_name"] == "TRK-0001"


def test_dry_run_writes_nothing(store):
    """Run first to preview before deciding. If the dry run also wrote, there
    would be no point having the mode at all."""
    _old_style_truck(store, ID_LAMA, "BE 4412 OFL")
    _weighing(store, "w-1", ID_LAMA, "BE 4412 OFL")

    result = rekonsiliasi_truk(store, tulis=False)

    assert result.dipindah == 1, "the report must still count what WOULD happen"
    assert store.truck(ID_LAMA) is not None, "nothing may change"
    assert store.weighing("w-1")["truck_id"] == ID_LAMA


def test_an_empty_plate_is_listed_but_does_not_cause_a_failure(store):
    """One broken row must not cancel the whole reconciliation: the rest still
    needs fixing, and the broken one is printed for a person to check (OPS-2 spec)."""
    store.upsert_truck({"id": ID_LAMA, "plate_number": None, "status": "active"})
    _old_style_truck(store, ID_LAMA_2, "BE 4412 OFL")

    result = rekonsiliasi_truk(store)

    assert ID_LAMA in [k.truck_id for k in result.kecuali]
    assert result.dipindah == 1, "a healthy truck is still fixed"
    assert store.truck(ID_LAMA) is not None, "the broken one is left as is"


def test_the_result_reads_as_plain_text(store):
    """Read in the factory PC's terminal by someone juggling ten other things."""
    _old_style_truck(store, ID_LAMA, "BE 4412 OFL")
    new_id = truck_id_for("BE 4412 OFL")
    store.upsert_truck({"id": new_id, "plate_number": "BE 4412 OFL", "status": "active"})

    report = rekonsiliasi_truk(store).laporan()

    assert "1" in report
    assert "BE 4412 OFL" in report
