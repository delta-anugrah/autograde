"""Master data pulled from AutoERP (plan §2, phase 1).

What is locked here is not "the fetch worked". It is that an ERP truck lands on
the row the operator already typed instead of a twin, that the supplier group
survives the trip untouched, and that a disabled row is marked rather than
dropped.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace

import httpx

from palmgrade.core.config import Settings
from palmgrade.domain.erp_master import supplier_row, truck_row
from palmgrade.domain.ffb_source import label_sumber
from palmgrade.domain.plate import truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.workers import master_data_worker
from palmgrade.workers.master_data_worker import (
    SUPPLIER_CURSOR_KEY,
    TRUCK_CURSOR_KEY,
    MasterDataWorker,
)

ERP = "http://erp.local"


def _supplier(**over) -> dict:
    doc = {
        "name": "KUD Sumber Makmur",
        "supplier_name": "KUD Sumber Makmur",
        "supplier_group": "Plasma",
        "disabled": 0,
        "modified": "2026-09-07 13:51:10.414651",
    }
    doc.update(over)
    return doc


def _truck(**over) -> dict:
    doc = {
        "name": "BE 8821 KL",
        "plate_number": "BE 8821 KL",
        "plate_normalized": "BE8821KL",
        "supplier": "KUD Sumber Makmur",
        "vehicle_class": "Dump Truck",
        "disabled": 0,
        "modified": "2026-09-07 13:52:00.000000",
    }
    doc.update(over)
    return doc


def test_supplier_group_is_stored_raw():
    """The edge renders the source, it never decides it (§3.5b).

    ERP derives Internal/External itself and keeps the Plasma vs agent
    distinction on the Supplier Group, so the group must arrive unflattened.
    """
    row = supplier_row(_supplier(supplier_group="Agen TBS"))

    assert row["sumber"] == "Agen TBS"
    assert row["erp_name"] == "KUD Sumber Makmur"
    assert row["name"] == "KUD Sumber Makmur"


def test_truck_lands_on_the_id_the_operator_already_typed():
    """Same plate, same row — an ERP truck adopts the operator's manual one."""
    row = truck_row(_truck(plate_number="be-8821-kl"))

    assert row["id"] == truck_id_for("BE 8821 KL")
    assert row["erp_name"] == "BE 8821 KL"


def test_truck_points_at_the_same_supplier_row_the_pull_wrote():
    """The truck's supplier link must resolve to the id supplier_row produced."""
    assert truck_row(_truck())["supplier_id"] == supplier_row(_supplier())["id"]


def test_disabled_row_is_marked_inactive():
    """`inactive` is what `ConsoleStore.trucks()` already filters on, so a truck
    revoked upstream stops being assignable while its row stays for history."""
    assert truck_row(_truck(disabled=1))["status"] == "inactive"
    assert truck_row(_truck())["status"] == "active"


def test_erp_name_reaches_a_console_database_that_predates_the_column(tmp_path):
    """Factory consoles already run with the old schema; the column has to
    arrive without a hand-run migration and without touching existing rows."""
    db = tmp_path / "console.db"
    old = sqlite3.connect(db)
    old.executescript(
        """CREATE TABLE suppliers (id TEXT PRIMARY KEY, name TEXT, sumber TEXT, status TEXT);
           CREATE TABLE trucks (id TEXT PRIMARY KEY, plate_number TEXT, supplier_id TEXT,
                                capacity REAL, status TEXT);
           INSERT INTO suppliers VALUES ('lama', 'KUD Lama', 'Plasma', 'active');"""
    )
    old.commit()
    old.close()

    store = ConsoleStore(db)
    store.upsert_supplier(supplier_row(_supplier()))

    con = sqlite3.connect(db)
    tersimpan = con.execute("SELECT id, erp_name FROM suppliers ORDER BY id").fetchall()
    con.close()
    assert tersimpan == [
        (supplier_row(_supplier())["id"], "KUD Sumber Makmur"),
        ("lama", None),
    ]


def test_an_erp_truck_adopts_the_row_the_operator_typed(tmp_path):
    """One plate is one truck. A twin row would split the day's tonnage between
    the operator's truck and the ERP's."""
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_truck(
        {"id": truck_id_for("BE 8821 KL"), "plate_number": "BE 8821 KL", "status": "manual"}
    )

    store.upsert_truck(truck_row(_truck()))

    baris = store.trucks()
    assert [(t["plate_number"], t["status"]) for t in baris] == [("BE 8821 KL", "active")]

    con = sqlite3.connect(tmp_path / "console.db")
    tersimpan = con.execute("SELECT erp_name FROM trucks").fetchall()
    con.close()
    assert tersimpan == [("BE 8821 KL",)]  # the ERP's own id, kept for phase 2


def test_retyping_a_plate_does_not_wipe_the_erp_name(tmp_path):
    """The operator types a plate that is already linked; the local row must not
    lose the link. Phase 2 sends the ticket under that name, so wiping it here
    would surface as a visit the ERP cannot match."""
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_truck(truck_row(_truck()))

    store.upsert_truck(
        {"id": truck_id_for("BE 8821 KL"), "plate_number": "BE 8821 KL", "status": "manual"}
    )

    con = sqlite3.connect(tmp_path / "console.db")
    tersimpan = con.execute("SELECT erp_name FROM trucks").fetchall()
    con.close()
    assert tersimpan == [("BE 8821 KL",)]


def _worker(tmp_path, monkeypatch, handler, *, erp_url: str = ERP):
    """Worker over a real store, with the network — the only collaborator that
    must not be real — replaced by a transport."""
    transport = httpx.MockTransport(handler)
    asli = httpx.AsyncClient
    monkeypatch.setattr(
        master_data_worker.httpx,
        "AsyncClient",
        lambda **kw: asli(transport=transport, headers=kw.get("headers")),
    )
    settings = replace(Settings(), erp_url=erp_url, erp_api_key="k", erp_api_secret="s")
    return MasterDataWorker(settings, ConsoleStore(tmp_path / "console.db"))


def _jawab(suppliers: list[dict], trucks: list[dict]):
    """One handler for both resources, in Frappe's `{"data": [...]}` envelope."""
    dilihat: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        dilihat.append(request)
        isi = suppliers if "Supplier" in str(request.url) else trucks
        return httpx.Response(200, json={"data": isi})

    return handler, dilihat


def test_an_unconfigured_erp_sends_no_traffic_at_all(tmp_path, monkeypatch):
    """`ERP_URL` empty is the default, and the operator screen must never depend
    on this path being wired."""

    def handler(request):  # pragma: no cover - must never run
        raise AssertionError(f"tidak boleh ada permintaan: {request.url}")

    worker = _worker(tmp_path, monkeypatch, handler, erp_url="")
    assert asyncio.run(worker.pull_once()) == 0


def test_pull_asks_only_for_rows_changed_since_the_cursor(tmp_path, monkeypatch):
    """Without the filter every tick drags the whole master list over a mill
    uplink; the token is what the ERP checks before answering at all."""
    handler, dilihat = _jawab([], [])
    worker = _worker(tmp_path, monkeypatch, handler)
    worker.store.set_state(SUPPLIER_CURSOR_KEY, "2026-09-07 13:51:10.414651")

    asyncio.run(worker.pull_once())

    supplier_req = next(r for r in dilihat if "Supplier" in str(r.url))
    filters = json.loads(supplier_req.url.params["filters"])
    assert filters[0][0:2] == ["modified", ">"]
    # Slightly BEFORE the cursor: two clocks never agree to the millisecond, and
    # a row written in the same second would otherwise never be seen again.
    assert filters[0][2] < "2026-09-07 13:51:10.414651"
    assert supplier_req.headers["authorization"] == "token k:s"


def test_rows_land_and_each_cursor_follows_its_own_newest_row(tmp_path, monkeypatch):
    """Suppliers and trucks move at different rates, so one shared cursor would
    let a quiet resource drag a busy one back over the same rows forever."""
    handler, _ = _jawab([_supplier()], [_truck(modified="2026-09-08 09:00:00.000000")])
    worker = _worker(tmp_path, monkeypatch, handler)

    assert asyncio.run(worker.pull_once()) == 2

    truk = worker.store.trucks()
    assert [(t["plate_number"], t["supplier_name"], t["sumber"]) for t in truk] == [
        ("BE 8821 KL", "KUD Sumber Makmur", "Plasma")
    ]
    assert worker.store.get_state(SUPPLIER_CURSOR_KEY) == "2026-09-07 13:51:10.414651"
    assert worker.store.get_state(TRUCK_CURSOR_KEY) == "2026-09-08 09:00:00.000000"


def test_cursor_holds_when_a_row_fails_to_land(tmp_path, monkeypatch):
    """Moved here from the cloud pull, unchanged in substance: skipping a row
    that never landed leaves the mill on a half-stale matrix forever, including
    revocations the ERP already made."""
    handler, _ = _jawab([_supplier(), {"supplier_name": "tanpa name"}], [])
    worker = _worker(tmp_path, monkeypatch, handler)

    asyncio.run(worker.pull_once())

    assert worker.store.get_state(SUPPLIER_CURSOR_KEY) is None


def test_an_erp_supplier_group_renders_as_external():
    """AutoERP's own rule is "has a supplier -> External", and every row this
    pull writes has one. The group name itself is master data an admin can add
    to, so the label must not depend on a list of known groups.
    """
    assert label_sumber("Agen TBS") == "External"
    assert label_sumber("Umum") == "External"
    assert label_sumber("Plasma") == "External"


def test_the_mill_s_own_fruit_is_still_internal():
    """`Inti` keeps its meaning: fruit from the estate, nothing bought."""
    assert label_sumber("Inti") == "Internal"
    assert label_sumber(None) is None
    assert label_sumber("  ") is None
