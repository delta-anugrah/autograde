"""Query panas konsol memakai indeks, bukan memindai seluruh janjang (batch 2.5).

Bukti dari EXPLAIN QUERY PLAN query yang benar-benar dijalankan method-nya
(`tests/rencana_query.py`). Hasil sisiran lengkap: rencana batch 2 stream B, Task 6.
"""
from __future__ import annotations

import re
import sqlite3

import pytest
from rencana_query import rencana

from palmgrade.repositories.console_repository import ConsoleStore

INDEKS_BARU = ("idx_inspections_assignment", "idx_weighings_assignment", "idx_auto_releases_waktu")
HARI = "2026-09-20"
SCAN_JANJANG = re.compile(r"\bSCAN (inspections|i)\b")


def _janjang(n: int, assignment_id: str | None) -> dict:
    return {
        "event_id": f"ev-{n}", "machine_id": "m-1", "line_code": "line-1", "work_date": HARI,
        "timestamp": f"{HARI}T07:{n:02d}:00+07:00", "ripeness_status": "ACC" if n % 3 else "REJ",
        "ripeness_confidence": 0.9, "capture_type": "auto", "image_path": None, "truck_id": "t1",
        "assignment_id": assignment_id, "prediction": "Acc" if n % 3 else "Rej",
        "tp_status": None, "tp_confidence": 0.9 if n % 4 == 0 else None,
    }


def _tiket(weighing_id: str) -> dict:
    return {
        "id": weighing_id, "ref": None, "plate_number": "BE 1 AA", "plate_norm": "BE1AA",
        "truck_id": "t1", "work_date": HARI, "gross_kg": 14560.0, "tare_kg": None, "net_kg": None,
        "entered_at": f"{HARI}T07:00:00+07:00", "exited_at": None,
    }


def _indeks(store: ConsoleStore) -> set[str]:
    return {r[0] for r in store._db.execute("SELECT name FROM sqlite_master WHERE type='index'")}


@pytest.fixture
def store(tmp_path) -> ConsoleStore:
    return ConsoleStore(tmp_path / "console.db")


@pytest.mark.parametrize(
    "panggil, indeks",
    [
        (lambda s: s.grading_counts("a1"), "idx_inspections_assignment (assignment_id=?)"),
        (lambda s: s.bunches_for_visit("w1"), "idx_inspections_assignment (assignment_id=?)"),
        (lambda s: s.grading_counts_for_visit("w1"), "idx_inspections_assignment (assignment_id=?)"),
        # Sejak 2026-10-01 tautan dibaca dari `visit_assignments`, kuncinya penugasan itu sendiri.
        (lambda s: s.weighing_for_assignment("a1"), "sqlite_autoindex_visit_assignments_1 (assignment_id=?)"),
        (lambda s: s.auto_releases_terbaru(), "idx_auto_releases_waktu (released_at>?)"),
        # Sejak 2026-10-01 tiket truk dicari lewat jendela waktu, bukan hari kerja.
        (lambda s: s.latest_weighing_for_truck_since("t1", 0.0), "idx_weighings_truck (truck_id=? AND received_at>?)"),
    ],
    ids=["grading_counts", "bunches_for_visit", "grading_counts_for_visit", "weighing_for_assignment",
         "auto_releases_terbaru", "latest_weighing_for_truck_since"],
)
def test_query_penugasan_dan_pelepasan_memakai_indeksnya(store, panggil, indeks):
    [plan] = rencana(store._db, lambda: panggil(store))

    assert indeks in plan, plan
    assert "SCAN" not in plan, plan


@pytest.mark.parametrize(
    "panggil",
    [lambda s: s.unloading_queue(0.0), lambda s: s.trucks_with_open_ticket(0.0)],
    ids=["unloading_queue", "trucks_with_open_ticket"],
)
def test_antrean_bongkar_dibaca_lewat_indeks_tiket_terbuka(store, panggil):
    """Dibaca tiap 2 detik. `SCAN a` di subquery antrean = tabel `assignments`, satu baris per
    line; yang tidak boleh adalah memindai `weighings`, tabel yang tidak pernah dibersihkan."""
    [plan] = rencana(store._db, lambda: panggil(store))

    assert "idx_weighings_terbuka (received_at>?)" in plan, plan
    assert not re.search(r"\bSCAN (weighings|w)\b", plan), plan


def test_antrean_bongkar_urut_dari_indeks_tanpa_sortir_ulang(store):
    [plan] = rencana(store._db, lambda: store.unloading_queue(0.0))

    assert "TEMP B-TREE" not in plan, plan


@pytest.mark.parametrize("panggil", [lambda s: s.auto_releases_terbaru()], ids=["auto_releases_terbaru"])
def test_urutan_datang_dari_indeks_tanpa_sortir_ulang(store, panggil):
    [plan] = rencana(store._db, lambda: panggil(store))

    assert "TEMP B-TREE" not in plan, plan


HOT = {
    "summary": lambda s: s.summary(HARI),
    "inspections": lambda s: s.inspections(HARI),
    "inspections_line": lambda s: s.inspections(HARI, line_code="line-1"),
    "inspections_truk": lambda s: s.inspections(HARI, truck_id="t1"),
    "inspection_count": lambda s: s.inspection_count(HARI),
    "inspection_count_line": lambda s: s.inspection_count(HARI, line_code="line-1"),
    "inspection_count_truk": lambda s: s.inspection_count(HARI, truck_id="t1"),
    "truck_recap": lambda s: s.truck_recap(HARI),
    "grading_counts": lambda s: s.grading_counts("a1"),
    "grading_counts_for_visit": lambda s: s.grading_counts_for_visit("w1"),
    "bunches_for_visit": lambda s: s.bunches_for_visit("w1"),
}


@pytest.mark.parametrize("nama", sorted(HOT))
def test_tidak_ada_query_panas_yang_memindai_seluruh_janjang(store, nama):
    for plan in rencana(store._db, lambda: HOT[nama](store)):
        assert not SCAN_JANJANG.search(plan), f"{nama}: {plan}"


def test_database_lama_mendapat_indeks_tanpa_mengubah_isi(tmp_path):
    """`state/console.db` Lampung = skema hari ini tanpa tiga indeks ini."""
    path = tmp_path / "console.db"
    lama = ConsoleStore(path)
    for n in range(12):
        lama.add_inspection(_janjang(n, "a1" if n < 10 else None))
    lama.upsert_weighing(_tiket("w1"))
    lama.link_weighing_to_assignment("w1", "a1")
    lama.record_auto_release(line_code="line-1", truck_id="t1", plate_number="BE 1 AA", assignment_id="a1")
    with lama._lock, lama._db:
        for nama in INDEKS_BARU:
            lama._db.execute(f"DROP INDEX {nama}")
    sebelum = (lama.grading_counts("a1"), lama.bunches_for_visit("w1"),
               lama.weighing_for_assignment("a1"), len(lama.auto_releases_terbaru()))
    lama._db.close()

    baru = ConsoleStore(path)

    assert set(INDEKS_BARU) <= _indeks(baru)
    assert (baru.grading_counts("a1"), baru.bunches_for_visit("w1"),
            baru.weighing_for_assignment("a1"), len(baru.auto_releases_terbaru())) == sebelum


def test_versi_lama_tetap_bisa_menulis_ke_database_berindeks(tmp_path):
    """Rollback (`autograde use <versi lama>`): build lama tidak kenal indeks ini, SQLite
    yang merawatnya. Tulis dengan SQL build lama, lalu baca lagi dengan build ini."""
    path = tmp_path / "console.db"
    ConsoleStore(path)._db.close()
    db = sqlite3.connect(str(path))
    db.execute(
        """INSERT OR IGNORE INTO inspections (event_id, machine_id, line_code, work_date, timestamp,
               ripeness_status, capture_type, assignment_id, received_at)
           VALUES ('ev-lama', 'm', 'line-1', ?, ?, 'ACC', 'auto', 'a-lama', 0)""",
        (HARI, f"{HARI}T07:00:00+07:00"),
    )
    db.commit()
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    db.close()

    assert ConsoleStore(path).grading_counts("a-lama")["total"] == 1
