"""Wiring the AutoERP link, and what a truck AutoERP accepted does locally.

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
from palmgrade.workers.erp_link import build_erp_workers, truck_linked
from palmgrade.workers.erp_outbox_worker import ErpOutboxWorker
from palmgrade.workers.master_data_worker import MasterDataWorker


def _parts(tmp_path) -> tuple[ConsoleStore, ErpOutboxStore]:
    return ConsoleStore(tmp_path / "console.db"), ErpOutboxStore(tmp_path / "erp_outbox.db")


def test_without_an_erp_url_there_are_no_workers(tmp_path):
    store, outbox = _parts(tmp_path)

    assert build_erp_workers(replace(Settings(), erp_url=""), store, outbox) == []


def test_an_erp_url_starts_the_pull_and_the_outbox(tmp_path):
    store, outbox = _parts(tmp_path)
    settings = replace(
        Settings(), erp_url="http://erp.local", erp_api_key="k", erp_api_secret="s"
    )

    workers = build_erp_workers(settings, store, outbox)

    assert [type(worker) for worker in workers] == [MasterDataWorker, ErpOutboxWorker]


def test_a_truck_autoerp_accepted_is_linked_to_its_erp_name(tmp_path):
    """`erp_name` is what the visit is sent under later; losing it makes the
    ticket unmatchable on the ERP side."""
    store, _ = _parts(tmp_path)
    store.upsert_truck(
        {"id": truck_id_for("be 1 aa"), "plate_number": "be 1 aa", "status": "manual"}
    )

    truck_linked(store)("BE1AA", {"name": "BE 1 AA", "supplier": None, "vehicle_class": ""})

    row = store.truck(truck_id_for("BE 1 AA"))
    assert (row["erp_name"], row["supplier_id"]) == ("BE 1 AA", None)


def test_a_plate_autoerp_already_knew_brings_its_owner_back(tmp_path):
    """AutoERP answers with the owner it already has; the console shows it at
    once instead of waiting for the truck to be touched upstream again."""
    store, _ = _parts(tmp_path)
    store.upsert_truck(
        {"id": truck_id_for("BE 1 AA"), "plate_number": "BE 1 AA", "status": "manual"}
    )

    truck_linked(store)("BE1AA", {"name": "BE 1 AA", "supplier": "KUD Sumber Makmur"})

    assert store.truck(truck_id_for("BE 1 AA"))["supplier_id"] == supplier_id_for(
        "KUD Sumber Makmur"
    )
