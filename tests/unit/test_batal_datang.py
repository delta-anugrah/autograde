"""Batal datang (user 2026-10-03): an arrival that will not be weighed is taken back.

Picked the wrong truck in the dropdown, or the truck was turned away at the gate. Only a
WAITING arrival can be cancelled; it then never shows in `waiting`, is never claimed by a
weigh-in, and (like every gate time) never reaches AutoERP. Answers, not exceptions.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.gerbang import DIBATALKAN, TIDAK_ADA, baca_waktu
from palmgrade.domain.plate import truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.gate_service import GateService

PLAT = "BE 7742 ZB"
DATANG = "2026-10-01T01:00:00Z"
OLEH = "operator@pks.test"


@pytest.fixture
def konsol(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    service = ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), store, None)
    return service, GateService(store, service.tz), store


def _id_menunggu(service, jam="2026-10-01T01:05:00Z"):
    return [a["id"] for a in service.waiting_arrivals(baca_waktu(jam))]


def test_kedatangan_menunggu_dibatalkan(konsol, caplog):
    service, gate, store = konsol
    gate.arrive(PLAT, DATANG)
    [arrival_id] = _id_menunggu(service)

    with caplog.at_level(logging.INFO, logger="palmgrade.services.gate_service"):
        jawab = gate.cancel_arrival(arrival_id, oleh=OLEH)

    assert jawab == {"hasil": DIBATALKAN, "plate_number": "BE7742ZB"}
    assert _id_menunggu(service) == []
    assert store.arrival(arrival_id) is None
    assert any(PLAT.replace(" ", "") in r.getMessage() and OLEH in r.getMessage() for r in caplog.records)


def test_dua_kali_dibatalkan_jawaban_kedua_tidak_ada(konsol):
    service, gate, _ = konsol
    gate.arrive(PLAT, DATANG)
    [arrival_id] = _id_menunggu(service)
    assert gate.cancel_arrival(arrival_id, oleh=OLEH)["hasil"] == DIBATALKAN
    assert gate.cancel_arrival(arrival_id, oleh=OLEH) == {"hasil": TIDAK_ADA}


def test_id_tak_dikenal_tidak_ada(konsol):
    _, gate, _ = konsol
    assert gate.cancel_arrival("bukan-id", oleh=OLEH) == {"hasil": TIDAK_ADA}


def test_kedatangan_yang_sudah_diklaim_tidak_bisa_dibatalkan(konsol):
    service, gate, store = konsol
    gate.arrive(PLAT, DATANG)
    [arrival_id] = _id_menunggu(service)
    asyncio.run(service.record_weighing({"plate_number": PLAT, "gross_kg": 14000, "entered_at": "2026-10-01T01:30:00Z"}))

    assert gate.cancel_arrival(arrival_id, oleh=OLEH) == {"hasil": TIDAK_ADA}
    assert store.arrival(arrival_id)["weighing_id"] is not None


def test_yang_dibatalkan_tidak_diklaim_timbang_isi(konsol):
    service, gate, _ = konsol
    gate.arrive(PLAT, DATANG)
    [arrival_id] = _id_menunggu(service)
    gate.cancel_arrival(arrival_id, oleh=OLEH)

    row = asyncio.run(service.record_weighing(
        {"plate_number": PLAT, "gross_kg": 14000, "entered_at": "2026-10-01T01:30:00Z"}))
    [tiket] = service.weighings(row["work_date"])
    assert (tiket["arrived_at"], tiket["tanpa_scan_1"]) == (None, True)


def test_truk_lain_tidak_tersentuh(konsol):
    service, gate, store = konsol
    gate.arrive(PLAT, DATANG)
    gate.arrive("BE 1 AA", DATANG)
    [a1, a2] = _id_menunggu(service)
    gate.cancel_arrival(a1, oleh=OLEH)
    assert _id_menunggu(service) == [a2]
    assert store.waiting_arrivals_for_truck(truck_id_for("BE 1 AA")) != []
