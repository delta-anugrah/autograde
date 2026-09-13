"""Master data pulled from AutoERP (autoerp `docs/autograde-integration.md` §4.A).

Pinned here: the pull names only fields the DocTypes really have, an ERP truck
lands on the row the operator already typed, and a failed row holds the cursor.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace

import httpx

from palmgrade.core.config import Settings
from palmgrade.domain.erp_master import supplier_row, truck_row
from palmgrade.domain.plate import truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.workers import master_data_worker
from palmgrade.workers.master_data_worker import (
    SUPPLIER_CURSOR_KEY,
    TRUCK_CURSOR_KEY,
    MasterDataWorker,
)

ERP = "http://erp.local"

# Truck: `erpnext/palm_mill/doctype/truck/truck.json`. Supplier: the fields the
# contract reads. Frappe refuses a field list naming anything else, so the fake
# ERP below refuses it too.
DOCTYPE_FIELDS = {
    "Supplier": {"name", "modified", "supplier_name", "supplier_group", "disabled"},
    "Truck": {
        "name", "modified", "plate_number", "supplier", "vehicle_class",
        "driver_name", "plate_normalized", "autograde_id", "source",
    },
}


def _supplier(**over) -> dict:
    return {
        "name": "KUD Sumber Makmur",
        "supplier_name": "KUD Sumber Makmur",
        "supplier_group": "Plasma",
        "disabled": 0,
        "modified": "2026-09-07 13:51:10.414651",
    } | over


def _truck(**over) -> dict:
    return {
        "name": "BE 8821 KL",
        "plate_number": "BE 8821 KL",
        "plate_normalized": "BE8821KL",
        "supplier": "KUD Sumber Makmur",
        "vehicle_class": "Dump Truck",
        "modified": "2026-09-07 13:52:00.000000",
    } | over


# ------------------------------------------------------------------ mapping


def test_supplier_group_is_stored_raw():
    """AutoERP keeps Plasma vs agent on the Supplier Group; it arrives untouched."""
    row = supplier_row(_supplier(supplier_group="Agen TBS"))

    assert (row["sumber"], row["erp_name"], row["name"]) == (
        "Agen TBS", "KUD Sumber Makmur", "KUD Sumber Makmur",
    )


def test_disabled_supplier_is_marked_inactive():
    """Marked, not dropped: history that points at it must stay readable."""
    assert supplier_row(_supplier(disabled=1))["status"] == "inactive"
    assert supplier_row(_supplier())["status"] == "active"


def test_erp_truck_is_active():
    """AutoERP's Truck has no `disabled` field, so every pulled truck is assignable."""
    assert truck_row(_truck())["status"] == "active"


def test_truck_lands_on_the_id_the_operator_already_typed():
    """Same plate, same row: an ERP truck adopts the operator's manual one."""
    row = truck_row(_truck(plate_number="be-8821-kl"))

    assert row["id"] == truck_id_for("BE 8821 KL")
    assert row["erp_name"] == "BE 8821 KL"


def test_truck_points_at_the_supplier_row_the_pull_wrote():
    assert truck_row(_truck())["supplier_id"] == supplier_row(_supplier())["id"]


# -------------------------------------------------------------------- store


def test_erp_name_reaches_a_console_database_that_predates_the_column(tmp_path):
    """Factory consoles run the old schema; the column must arrive without a
    hand-run migration and without touching existing rows."""
    db = tmp_path / "console.db"
    old = sqlite3.connect(db)
    old.executescript(
        """CREATE TABLE suppliers (id TEXT PRIMARY KEY, name TEXT, sumber TEXT, status TEXT);
           CREATE TABLE trucks (id TEXT PRIMARY KEY, plate_number TEXT, supplier_id TEXT,
                                capacity REAL, status TEXT);
           INSERT INTO suppliers VALUES ('old', 'KUD Lama', 'Plasma', 'active');"""
    )
    old.commit()
    old.close()

    store = ConsoleStore(db)
    store.upsert_supplier(supplier_row(_supplier()))

    con = sqlite3.connect(db)
    stored = con.execute("SELECT id, erp_name FROM suppliers ORDER BY id").fetchall()
    con.close()
    assert stored == [(supplier_row(_supplier())["id"], "KUD Sumber Makmur"), ("old", None)]


def test_an_erp_truck_adopts_the_row_the_operator_typed(tmp_path):
    """One plate is one truck; a twin row would split the day's tonnage."""
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_truck(
        {"id": truck_id_for("BE 8821 KL"), "plate_number": "BE 8821 KL", "status": "manual"}
    )

    store.upsert_truck(truck_row(_truck()))

    assert [(t["plate_number"], t["status"]) for t in store.trucks()] == [("BE 8821 KL", "active")]
    con = sqlite3.connect(tmp_path / "console.db")
    assert con.execute("SELECT erp_name FROM trucks").fetchall() == [("BE 8821 KL",)]
    con.close()


def test_retyping_a_plate_does_not_wipe_the_erp_name(tmp_path):
    """The visit is sent under that name later; losing it makes it unmatchable."""
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_truck(truck_row(_truck()))

    store.upsert_truck(
        {"id": truck_id_for("BE 8821 KL"), "plate_number": "BE 8821 KL", "status": "manual"}
    )

    con = sqlite3.connect(tmp_path / "console.db")
    assert con.execute("SELECT erp_name FROM trucks").fetchall() == [("BE 8821 KL",)]
    con.close()


# ------------------------------------------------------------------- worker


def _worker(tmp_path, monkeypatch, handler, *, erp_url: str = ERP) -> MasterDataWorker:
    """A real store; only the network is faked."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        master_data_worker.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=transport, headers=kw.get("headers")),
    )
    settings = replace(Settings(), erp_url=erp_url, erp_api_key="k", erp_api_secret="s")
    return MasterDataWorker(settings, ConsoleStore(tmp_path / "console.db"))


def _fake_erp(suppliers: list[dict], trucks: list[dict]):
    """Frappe's `/api/resource` in miniature, strict about field names."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        doctype = request.url.path.rsplit("/", 1)[-1]
        unknown = set(json.loads(request.url.params["fields"])) - DOCTYPE_FIELDS[doctype]
        if unknown:
            # Real AutoERP's answer, observed against autoerp 51d3bf2.
            message = f"Field not permitted in query: {sorted(unknown)[0]}"
            return httpx.Response(417, json={"exc_type": "DataError", "exception": message})
        return httpx.Response(200, json={"data": suppliers if doctype == "Supplier" else trucks})

    return handler, seen


def test_an_unconfigured_erp_sends_no_traffic(tmp_path, monkeypatch):
    """`ERP_URL` empty is the default; the operator screen never depends on it."""

    def handler(request):  # pragma: no cover - must never run
        raise AssertionError(f"unexpected request: {request.url}")

    worker = _worker(tmp_path, monkeypatch, handler, erp_url="")
    assert asyncio.run(worker.pull_once()) == 0


def test_pull_names_only_fields_the_doctypes_have(tmp_path, monkeypatch):
    """One unknown field fails the whole request against a real AutoERP."""
    handler, _ = _fake_erp([_supplier()], [_truck()])
    worker = _worker(tmp_path, monkeypatch, handler)

    assert asyncio.run(worker.pull_once()) == 2


def test_pull_asks_only_for_rows_changed_since_the_cursor(tmp_path, monkeypatch):
    handler, seen = _fake_erp([], [])
    worker = _worker(tmp_path, monkeypatch, handler)
    worker.store.set_state(SUPPLIER_CURSOR_KEY, "2026-09-07 13:51:10.414651")

    asyncio.run(worker.pull_once())

    request = next(r for r in seen if r.url.path.endswith("/Supplier"))
    filters = json.loads(request.url.params["filters"])
    assert filters[0][0:2] == ["modified", ">"]
    # Slightly before the cursor: two clocks never agree to the millisecond.
    assert filters[0][2] < "2026-09-07 13:51:10.414651"
    assert request.headers["authorization"] == "token k:s"


def test_each_cursor_follows_its_own_newest_row(tmp_path, monkeypatch):
    """One shared cursor would drag a quiet resource back over seen rows."""
    handler, _ = _fake_erp([_supplier()], [_truck(modified="2026-09-08 09:00:00.000000")])
    worker = _worker(tmp_path, monkeypatch, handler)

    asyncio.run(worker.pull_once())

    assert [(t["plate_number"], t["supplier_name"]) for t in worker.store.trucks()] == [
        ("BE 8821 KL", "KUD Sumber Makmur")
    ]
    assert worker.store.get_state(SUPPLIER_CURSOR_KEY) == "2026-09-07 13:51:10.414651"
    assert worker.store.get_state(TRUCK_CURSOR_KEY) == "2026-09-08 09:00:00.000000"


def test_cursor_holds_when_a_row_fails_to_land(tmp_path, monkeypatch):
    """Skipping a row that never landed leaves the mill half-stale for good."""
    handler, _ = _fake_erp([_supplier(), {"supplier_name": "no name"}], [])
    worker = _worker(tmp_path, monkeypatch, handler)

    asyncio.run(worker.pull_once())

    assert worker.store.get_state(SUPPLIER_CURSOR_KEY) is None
