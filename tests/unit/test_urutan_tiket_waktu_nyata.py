"""Tickets ordered by the real instant, not by the ISO text (user's screenshot 2026-10-02).

The browser sends `...Z`, the demo seeder and the scale program `...+07:00`. As text,
"08:00+07:00" (01:00 UTC) sorts after "01:30Z", so a new ticket sat between older ones and
"the truck's newest ticket" could be the older one. SQLite `julianday()` reads both.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from palmgrade.repositories.console_repository import ConsoleStore

HARI = "2026-10-02"


def _tiket(store, wid, truck, entered_at, *, gross=14000.0):
    store.upsert_weighing({
        "id": wid, "ref": None, "plate_number": f"BE {truck}", "plate_norm": f"BE{truck}",
        "truck_id": truck, "work_date": HARI, "gross_kg": gross, "tare_kg": None,
        "net_kg": None, "entered_at": entered_at, "exited_at": None,
    })


@pytest.fixture
def store(tmp_path) -> ConsoleStore:
    return ConsoleStore(tmp_path / "console.db")


def _sejak() -> float:
    return time.time() - 3600


def test_tabel_timbangan_terbaru_dulu_menurut_waktu_nyata(store):
    _tiket(store, "lama", "C", f"{HARI}T08:00:00+07:00")  # 01:00 UTC, seeded
    _tiket(store, "baru", "B", f"{HARI}T01:30:00.123Z")  # 01:30 UTC, from the browser
    _tiket(store, "terbaru", "D", f"{HARI}T08:45:00+07:00")  # 01:45 UTC
    assert [w["id"] for w in store.weighings(HARI)] == ["terbaru", "baru", "lama"]


def test_tiket_tanpa_jam_isi_memakai_jam_terima(store):
    _tiket(store, "berjam", "A", "2020-01-01T01:00:00Z")
    _tiket(store, "tanpa", "B", None)  # received now, long after 2020
    assert [w["id"] for w in store.weighings(HARI)] == ["tanpa", "berjam"]


def test_jam_sama_persis_yang_terakhir_masuk_di_atas(store):
    for wid in ("w1", "w2", "w3"):
        _tiket(store, wid, wid, f"{HARI}T01:00:00Z")
    with store._lock, store._db:
        store._db.execute("UPDATE weighings SET received_at = 1000.0")
    assert [w["id"] for w in store.weighings(HARI)] == ["w3", "w2", "w1"]


def test_tiket_terbaru_truk_menurut_waktu_nyata_dan_antrean_sepakat(store):
    """Review Focus 4: the ticket a release links is the ticket the queue offers."""
    _tiket(store, "lama", "A", f"{HARI}T08:00:00+07:00")  # 01:00 UTC; as text the "newest"
    _tiket(store, "baru", "A", f"{HARI}T01:30:00Z")
    assert store.latest_weighing_for_truck_since("A", _sejak()) == "baru"
    assert [r["weighing_id"] for r in store.unloading_queue(_sejak())] == ["baru"]


def test_tiket_terbaru_sepakat_juga_tanpa_jam_isi(store):
    _tiket(store, "berjam", "A", "2020-01-01T01:00:00Z")
    _tiket(store, "tanpa", "A", None)
    assert store.latest_weighing_for_truck_since("A", _sejak()) == "tanpa"
    assert [r["weighing_id"] for r in store.unloading_queue(_sejak())] == ["tanpa"]


def test_tiket_terbaru_sepakat_saat_jam_isi_kembar(store):
    _tiket(store, "pertama", "A", f"{HARI}T01:00:00Z")
    _tiket(store, "kedua", "A", f"{HARI}T08:00:00+07:00")  # same instant, other spelling
    with store._lock, store._db:
        store._db.execute("UPDATE weighings SET received_at = ?", (time.time(),))
    terbaru = store.latest_weighing_for_truck_since("A", _sejak())
    assert terbaru == "kedua"
    assert [r["weighing_id"] for r in store.unloading_queue(_sejak())] == [terbaru]


def test_menunggu_timbang_urut_jam_datang_nyata(store):
    """Step 2's "Menunggu timbang" section lists the oldest arrival first."""
    for aid, plat, jam in (("a1", "BE 1", f"{HARI}T08:20:00+07:00"),  # 01:20 UTC
                           ("a2", "BE 2", f"{HARI}T01:10:00.000Z"),
                           ("a3", "BE 3", f"{HARI}T08:05:00+07:00")):  # 01:05 UTC
        store.record_arrival({"id": aid, "plate_number": plat, "plate_norm": plat.replace(" ", ""),
                              "truck_id": plat, "work_date": HARI, "arrived_at": jam})
    assert [a["plate_number"] for a in store.waiting_arrivals(HARI)] == ["BE 3", "BE 2", "BE 1"]


def test_tiket_terbuka_truk_terbaru_dulu_menurut_waktu_nyata(store):
    """Which open ticket a tare goes to: the same order as the table and the queue."""
    _tiket(store, "lama", "A", f"{HARI}T08:00:00+07:00")  # 01:00 UTC; as text the "newest"
    _tiket(store, "baru", "A", f"{HARI}T01:30:00Z")
    sejak = datetime(2026, 10, 2, tzinfo=UTC).timestamp()
    assert [w["id"] for w in store.open_weighings_for_truck("A", sejak)] == ["baru", "lama"]
    assert store.latest_weighing_for_truck_since("A", _sejak()) == "baru"
