"""`waiting_arrivals`: menit tunggu dari jam server; jam rusak atau mundur = None, bukan 0."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from palmgrade.core.config import Settings
from palmgrade.domain.plate import truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService

PLAT = "BE 4412 OFL"


def _konsol(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    return ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), store, None), store


def _datang(store, id_, jam, hari):
    store.record_arrival({
        "id": id_, "plate_number": PLAT, "plate_norm": "BE4412OFL", "truck_id": truck_id_for(PLAT),
        "work_date": hari, "arrived_at": jam,
    })


def test_menit_tunggu_dari_jam_server(tmp_path):
    service, store = _konsol(tmp_path)
    jam = (datetime.now(UTC) - timedelta(minutes=12)).isoformat()
    _datang(store, "a1", jam, "2026-09-30")
    [baris] = service.waiting_arrivals("2026-09-30")
    assert baris["menit"] in (12, 13)


def test_jam_mundur_atau_rusak_bukan_nol_menit(tmp_path):
    service, store = _konsol(tmp_path)
    _datang(store, "a1", (datetime.now(UTC) + timedelta(hours=2)).isoformat(), "2026-09-30")
    _datang(store, "a2", "bukan-jam", "2026-09-30")
    menit = {b["arrived_at"][:5]: b["menit"] for b in service.waiting_arrivals("2026-09-30")}
    assert list(menit.values()) == [None, None]
