"""Opening a console database written by an older build must not lose accounts.

The column rename `nama`→`full_name`, `asal`→`origin`, `dibuat_at`→`created_at`,
`peran`→`role` shipped without a data migration, on the reasoning that no factory PC
had ever run that schema. That held for factory PCs and not for developer machines,
where the console then read a column the table did not have: every account came back
with a blank name, so the sign-in screen drew empty pills and the navbar showed no
operator. `role` alone survived, because it was added as a *new* column defaulting to
`operator` — which silently demoted every support account that predated the rename.

What is pinned here: the rename carries the values across, the role is carried over
rather than defaulted, an already-renamed database is left alone, and the oldest
PIN-era shape is still dropped rather than migrated.
"""
from __future__ import annotations

import sqlite3
import time

from palmgrade.repositories.console_repository import ConsoleStore

# The `operators` table exactly as the pre-rename build created it.
_PRE_RENAME_SQL = """
CREATE TABLE operators (
    id             TEXT PRIMARY KEY,
    email          TEXT NOT NULL UNIQUE,
    nama           TEXT NOT NULL,
    password_hash  TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active',
    asal           TEXT NOT NULL DEFAULT 'lokal',
    erp_name       TEXT,
    dibuat_at      REAL NOT NULL,
    gagal_count    INTEGER NOT NULL DEFAULT 0,
    gagal_terakhir REAL,
    peran          TEXT NOT NULL DEFAULT 'operator'
);
"""


def _pre_rename_db(path, rows=()):
    """A console database as an older build left it, with `rows` already in it."""
    db = sqlite3.connect(str(path))
    db.executescript(_PRE_RENAME_SQL)
    for row in rows:
        db.execute(
            """INSERT INTO operators (id, email, nama, password_hash, status, asal,
                                      erp_name, dibuat_at, gagal_count, peran)
               VALUES (:id, :email, :nama, :hash, :status, :asal, :erp_name,
                       :dibuat_at, :gagal_count, :peran)""",
            {
                "erp_name": None,
                "status": "active",
                "asal": "lokal",
                "dibuat_at": time.time(),
                "gagal_count": 0,
                "peran": "operator",
                "hash": "scrypt$x",
                **row,
            },
        )
    db.commit()
    db.close()
    return path


def _columns(path, table="operators"):
    db = sqlite3.connect(str(path))
    try:
        return {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
    finally:
        db.close()


def test_rename_keeps_the_accounts_and_their_names(tmp_path):
    """The bug itself: a pre-rename database used to read back blank names."""
    path = _pre_rename_db(
        tmp_path / "console.db",
        [
            {"id": "op-1", "email": "operator@pks.test", "nama": "Pak Budi"},
            {"id": "op-2", "email": "support3@example.com", "nama": "Support 3", "peran": "support"},
        ],
    )

    store = ConsoleStore(path)

    columns = _columns(path)
    assert {"full_name", "origin", "created_at", "role"} <= columns
    assert not {"nama", "asal", "dibuat_at", "peran"} & columns

    rows = {r["email"]: r for r in store.operators()}
    assert rows["operator@pks.test"]["full_name"] == "Pak Budi"
    assert rows["support3@example.com"]["full_name"] == "Support 3"


def test_the_support_role_survives_the_rename(tmp_path):
    """`role` used to be added as a new column defaulting to `operator`, so a support
    account came back demoted — it kept its name but lost the developer menus."""
    path = _pre_rename_db(
        tmp_path / "console.db",
        [
            {"id": "op-1", "email": "support3@example.com", "nama": "Support 3", "peran": "support"},
            {"id": "op-2", "email": "operator@pks.test", "nama": "Pak Budi", "peran": "operator"},
        ],
    )

    ConsoleStore(path)

    db = sqlite3.connect(str(path))
    db.row_factory = sqlite3.Row
    try:
        roles = {r["email"]: r["role"] for r in db.execute("SELECT email, role FROM operators")}
    finally:
        db.close()
    assert roles == {"support3@example.com": "support", "operator@pks.test": "operator"}


def test_a_half_migrated_database_is_finished_off(tmp_path):
    """The shape this machine was actually found in: `role` added by the earlier
    migration while `peran` and the other Indonesian columns were still there."""
    path = tmp_path / "console.db"
    _pre_rename_db(path, [{"id": "op-1", "email": "support3@example.com", "nama": "Support 3", "peran": "support"}])
    db = sqlite3.connect(str(path))
    db.execute("ALTER TABLE operators ADD COLUMN role TEXT NOT NULL DEFAULT 'operator'")
    db.commit()
    db.close()

    ConsoleStore(path)

    columns = _columns(path)
    assert "peran" not in columns and "nama" not in columns
    db = sqlite3.connect(str(path))
    db.row_factory = sqlite3.Row
    try:
        row = db.execute("SELECT full_name, role FROM operators").fetchone()
    finally:
        db.close()
    assert (row["full_name"], row["role"]) == ("Support 3", "support")


def test_an_already_renamed_database_is_left_alone(tmp_path):
    """Opening twice must be a no-op the second time."""
    path = _pre_rename_db(
        tmp_path / "console.db", [{"id": "op-1", "email": "operator@pks.test", "nama": "Pak Budi"}]
    )
    ConsoleStore(path)
    store = ConsoleStore(path)

    rows = store.operators()
    assert [r["full_name"] for r in rows] == ["Pak Budi"]
    assert _columns(path) >= {"full_name", "origin", "created_at", "role"}


def test_the_pin_era_table_is_still_dropped(tmp_path):
    """Older than the rename: keyed by name with no email, so it cannot be carried."""
    path = tmp_path / "console.db"
    db = sqlite3.connect(str(path))
    db.executescript(
        """CREATE TABLE operators (
               id TEXT PRIMARY KEY, nama TEXT NOT NULL, pin_hash TEXT NOT NULL
           );"""
    )
    db.execute("INSERT INTO operators VALUES ('op-1', 'Pak Budi', 'x')")
    db.commit()
    db.close()

    store = ConsoleStore(path)

    assert store.operators() == []
    assert _columns(path) >= {"email", "full_name", "role"}
