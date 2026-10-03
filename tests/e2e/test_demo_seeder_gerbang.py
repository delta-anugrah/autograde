"""`make demo` mengisi jam datang dan jam keluar gerbang."""
from __future__ import annotations

import importlib.util
import pathlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from palmgrade.domain.plate import normalisasi_plat, truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore

AKAR = pathlib.Path(__file__).resolve().parents[2]
WIB = ZoneInfo("Asia/Jakarta")


def _muat_seeder():
    spec = importlib.util.spec_from_file_location("seed_console_demo", AKAR / "scripts" / "seed-console-demo.py")
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def _tiket(store, seeder, key, plate, start):
    store.upsert_weighing({
        "id": seeder._uid("weighing", key), "ref": None, "plate_number": plate,
        "plate_norm": normalisasi_plat(plate), "truck_id": truck_id_for(plate),
        "work_date": start.strftime("%Y-%m-%d"), "gross_kg": 14000.0, "tare_kg": 6000.0,
        "net_kg": 8000.0, "entered_at": start.isoformat(),
        "exited_at": (start + timedelta(hours=1)).isoformat(),
    })


def test_kunjungan_demo_punya_jam_gerbang_yang_masuk_akal(tmp_path):
    seeder = _muat_seeder()
    store = ConsoleStore(tmp_path / "console.db")
    plate = seeder.PLATES[0]
    start = datetime(2026, 9, 29, 8, 0, tzinfo=WIB)
    for i in range(40):
        key = f"20260929:{i:03d}"
        mulai = start + timedelta(minutes=10 * i)
        _tiket(store, seeder, key, plate, mulai)
        seeder._seed_gerbang(store, WIB, key, plate, truck_id_for(plate), mulai)
        row = store.weighing(seeder._uid("weighing", key))
        assert datetime.fromisoformat(row["left_at"]) > datetime.fromisoformat(row["exited_at"])
    dengan_datang = 0
    for row in store.weighings("2026-09-29", limit=100):
        if row["arrived_at"]:
            dengan_datang += 1
            selisih = datetime.fromisoformat(row["entered_at"]) - datetime.fromisoformat(row["arrived_at"])
            assert timedelta(minutes=5) <= selisih <= timedelta(minutes=90)
    assert dengan_datang >= 30


def test_seed_ulang_tidak_menggandakan(tmp_path):
    seeder = _muat_seeder()
    store = ConsoleStore(tmp_path / "console.db")
    plate = seeder.PLATES[0]
    start = datetime(2026, 9, 29, 8, 0, tzinfo=WIB)
    _tiket(store, seeder, "20260929:000", plate, start)
    for _ in range(2):
        seeder._seed_gerbang(store, WIB, "20260929:000", plate, truck_id_for(plate), start)
    assert len(store.weighings("2026-09-29")) == 1


def test_wipe_menghapus_kedatangan_demo(tmp_path):
    seeder = _muat_seeder()
    store = ConsoleStore(tmp_path / "console.db")
    plate = seeder.PLATES[0]
    store.record_arrival({"id": "a-demo", "plate_number": plate, "plate_norm": normalisasi_plat(plate),
                          "truck_id": truck_id_for(plate), "work_date": "2026-09-29",
                          "arrived_at": "2026-09-29T00:30:00+00:00"})
    seeder.wipe(store)
    assert store.arrival("a-demo") is None


def test_wipe_juga_menghapus_kedatangan_demo_yang_dibatalkan(tmp_path):
    """A cancelled arrival is kept as history (round 4); `make demo-reset` still clears it."""
    seeder = _muat_seeder()
    store = ConsoleStore(tmp_path / "console.db")
    plate = seeder.PLATES[0]
    store.record_arrival({"id": "a-batal", "plate_number": plate, "plate_norm": normalisasi_plat(plate),
                          "truck_id": truck_id_for(plate), "work_date": "2026-09-29",
                          "arrived_at": "2026-09-29T00:30:00+00:00"})
    store.cancel_arrival("a-batal", cancelled_at="2026-09-29T00:40:00+00:00", cancelled_by="op@pks.test")
    seeder.wipe(store)
    assert store.arrival("a-batal") is None
    assert store.cancelled_arrivals("2026-09-29") == []

