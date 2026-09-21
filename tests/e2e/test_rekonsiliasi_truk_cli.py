"""End-to-end OPS-2: `make rekonsiliasi-truk` against a real database file.

The unit tests call `rekonsiliasi_truk()` directly. What they cannot cover is the
part the person installing a mill PC actually touches: the Makefile target, the
`TULIS` flag, the exit codes, and the fact that look-only really writes nothing to
a file on disk. That is what runs here — a real subprocess, a real SQLite file, no
fakes and no in-process shortcuts.

Not skipped and needs no services: the script's only dependency is a database path,
which the fixture builds. It is the one E2E in this suite that can run anywhere,
and it is kept out of `tests/unit` deliberately — it spawns processes and touches
the filesystem, which the unit suite must not do.

⚠️ The `_cli` suffix is load-bearing. There is no `__init__.py` under `tests/`, so
pytest imports test modules by basename: two files called `test_rekonsiliasi_truk.py`
in `unit/` and `e2e/` collide, and collection fails for BOTH. CI only runs
`tests/unit/`, so it stays green and the clash only appears when someone runs the two
suites together. Give every E2E file a basename no unit file uses.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from palmgrade.domain.plate import truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "rekonsiliasi-truk.py"

# The shape palmgrade-api leaves behind: uuid4, unrelated to the plate.
ID_LAMA = "7f3a9b21-0000-4000-8000-00000000000{}"


def _run(db: Path, *args: str) -> subprocess.CompletedProcess:
    """The script as the installer runs it: its own process, its own interpreter."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--db", str(db), *args],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
        cwd=str(REPO),
    )


@pytest.fixture
def factory_db(tmp_path) -> Path:
    """A database shaped like a mill PC that has been running on palmgrade-api.

    Four trucks with random ids, one of them already twinned by an ERP pull, plus
    one row whose plate is unreadable — the case that must not abort the rest.
    """
    path = tmp_path / "console.db"
    store = ConsoleStore(path)
    plates = ["BE 4412 OFL", "be-9012-tt", "BG 1234 AB", "BE 7788 QQ"]

    for i, p in enumerate(plates, 1):
        tid = ID_LAMA.format(i)
        store.upsert_truck({"id": tid, "plate_number": p, "status": "active"})
        store.upsert_weighing(
            {
                "id": f"w-{i}",
                "ref": None,
                "plate_number": p,
                "plate_norm": p.replace(" ", "").replace("-", "").upper(),
                "truck_id": tid,
                "work_date": "2026-09-15",
                "gross_kg": 13000.0,
                "tare_kg": 5000.0,
                "net_kg": 8000.0,
                "entered_at": "2026-09-15T08:00:00+07:00",
                "exited_at": "2026-09-15T09:00:00+07:00",
            }
        )

    # One truck already pulled from AutoERP: this is the twin.
    store.upsert_truck(
        {
            "id": truck_id_for("BE 4412 OFL"),
            "plate_number": "BE 4412 OFL",
            "status": "active",
            "erp_name": "TRK-0001",
        }
    )
    store.upsert_truck({"id": "rusak-1", "plate_number": None, "status": "active"})
    return path


def _net(db: Path) -> float:
    con = sqlite3.connect(db)
    try:
        return con.execute("SELECT COALESCE(SUM(net_kg), 0) FROM weighings").fetchone()[0]
    finally:
        con.close()


def _dangling(db: Path) -> dict[str, int]:
    """Rows pointing at a truck id that no longer exists — the failure that empties
    the recap without any error anywhere."""
    con = sqlite3.connect(db)
    try:
        return {
            t: con.execute(
                f"SELECT COUNT(*) FROM {t} WHERE truck_id IS NOT NULL"
                "  AND truck_id NOT IN (SELECT id FROM trucks)"
            ).fetchone()[0]
            for t in ("weighings", "inspections", "assignments")
        }
    finally:
        con.close()


def _twin_plates(db: Path) -> int:
    con = sqlite3.connect(db)
    try:
        return con.execute(
            """SELECT COUNT(*) FROM (
                   SELECT 1 FROM trucks WHERE plate_number IS NOT NULL
                   GROUP BY UPPER(REPLACE(REPLACE(plate_number, ' ', ''), '-', ''))
                   HAVING COUNT(*) > 1)"""
        ).fetchone()[0]
    finally:
        con.close()


def _isi(db: Path) -> dict[str, list]:
    """Every row of every table, which is what "writes nothing" has to mean here.

    Not the raw bytes. `ConsoleStore` sets `PRAGMA journal_mode=WAL` on open, and on
    a database that is not yet in WAL mode that rewrites 4 bytes of the file header
    before a single statement runs — measured, on a table with no rows. Comparing
    bytes therefore fails on a machine whose fixture file starts in rollback mode
    even though the data is untouched, which is exactly what it did the first time
    this suite ran in CI.
    """
    con = sqlite3.connect(db)
    try:
        tabel = [
            r[0]
            for r in con.execute(
                "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
            )
        ]
        return {t: con.execute(f"select * from {t} order by 1").fetchall() for t in tabel}
    finally:
        con.close()


def test_dry_run_does_not_touch_the_file(factory_db):
    """Run first to read before deciding. If this mode also wrote, there would be
    no safe way to check the result before changing the mill's data."""
    before = _isi(factory_db)

    result = _run(factory_db)

    assert result.returncode == 0, result.stderr
    assert "lihat saja" in result.stdout
    assert _isi(factory_db) == before, "the data changed even though this is dry-run mode"


def test_the_report_names_plates_so_a_person_can_match_them(factory_db):
    """Read in the factory PC's terminal while holding truck records."""
    result = _run(factory_db)

    assert "BE 4412 OFL" in result.stdout
    assert "PERLU DIPERIKSA ORANG" in result.stdout
    assert "rusak-1" in result.stdout


def test_tonnage_does_not_shift_by_even_one_kilo(factory_db):
    """This is the entire stake: net weight is the figure the farmer gets paid on.
    Trucks may be merged, tonnage must not move by a single kilo."""
    before = _net(factory_db)

    _run(factory_db, "--tulis")

    assert _net(factory_db) == before == 32000.0


def test_no_row_is_left_dangling_afterwards(factory_db):
    """`truck_id` lives in three tables. Miss one and that row disappears from the
    recap with no error anywhere — the hardest kind of failure to notice."""
    _run(factory_db, "--tulis")

    assert _dangling(factory_db) == {"weighings": 0, "inspections": 0, "assignments": 0}


def test_twin_trucks_disappear_and_erp_name_survives(factory_db):
    assert _twin_plates(factory_db) == 1

    _run(factory_db, "--tulis")

    assert _twin_plates(factory_db) == 0
    con = sqlite3.connect(factory_db)
    try:
        assert con.execute("SELECT COUNT(*) FROM trucks WHERE erp_name='TRK-0001'").fetchone()[0] == 1
    finally:
        con.close()


def test_running_it_twice_is_safe(factory_db):
    """Whoever runs this is juggling ten other things and often unsure whether it
    already ran."""
    _run(factory_db, "--tulis")
    after_first = _net(factory_db)

    second = _run(factory_db, "--tulis")

    assert "digabung : 0" in second.stdout
    assert "dipindah : 0" in second.stdout
    assert _net(factory_db) == after_first


def test_the_exit_code_flags_what_needs_a_person(factory_db):
    """Not a failure — the rest has already been fixed. But it must be non-zero, or
    the exception list slides straight past an installation script."""
    assert _run(factory_db, "--tulis").returncode == 2


def test_a_missing_database_is_refused_not_created(tmp_path):
    """A typo in the path must not produce an empty database that reads like a
    mill with no trucks."""
    missing = tmp_path / "tidak-ada.db"

    result = _run(missing)

    assert result.returncode == 1
    assert not missing.exists(), "the script created a new database from a mistyped path"


def test_a_fresh_pc_with_no_trucks_reports_nothing_to_do(tmp_path):
    """A brand-new mill runs this too (the install checklist does not branch), and
    the result must say plainly that there is nothing to do."""
    empty = tmp_path / "console.db"
    ConsoleStore(empty)

    result = _run(empty)

    assert result.returncode == 0
    assert "Tidak ada yang perlu dibetulkan" in result.stdout


# ── finding its own database ─────────────────────────────────────────────────
# Found on the Lampung PC 2026-09-15: `make rekonsiliasi-truk` on the host
# answered "Database konsol tidak ada" even though 53 MB of it sat right
# there. Compose mounts `./state/console:/app/state`, so from the HOST the
# file is at `state/console/console.db` while from INSIDE the container it is
# `state/console.db`. A script that only knows one shape dies in one of the
# two places, and whoever is running it is in the middle of installing a
# factory PC.


def test_both_path_shapes_are_searched():
    """What is guarded: the candidate list carries BOTH the native shape and the
    host-Docker shape."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("rekon_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    candidates = [str(p) for p in module._kandidat_db()]

    assert any(p.endswith("state/console.db") for p in candidates), candidates
    assert any(p.endswith("state/console/console.db") for p in candidates), candidates


def test_both_locations_are_named_when_truly_missing(tmp_path):
    """When it really is missing, the message must name BOTH searched locations —
    naming only one leads the reader to conclude a wrong checkout when the
    database is actually there."""
    result = _run(tmp_path / "tidak-ada.db")

    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "state/console.db" in combined
    assert "state/console/console.db" in combined
    assert "--db" in combined, "the way out must be named"
