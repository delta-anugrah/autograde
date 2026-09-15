"""Wiring the AutoERP link, and what AutoERP's answers do locally.

The composition root decides whether the link exists at all: no `ERP_URL`, no
workers, no traffic — the operator screen must never depend on AutoERP.
"""
from __future__ import annotations

from dataclasses import replace

from palmgrade.core.config import Settings
from palmgrade.domain.erp_master import supplier_id_for
from palmgrade.domain.plate import truck_id_for
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.erp_queue import ErpQueue
from palmgrade.workers.erp_link import build_erp_workers, truck_linked, visit_recorded
from palmgrade.workers.erp_outbox_worker import ErpOutboxWorker
from palmgrade.workers.master_data_worker import MasterDataWorker
from palmgrade.workers.visit_resend_worker import VisitResendWorker

PLATE = "BE 1 AA"


def _parts(tmp_path) -> tuple[ConsoleStore, ErpQueue]:
    store = ConsoleStore(tmp_path / "console.db")
    return store, ErpQueue(store, ErpOutboxStore(tmp_path / "erp_outbox.db"))


def _weighing(store: ConsoleStore, weighing_id: str = "w1") -> str:
    store.upsert_weighing(
        {
            "id": weighing_id, "ref": "SCL-1", "plate_number": PLATE, "plate_norm": "BE1AA",
            "truck_id": truck_id_for(PLATE), "tanggal_kerja": "2026-09-13",
            "bruto_kg": 14560.0, "tara_kg": None, "neto_kg": None,
            "waktu_masuk": "2026-09-13T07:41:00+07:00", "waktu_keluar": None,
        }
    )
    return weighing_id


def test_without_an_erp_url_there_are_no_workers(tmp_path):
    store, queue = _parts(tmp_path)

    assert build_erp_workers(replace(Settings(), erp_url=""), store, queue) == []


def test_an_erp_url_starts_the_pull_the_outbox_and_the_daily_resend(tmp_path):
    store, queue = _parts(tmp_path)
    settings = replace(
        Settings(), erp_url="http://erp.local", erp_api_key="k", erp_api_secret="s"
    )

    workers = build_erp_workers(settings, store, queue)

    assert [type(worker) for worker in workers] == [
        MasterDataWorker, ErpOutboxWorker, VisitResendWorker,
    ]


def test_a_truck_autoerp_accepted_is_linked_to_its_erp_name(tmp_path):
    """`erp_name` is what the visit is sent under later; losing it makes the
    ticket unmatchable on the ERP side."""
    store, _ = _parts(tmp_path)
    store.upsert_truck({"id": truck_id_for("be 1 aa"), "plate_number": "be 1 aa", "status": "manual"})

    truck_linked(store)("BE1AA", {"name": PLATE, "supplier": None, "vehicle_class": ""})

    row = store.truck(truck_id_for(PLATE))
    assert (row["erp_name"], row["supplier_id"]) == (PLATE, None)


def test_a_plate_autoerp_already_knew_brings_its_owner_back(tmp_path):
    """AutoERP answers with the owner it already has; the console shows it at
    once instead of waiting for the truck to be touched upstream again."""
    store, _ = _parts(tmp_path)
    store.upsert_truck({"id": truck_id_for(PLATE), "plate_number": PLATE, "status": "manual"})

    truck_linked(store)("BE1AA", {"name": PLATE, "supplier": "KUD Sumber Makmur"})

    assert store.truck(truck_id_for(PLATE))["supplier_id"] == supplier_id_for("KUD Sumber Makmur")


def test_the_ticket_autoerp_made_is_kept_against_the_weighing(tmp_path):
    """The trace from a weighbridge row at the mill to the receipt in the ledger."""
    store, _ = _parts(tmp_path)
    _weighing(store)

    visit_recorded(store)("w1", {"ticket": "WB-2026-03851", "status": "Waiting Grading"})

    row = store.weighing("w1")
    assert (row["erp_ticket"], row["erp_status"]) == ("WB-2026-03851", "Waiting Grading")


def test_a_revision_after_finalisation_is_recorded_and_logged(tmp_path, caplog):
    """AutoERP never rewrites a finalised ticket: it flags `grading_revised`, leaves a
    comment, and says so in `note`. Keeping only the ticket number threw that away, so
    nobody at the mill could tell that the numbers they sent were not the booked ones.
    """
    store, _ = _parts(tmp_path)
    _weighing(store)

    with caplog.at_level("WARNING"):
        visit_recorded(store)(
            "w1",
            {
                "ticket": "WB-2026-03851",
                "status": "Finalised",
                "revised": True,
                "note": "ticket already finalised; grading revised",
            },
        )

    row = store.weighing("w1")
    assert (row["erp_status"], row["erp_note"]) == (
        "Finalised",
        "ticket already finalised; grading revised",
    )
    assert "grading revised" in caplog.text


def test_a_cancelled_ticket_is_recorded_as_such(tmp_path):
    """`note: ticket cancelled; visit ignored` means AutoERP took nothing from this
    send. Marking it delivered without the note reads as success."""
    store, _ = _parts(tmp_path)
    _weighing(store)

    visit_recorded(store)(
        "w1", {"ticket": "WB-2026-03851", "status": "Cancelled", "note": "ticket cancelled; visit ignored"}
    )

    assert store.weighing("w1")["erp_note"] == "ticket cancelled; visit ignored"


def test_an_answer_for_a_weighing_we_no_longer_have_is_harmless(tmp_path):
    """The row can be gone by the time the outbox drains; recording must not raise."""
    store, _ = _parts(tmp_path)

    visit_recorded(store)("w1", {"note": "ticket cancelled; visit ignored"})
