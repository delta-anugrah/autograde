"""Master data pulled from AutoERP (autoerp `docs/autograde-integration.md` §4.A).

Pinned: the pull names only fields the DocTypes really have, an ERP truck lands
on the row the operator already typed, and a failed row holds the cursor.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from urllib.parse import unquote

import httpx

from palmgrade.domain.erp_master import operator_row, supplier_row, truck_row
from palmgrade.domain.operator_auth import verify_password
from palmgrade.domain.plate import truck_id_for
from palmgrade.integrations.erp.client import ErpClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.workers.master_data_worker import (
    OPERATOR_CURSOR_KEY,
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
    # `erpnext/palm_mill/doctype/autograde_operator/autograde_operator.json`.
    "AutoGrade Operator": {
        "name", "modified", "email", "full_name", "active", "password_hash", "role",
    },
}

# What AutoERP's passlib context writes. The console verifies it without passlib, which
# is what lets an operator sign in while the internet is down.
OPERATOR_HASH = "$pbkdf2-sha256$29000$LuX8f895T2kNYcx5T2nt3Q$D5HIS3SGDVbL0W7HeOWXMlT9lQuv4dWlA8wOFbs0AW8"


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


def _operator(**over) -> dict:
    """The DocType is named by the email, so `name` and `email` agree."""
    return {
        "name": "budi@pks.test",
        "email": "budi@pks.test",
        "full_name": "Pak Budi",
        "active": 1,
        "password_hash": OPERATOR_HASH,
        "modified": "2026-09-07 13:53:00.000000",
    } | over


# ------------------------------------------------------------------ mapping


def test_supplier_group_is_stored_raw():
    """AutoERP keeps Plasma vs agent on the Supplier Group; it arrives untouched."""
    row = supplier_row(_supplier(supplier_group="Agen TBS"))

    assert (row["source_group"], row["erp_name"], row["name"]) == (
        "Agen TBS", "KUD Sumber Makmur", "KUD Sumber Makmur",
    )


def test_disabled_supplier_is_marked_inactive():
    """Marked, not dropped: history that points at it must stay readable."""
    assert supplier_row(_supplier(disabled=1))["status"] == "inactive"
    assert supplier_row(_supplier())["status"] == "active"


def test_erp_truck_is_active():
    """AutoERP's Truck has no `disabled` field, so every pulled truck is assignable."""
    assert truck_row(_truck())["status"] == "active"


def test_operator_arrives_with_the_hash_the_console_will_verify_offline():
    """The hash travels with the account; nothing is asked of AutoERP at sign-in."""
    row = operator_row(_operator())

    assert (row["email"], row["full_name"], row["erp_name"]) == (
        "budi@pks.test", "Pak Budi", "budi@pks.test",
    )
    assert (row["password_hash"], row["active"]) == (OPERATOR_HASH, 1)


def test_an_operator_deactivated_in_autoerp_arrives_marked_inactive():
    """`active = 0` is how backoffice removes someone who left."""
    assert operator_row(_operator(active=0))["active"] == 0


def test_an_operator_with_no_password_yet_arrives_with_an_empty_hash():
    """Created in AutoERP, password not set. `verify_password` refuses an empty hash, so
    the account simply cannot sign in — which is the honest reading of that state."""
    assert operator_row(_operator(password_hash=None))["password_hash"] == ""


def test_an_operator_with_no_full_name_falls_back_to_the_email():
    """The screen has to show something, and an empty button is unusable."""
    assert operator_row(_operator(full_name=None))["full_name"] == "budi@pks.test"


def test_operator_row_membawa_peran():
    row = operator_row(
        {"name": "a@b.c", "email": "a@b.c", "full_name": "A",
         "password_hash": "x", "active": 1, "role": "support"}
    )
    assert row["role"] == "support"


def test_operator_row_tanpa_peran_tetap_mentah():
    """`operator_row` does not normalize; only the store does, via `filter_erp_role`."""
    row = operator_row({"name": "a@b.c", "email": "a@b.c", "full_name": "A"})
    assert row["role"] == ""


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
        """CREATE TABLE suppliers (id TEXT PRIMARY KEY, name TEXT, source_group TEXT, status TEXT);
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


def _worker(tmp_path, handler) -> MasterDataWorker:
    """A real store and a real client; only the network is faked."""
    client = ErpClient(ERP, "k", "s", transport=httpx.MockTransport(handler))
    return MasterDataWorker(ConsoleStore(tmp_path / "console.db"), client)


def _fake_erp(suppliers: list[dict], trucks: list[dict], operators: list[dict] | None = None):
    """Frappe's `/api/resource` in miniature, strict about field names."""
    seen: list[httpx.Request] = []
    rows = {"Supplier": suppliers, "Truck": trucks, "AutoGrade Operator": operators or []}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        # Unquoted: "AutoGrade Operator" arrives percent-encoded in the path.
        doctype = unquote(request.url.path.rsplit("/", 1)[-1])
        unknown = set(json.loads(request.url.params["fields"])) - DOCTYPE_FIELDS[doctype]
        if unknown:
            # Real AutoERP's answer, observed against autoerp 51d3bf2.
            message = f"Field not permitted in query: {sorted(unknown)[0]}"
            return httpx.Response(417, json={"exc_type": "DataError", "exception": message})
        return httpx.Response(200, json={"data": rows[doctype]})

    return handler, seen


def test_pull_names_only_fields_the_doctypes_have(tmp_path):
    """One unknown field fails the whole request against a real AutoERP."""
    handler, _ = _fake_erp([_supplier()], [_truck()], [_operator()])
    worker = _worker(tmp_path, handler)

    assert asyncio.run(worker.pull_once()) == 3


def test_a_pulled_operator_can_sign_in_at_the_mill(tmp_path):
    """End of the offline chain: backoffice sets the password, the pull carries the hash,
    and the console verifies it here with no network in the path."""
    handler, _ = _fake_erp([], [], [_operator()])
    worker = _worker(tmp_path, handler)

    asyncio.run(worker.pull_once())

    row = worker.store.operator_by_email("budi@pks.test")
    assert (row["full_name"], row["origin"], row["status"]) == ("Pak Budi", "erp", "active")
    assert verify_password("sawit2026", row["password_hash"])


def test_an_operator_cursor_is_its_own(tmp_path):
    """Accounts change far less often than trucks; one shared cursor would drag them
    back over rows already seen."""
    handler, _ = _fake_erp([], [], [_operator()])
    worker = _worker(tmp_path, handler)

    asyncio.run(worker.pull_once())

    assert worker.store.get_state(OPERATOR_CURSOR_KEY) == "2026-09-07 13:53:00.000000"


def test_pull_asks_only_for_rows_changed_since_the_cursor(tmp_path):
    handler, seen = _fake_erp([], [])
    worker = _worker(tmp_path, handler)
    worker.store.set_state(SUPPLIER_CURSOR_KEY, "2026-09-07 13:51:10.414651")

    asyncio.run(worker.pull_once())

    request = next(r for r in seen if r.url.path.endswith("/Supplier"))
    filters = json.loads(request.url.params["filters"])
    assert filters[0][0:2] == ["modified", ">"]
    # Slightly before the cursor: two clocks never agree to the millisecond.
    assert filters[0][2] < "2026-09-07 13:51:10.414651"
    assert request.headers["authorization"] == "token k:s"


def test_each_cursor_follows_its_own_newest_row(tmp_path):
    """One shared cursor would drag a quiet resource back over seen rows."""
    handler, _ = _fake_erp([_supplier()], [_truck(modified="2026-09-08 09:00:00.000000")])
    worker = _worker(tmp_path, handler)

    asyncio.run(worker.pull_once())

    assert [(t["plate_number"], t["supplier_name"]) for t in worker.store.trucks()] == [
        ("BE 8821 KL", "KUD Sumber Makmur")
    ]
    assert worker.store.get_state(SUPPLIER_CURSOR_KEY) == "2026-09-07 13:51:10.414651"
    assert worker.store.get_state(TRUCK_CURSOR_KEY) == "2026-09-08 09:00:00.000000"


def test_cursor_holds_when_a_row_fails_to_land(tmp_path):
    """Skipping a row that never landed leaves the mill half-stale for good."""
    handler, _ = _fake_erp([_supplier(), {"supplier_name": "no name"}], [])
    worker = _worker(tmp_path, handler)

    asyncio.run(worker.pull_once())

    assert worker.store.get_state(SUPPLIER_CURSOR_KEY) is None
