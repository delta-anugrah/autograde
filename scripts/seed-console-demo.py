#!/usr/bin/env python3
"""Fill the operator console with demo data for a showcase.

    make demo                  a week of history, then the accounts to sign in with
    make demo HARI=3           fewer days
    make demo AKSI=reset       delete what this script made, then build it again

DEV AND DEMO ONLY — never on the factory PC. It writes grading events and weighbridge
tickets into the console database, and on a real mill that is the operator's own day
mixed with invented bunches. It refuses to run unless the database is empty of real
data, or `PAKSA=1` is set.

It writes to SQLite directly instead of posting to the API, so nothing needs to be
running and no secret has to be passed on the command line. The earlier version needed
`WEBHOOK_SECRET`, three machine ids and an operator password just to start.

The plates are the same ten as AutoERP's seeder (`erpnext/palm_mill/demo.py`). That is
the point: seed both sides and one truck is the same truck on both screens, so the
demo can show a visit at the mill and then the ticket it became in the ERP. Change a
plate here and change it there in the same pull request.

Every id is a uuid5 of its natural key, so re-running adds nothing new.
"""

from __future__ import annotations

import argparse
import random
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# scripts/ is not a package and the image sets no PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palmgrade.core.config import Settings  # noqa: E402
from palmgrade.domain.operator_auth import hash_password, operator_id_for  # noqa: E402
from palmgrade.domain.plate import normalisasi_plat, truck_id_for  # noqa: E402
from palmgrade.domain.role import ROLE_OPERATOR, ROLE_SUPPORT  # noqa: E402
from palmgrade.domain.working_day import work_date_for  # noqa: E402
from palmgrade.repositories.console_repository import ConsoleStore  # noqa: E402

# Must match PLATES in autoerp/erpnext/palm_mill/demo.py.
PLATES = (
    "BE 6311 TSA",
    "BE 1825 TSC",
    "BE 8605 TSD",
    "BE 9698 TSD",
    "BE 1473 TSE",
    "BE 5585 TSE",
    "BE 9874 TSE",
    "BG 9911 ZA",
    "BG 7742 ZB",
    "BG 3308 ZC",
)

# Same two accounts AutoERP's CONSOLE_USERS carries, so a demo that pulls master data
# from AutoERP shows the same people it would have created on its own.
DEMO_PASSWORD = "sawit2026"
ACCOUNTS = (
    ("operator@demo.autoerp.test", "Operator Line", ROLE_OPERATOR),
    ("support@demo.autoerp.test", "Support AutoGrade", ROLE_SUPPORT),
)

LINES = ("line-1", "line-2", "line-3")
DAYS = 7
VISITS_PER_DAY = (4, 7)
BUNCHES_PER_VISIT = (28, 64)
SEED = 20260917

# A bunch is ~20 kg; a visit nets a few tonnes. Gross/tare are drawn, net follows.
GROSS_RANGE = (9000, 24000)
TARE_RANGE = (4000, 8000)

# Share of bunches the line rejects, and — among the rejects — how many are Janjang
# Kosong rather than Unripe. Both are drawn so the demo shows the grade-class column
# filled; a screen where JK is always zero hides a miswired class.
REJ_SHARE = (0.03, 0.14)
JK_SHARE_OF_REJ = 0.2

DEMO_TAG = "demo:"  # every seeded id is uuid5 of a string starting with this


def _uid(kind: str, key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{DEMO_TAG}{kind}:{key}"))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hari", type=int, default=DAYS, help="days of history (default 7)")
    ap.add_argument("--reset", action="store_true", help="delete demo rows first")
    ap.add_argument("--paksa", action="store_true", help="run even on a non-empty database")
    args = ap.parse_args(argv[1:])

    settings = Settings()
    store = ConsoleStore(settings.console_db_path)
    tz = ZoneInfo(settings.factory_tz)
    # Printed every time: writing demo data into the wrong database is the one mistake
    # this script could make silently.
    print(f"Database konsol: {settings.console_db_path}")

    if args.reset:
        print(f"  dihapus: {wipe(store)} baris demo")

    if not args.paksa:
        refused = guard(store)
        if refused:
            print(f"\nBERHENTI: {refused}", file=sys.stderr)
            print("Pakai PAKSA=1 kalau memang mau menimpa.", file=sys.stderr)
            return 1

    made = seed(store, tz, days=max(1, args.hari))
    print(f"  {made['trucks']} truk, {made['visits']} kunjungan, {made['bunches']} janjang")
    print(f"  {made['accounts']} akun")
    print()
    print(f"  Masuk konsol dengan sandi: {DEMO_PASSWORD}")
    for email, full_name, role in ACCOUNTS:
        print(f"    {email:<30} {full_name:<20} [{role}]")
    return 0


def guard(store: ConsoleStore) -> str | None:
    """Refuse to touch a database that already holds somebody's real day.

    A mill PC is the one place this script must never run, and the operator who runs it
    there will not have read the docstring. Demo rows do not count — re-seeding a demo
    is the normal case.
    """
    for row in store.trucks_semua():
        if row["id"] != truck_id_for(row["plate_number"] or ""):
            return "database ini punya truk yang bukan buatan demo"
    real = [op for op in store.operators() if op["origin"] == "erp"]
    if real:
        return f"database ini punya {len(real)} akun dari AutoERP"
    return None


def wipe(store: ConsoleStore) -> int:
    """Delete only what this script wrote, found by the plates it owns."""
    ids = {truck_id_for(p) for p in PLATES}
    removed = 0
    with store._lock, store._db:  # noqa: SLF001 — no public bulk-delete; this is a dev tool
        for table, column in (
            ("inspections", "truck_id"),
            ("weighings", "truck_id"),
            ("assignments", "truck_id"),
        ):
            cur = store._db.execute(  # noqa: SLF001
                f"DELETE FROM {table} WHERE {column} IN ({','.join('?' * len(ids))})", tuple(ids)
            )
            removed += cur.rowcount
        cur = store._db.execute(  # noqa: SLF001
            f"DELETE FROM trucks WHERE id IN ({','.join('?' * len(ids))})", tuple(ids)
        )
        removed += cur.rowcount
        for email, _name, _role in ACCOUNTS:
            cur = store._db.execute(  # noqa: SLF001
                "DELETE FROM operators WHERE id = ?", (operator_id_for(email),)
            )
            removed += cur.rowcount
    return removed


def seed(store: ConsoleStore, tz, days: int = DAYS) -> dict[str, int]:
    accounts = seed_accounts(store)
    trucks = seed_trucks(store)
    visits, bunches = seed_visits(store, tz, days=days)
    return {"accounts": accounts, "trucks": trucks, "visits": visits, "bunches": bunches}


def seed_accounts(store: ConsoleStore) -> int:
    """The two demo logins. Written as `lokal`, like `make operator` does — an `erp`
    row would be overwritten by the first pull from AutoERP."""
    made = 0
    for email, full_name, role in ACCOUNTS:
        if store.operator_by_email(email) is not None:
            continue
        store.upsert_operator_manual(
            {
                "email": email,
                "full_name": full_name,
                "password_hash": hash_password(DEMO_PASSWORD),
                "role": role,
            }
        )
        made += 1
    return made


def seed_trucks(store: ConsoleStore) -> int:
    for plate in PLATES:
        store.upsert_truck(
            {
                "id": truck_id_for(plate),
                "plate_number": plate,
                "supplier_id": None,
                "capacity": None,
                "status": "active",
                # Left empty on purpose: `erp_name` is written by the pull from AutoERP.
                # Filling it here would fake a link that was never made, and the console
                # would then believe a truck is synced when it is not.
                "erp_name": None,
            }
        )
    return len(PLATES)


def seed_visits(store: ConsoleStore, tz, days: int = DAYS) -> tuple[int, int]:
    now = datetime.now(tz)
    visits = bunches = 0

    for back in range(days - 1, -1, -1):
        day = now - timedelta(days=back)
        date_key = day.strftime("%Y%m%d")
        rng = random.Random(f"{SEED}:{date_key}")
        for i in range(rng.randint(*VISITS_PER_DAY)):
            # Seeded per visit, so a day that is partly present already fills in the
            # rest with the same numbers it would have had.
            vrng = random.Random(f"{SEED}:{date_key}:{i}")
            plate = PLATES[vrng.randrange(len(PLATES))]
            n = _seed_one_visit(store, tz, day, i, plate, vrng)
            visits += 1
            bunches += n
    return visits, bunches


def _seed_one_visit(store: ConsoleStore, tz, day, i: int, plate: str, rng) -> int:
    truck_id = truck_id_for(plate)
    line = LINES[i % len(LINES)]
    key = f"{day:%Y%m%d}:{i:03d}"
    assignment_id = _uid("assignment", key)

    # A visit occupies one slot in the working day, from 07:00 on.
    start = day.replace(hour=7, minute=0, second=0, microsecond=0) + timedelta(
        minutes=(i * 97) % 600
    )
    work_date = work_date_for(start.isoformat(), tz)

    gross = float(rng.randrange(*GROSS_RANGE, 10))
    tare = float(rng.randrange(TARE_RANGE[0], min(int(gross) - 2500, TARE_RANGE[1]), 10))
    store.upsert_weighing(
        {
            "id": _uid("weighing", key),
            "ref": f"TKT-{day:%y%m%d}-{i:03d}",
            "plate_number": plate,
            "plate_norm": normalisasi_plat(plate),
            "truck_id": truck_id,
            "work_date": work_date,
            "gross_kg": gross,
            "tare_kg": tare,
            "net_kg": gross - tare,
            "entered_at": start.isoformat(),
            "exited_at": (start + timedelta(hours=1)).isoformat(),
        }
    )
    store.link_weighing_to_assignment(_uid("weighing", key), assignment_id)

    total = rng.randint(*BUNCHES_PER_VISIT)
    rej_share = rng.uniform(*REJ_SHARE)
    for j in range(total):
        ts = start + timedelta(seconds=j * 20)
        rejected = rng.random() < rej_share
        # Among rejects, a few are Janjang Kosong rather than Unripe, so the grade-class
        # column on screen is not one repeated value.
        grade_class = ("JK" if rng.random() < JK_SHARE_OF_REJ else "Unripe") if rejected else "Ripe"
        store.add_inspection(
            {
                "event_id": _uid("bunch", f"{key}:{j}"),
                "machine_id": line,
                "line_code": line,
                "work_date": work_date,
                "timestamp": ts.isoformat(),
                "prediction": "Rej" if rejected else "Acc",
                "ripeness_status": "REJ" if rejected else "ACC",
                "grade_class": grade_class,
                "ripeness_confidence": round(rng.uniform(0.70, 0.79 if rejected else 0.98), 2),
                # Long stalks are only judged on fruit that was accepted; a rejected
                # bunch never reaches that check, so the column stays empty for it.
                "tp_status": None if rejected else ("FAIL" if rng.random() < 0.06 else "PASS"),
                "tp_confidence": None,
                "capture_type": "manual" if j == 3 else "auto",
                "image_path": f"captures/results/{work_date}/{line}_{j:04d}.webp",
                "truck_id": truck_id,
                "assignment_id": assignment_id,
            }
        )
    return total


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
