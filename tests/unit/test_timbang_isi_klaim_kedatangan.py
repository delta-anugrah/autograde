"""Timbang isi mengklaim kedatangan truknya, dari jalur mana pun tiketnya dibuka, dan
jam gerbang tidak pernah naik ke AutoERP."""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.erp_messages import visit_message
from palmgrade.domain.gerbang import baca_waktu
from palmgrade.domain.plate import truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.gate_service import GateService

PLAT = "BE 4412 OFL"


class _AntreanPalsu:
    def __init__(self) -> None:
        self.visits: list[str] = []

    def visit(self, weighing_id, tz=None):
        self.visits.append(weighing_id)

    def truck(self, plate):
        pass


@pytest.fixture
def pabrik(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    antrean = _AntreanPalsu()
    service = ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), store, None, erp_queue=antrean)
    return service, GateService(store, service.tz), store, antrean


def _isi(service, jam):
    return asyncio.run(service.record_weighing({"plate_number": PLAT, "gross_kg": 14000, "entered_at": jam}))


def _kosong(service, jam_masuk, jam_keluar):
    return asyncio.run(service.record_weighing({
        "plate_number": PLAT, "entered_at": jam_masuk, "tare_kg": 6000, "exited_at": jam_keluar,
    }))


def test_timbang_isi_mengklaim_kedatangan_truknya(pabrik):
    service, gate, store, _ = pabrik
    gate.arrive(PLAT, "2026-09-30T00:30:00+00:00")
    row = _isi(service, "2026-09-30T01:00:00+00:00")
    [tiket] = service.weighings(row["work_date"])
    assert tiket["arrived_at"] == "2026-09-30T00:30:00+00:00"
    assert (tiket["antre_menit"], tiket["tanpa_scan_1"]) == (30, False)
    assert store.waiting_arrivals_for_truck(truck_id_for(PLAT)) == []


def test_tanpa_scan_1_ditandai(pabrik):
    service, _, _, _ = pabrik
    row = _isi(service, "2026-09-30T01:00:00+00:00")
    [tiket] = service.weighings(row["work_date"])
    assert (tiket["arrived_at"], tiket["antre_menit"], tiket["tanpa_scan_1"]) == (None, None, True)


def test_total_sesudah_keluar_gerbang(pabrik):
    service, gate, _, _ = pabrik
    gate.arrive(PLAT, "2026-09-30T00:30:00+00:00")
    _isi(service, "2026-09-30T01:00:00+00:00")
    row = _kosong(service, "2026-09-30T01:00:00+00:00", "2026-09-30T02:00:00+00:00")
    gate.leave(PLAT, "2026-09-30T02:30:00+00:00")
    assert service.weighings(row["work_date"])[0]["total_menit"] == 120


def test_kedatangan_truk_lain_tidak_diklaim(pabrik):
    service, gate, store, _ = pabrik
    gate.arrive("BE 1 AA", "2026-09-30T00:30:00+00:00")
    _isi(service, "2026-09-30T01:00:00+00:00")
    assert len(store.waiting_arrivals_for_truck(truck_id_for("BE 1 AA"))) == 1


def test_dua_kunjungan_sehari_masing_masing_antrenya(pabrik):
    service, gate, _, _ = pabrik
    gate.arrive(PLAT, "2026-09-30T00:30:00+00:00")
    _isi(service, "2026-09-30T01:00:00+00:00")
    _kosong(service, "2026-09-30T01:00:00+00:00", "2026-09-30T02:00:00+00:00")
    gate.arrive(PLAT, "2026-09-30T05:00:00+00:00")
    row = _isi(service, "2026-09-30T05:20:00+00:00")
    datang = sorted(t["arrived_at"] for t in service.weighings(row["work_date"]))
    assert datang == ["2026-09-30T00:30:00+00:00", "2026-09-30T05:00:00+00:00"]


def test_klaim_lewat_tengah_malam(pabrik):
    service, gate, _, _ = pabrik
    gate.arrive(PLAT, "2026-09-30T23:50:00+07:00")
    row = _isi(service, "2026-10-01T00:10:00+07:00")
    assert service.weighings(row["work_date"])[0]["arrived_at"] == "2026-09-30T23:50:00+07:00"


def test_jam_gerbang_tidak_pernah_masuk_pesan_autoerp():
    visit = {
        "id": "w1", "plate_number": PLAT, "truck_id": truck_id_for(PLAT),
        "entered_at": "2026-09-30T01:00:00+00:00", "exited_at": "2026-09-30T02:00:00+00:00",
        "gross_kg": 14000.0, "tare_kg": 6000.0,
        "arrived_at": "2026-09-30T00:17:00+00:00", "left_at": "2026-09-30T02:43:00+00:00",
    }
    _, payload = visit_message(visit, None, site="", emitted_at="2026-09-30T02:44:00+00:00")
    # Exact keys, not a substring scan: `time_arrive` in +07:00 would pass a scan (Q1).
    assert set(payload) == {"visit_id", "stage", "truck", "weighing", "emitted_at"}
    assert set(payload["weighing"]) == {"time_in", "gross_kg", "tare_kg", "time_out"}
    teks = json.dumps(payload)
    assert "00:17" not in teks and "02:43" not in teks
    assert "arrived" not in teks and "left_at" not in teks


def test_keluar_gerbang_tidak_mengantre_kiriman_erp(pabrik):
    service, gate, _, antrean = pabrik
    _isi(service, "2026-09-30T01:00:00+00:00")
    _kosong(service, "2026-09-30T01:00:00+00:00", "2026-09-30T02:00:00+00:00")
    sebelum = len(antrean.visits)
    gate.arrive("BE 1 AA", "2026-09-30T02:05:00+00:00")
    assert gate.leave(PLAT, "2026-09-30T02:10:00+00:00")["hasil"] == "tercatat"
    assert len(antrean.visits) == sebelum


def test_antrean_timbang_dari_service_membawa_menit(pabrik):
    service, gate, _, _ = pabrik
    gate.arrive(PLAT, "2026-09-30T00:30:00+00:00")
    [a] = service.waiting_arrivals(baca_waktu("2026-09-30T00:40:00+00:00"))
    assert a["plate_number"] == "BE4412OFL"
    assert isinstance(a["menit"], int) and a["menit"] >= 0


def test_tiket_yang_sudah_ada_tidak_mengklaim_lagi(pabrik):
    """A re-weigh of an existing ticket (same entered_at) must not take a later arrival."""
    service, gate, store, _ = pabrik
    _isi(service, "2026-09-30T01:00:00+00:00")
    gate.arrive(PLAT, "2026-09-30T00:59:00+00:00")
    # arrive() refused (truck is inside), so seed a waiting arrival directly
    assert store.waiting_arrivals_for_truck(truck_id_for(PLAT)) == []
    store.record_arrival({
        "id": "a-x", "plate_number": PLAT, "plate_norm": "BE4412OFL", "truck_id": truck_id_for(PLAT),
        "work_date": "2026-09-30", "arrived_at": "2026-09-30T00:59:30+00:00",
    })
    _isi(service, "2026-09-30T01:00:00+00:00")
    assert len(store.waiting_arrivals_for_truck(truck_id_for(PLAT))) == 1


def test_klaim_yang_gagal_tidak_menggagalkan_timbangan(pabrik, monkeypatch):
    service, gate, store, _ = pabrik
    gate.arrive(PLAT, "2026-09-30T00:30:00+00:00")

    def _rusak(*_a, **_k):
        raise RuntimeError("disk penuh")

    monkeypatch.setattr(store, "claim_arrival", _rusak)
    row = _isi(service, "2026-09-30T01:00:00+00:00")
    assert row["gross_kg"] == 14000.0
    assert service.weighings(row["work_date"])[0]["tanpa_scan_1"] is True
