"""Integrasi empat scan: GateService + ConsoleService + ConsoleStore (berkas SQLite) + ErpQueue.

Dibuktikan: scan 1 menunggu, timbang isi mengklaimnya, timbang kosong, scan 4 menutup;
lama antre dan lama total ada di tampilan Timbangan; scan 1 yang dilewati ditandai;
keluar sebelum timbang kosong tidak menulis apa pun; dan jam gerbang TIDAK PERNAH ada di
pesan AutoERP yang benar-benar masuk antrean, sedangkan scan 4 tidak mengantre apa pun.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain import erp_messages
from palmgrade.domain.gerbang import baca_waktu
from palmgrade.domain.plate import truck_id_for
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.erp_queue import ErpQueue
from palmgrade.services.gate_service import GateService

PLAT = "BE 4412 OFL"
HARI = "2026-09-30"


@pytest.fixture
def pabrik(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    outbox = ErpOutboxStore(tmp_path / "erp_outbox.db")
    service = ConsoleService(
        replace(Settings(), factory_tz="Asia/Jakarta"), store, None, erp_queue=ErpQueue(store, outbox)
    )
    return service, GateService(store, service.tz), store, outbox


def _isi(service, jam, plat=PLAT):
    return asyncio.run(service.record_weighing({"plate_number": plat, "gross_kg": 14000, "entered_at": jam}))


def _kosong(service, masuk, keluar, plat=PLAT):
    return asyncio.run(service.record_weighing({
        "plate_number": plat, "entered_at": masuk, "tare_kg": 6000, "exited_at": keluar,
    }))


def _pesan_visit(outbox):
    return [m for m in outbox.due(50) if m.kind == erp_messages.VISIT]


def test_empat_scan_sampai_lama_antre_dan_total(pabrik):
    service, gate, store, outbox = pabrik
    assert gate.arrive(PLAT, "2026-09-30T00:30:00+00:00")["hasil"] == "tercatat"
    assert [a["plate_number"] for a in service.waiting_arrivals(baca_waktu("2026-09-30T00:40:00+00:00"))] == [
        "BE4412OFL"  # unregistered: the normalized plate
    ]

    _isi(service, "2026-09-30T01:00:00+00:00")  # claims the arrival
    assert service.waiting_arrivals(baca_waktu("2026-09-30T01:05:00+00:00")) == []
    _kosong(service, "2026-09-30T01:00:00+00:00", "2026-09-30T02:00:00+00:00")
    assert gate.leave(PLAT, "2026-09-30T02:10:00+00:00")["hasil"] == "tercatat"

    [tiket] = service.weighings(HARI)
    assert (tiket["antre_menit"], tiket["total_menit"], tiket["tanpa_scan_1"]) == (30, 100, False)
    assert (tiket["arrived_at"], tiket["left_at"]) == ("2026-09-30T00:30:00+00:00", "2026-09-30T02:10:00+00:00")
    assert tiket["net_kg"] == 8000.0


def test_scan_1_dilewati_ditandai_dan_total_dari_timbang_isi(pabrik):
    service, gate, _, _ = pabrik
    _isi(service, "2026-09-30T01:00:00+00:00")
    _kosong(service, "2026-09-30T01:00:00+00:00", "2026-09-30T02:00:00+00:00")
    gate.leave(PLAT, "2026-09-30T02:30:00+00:00")
    [tiket] = service.weighings(HARI)
    assert (tiket["antre_menit"], tiket["tanpa_scan_1"], tiket["total_menit"]) == (None, True, 90)


def test_keluar_sebelum_timbang_kosong_tidak_menulis_apa_pun(pabrik):
    service, gate, store, outbox = pabrik
    row = _isi(service, "2026-09-30T01:00:00+00:00")
    sebelum = len(outbox.due(50))
    jawab = gate.leave(PLAT, "2026-09-30T01:30:00+00:00")
    assert jawab["hasil"] == "belum_timbang_kosong" and "left_at" not in jawab
    assert store.weighing(row["id"])["left_at"] is None
    assert len(outbox.due(50)) == sebelum
    # and a row-button press on the same ticket is refused the same way
    assert gate.leave(None, "2026-09-30T01:31:00+00:00", weighing_id=row["id"])["hasil"] == "belum_timbang_kosong"
    assert store.weighing(row["id"])["left_at"] is None


def test_jam_gerbang_tidak_pernah_ada_di_pesan_autoerp_yang_antre(pabrik):
    service, gate, store, outbox = pabrik
    gate.arrive(PLAT, "2026-09-30T00:17:00+00:00")
    _isi(service, "2026-09-30T01:00:00+00:00")
    row = _kosong(service, "2026-09-30T01:00:00+00:00", "2026-09-30T02:00:00+00:00")
    gate.leave(PLAT, "2026-09-30T02:43:00+00:00")

    [tiket] = service.weighings(HARI)
    assert tiket["arrived_at"] and tiket["left_at"]  # the ticket really holds both gate times

    # The daily resend rebuilds the visit from the store, after both gate times exist.
    assert service.erp_queue.visit(row["id"]) is True
    pesan = _pesan_visit(outbox)
    assert pesan, "no visit message was queued"
    for m in pesan:
        teks = json.dumps(m.payload)
        assert "00:17" not in teks and "02:43" not in teks
        assert "arrived" not in teks and "left" not in teks


def test_scan_4_tidak_mengantre_apa_pun_ke_autoerp(pabrik):
    service, gate, store, outbox = pabrik
    gate.arrive(PLAT, "2026-09-30T00:30:00+00:00")
    _isi(service, "2026-09-30T01:00:00+00:00")
    _kosong(service, "2026-09-30T01:00:00+00:00", "2026-09-30T02:00:00+00:00")
    sebelum = [(m.kind, m.key) for m in outbox.due(50)]
    assert sebelum, "weigh-out should have queued its visit"
    gate.arrive("BE 7001 XY", "2026-09-30T02:05:00+00:00")  # scan 1 of another truck
    assert gate.leave(PLAT, "2026-09-30T02:10:00+00:00")["hasil"] == "tercatat"
    assert [(m.kind, m.key) for m in outbox.due(50)] == sebelum
    assert store.truck(truck_id_for("BE 7001 XY")) is None  # a scan never creates a truck
