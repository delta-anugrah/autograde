"""Integrasi empat scan: GateService + ConsoleService + ConsoleStore (berkas SQLite) + ErpQueue.

Dibuktikan: scan 1 menunggu, timbang isi mengklaimnya, timbang kosong, scan 4 menutup;
lama antre dan lama total ada di tampilan Timbangan; scan 1 yang dilewati ditandai;
keluar sebelum timbang kosong tidak menulis apa pun; dan jam gerbang TIDAK PERNAH ada di
pesan AutoERP yang benar-benar masuk antrean, sedangkan scan 4 tidak mengantre apa pun.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain import erp_messages
from palmgrade.domain.gerbang import (
    TAHAP_BONGKAR,
    TAHAP_DATANG,
    TAHAP_SELESAI,
    TAHAP_TIMBANG_KOSONG,
    baca_waktu,
)
from palmgrade.domain.plate import truck_id_for
from palmgrade.domain.visit_manifest import build_manifest
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


DATANG, PERGI = "2026-09-30T00:17:00+00:00", "2026-09-30T02:43:00+00:00"

# What a visit may carry, key by key (contract §4.C). A new key fails here first, so a
# gate time can never slip in under a name nobody thought to search for (Q1).
KUNCI_PESAN = {"visit_id", "stage", "truck", "weighing", "emitted_at"}
KUNCI_TIMBANGAN = {"time_in", "gross_kg", "tare_kg", "time_out"}
KUNCI_TRUK = {"plate_number", "autograde_id"}
KUNCI_MANIFEST = {"schema", "visit_id", "assignment_id", "line_code", "plate_number", "supplier_name",
                  "work_date", "started_at", "ended_at", "generated_at", "counts", "bunches"}


def _daun(nilai):
    """Every leaf value of a JSON body, however deep."""
    if isinstance(nilai, dict):
        for v in nilai.values():
            yield from _daun(v)
    elif isinstance(nilai, list):
        for v in nilai:
            yield from _daun(v)
    else:
        yield nilai


def _tanpa_jam_gerbang(body):
    """No leaf is the arrive or leave instant in any rendering: UTC, Z, +07:00, epoch."""
    instan = {baca_waktu(DATANG), baca_waktu(PERGI)}
    epoch = {t.timestamp() for t in instan} | {t.timestamp() * 1000 for t in instan}
    for nilai in _daun(body):
        if isinstance(nilai, bool) or nilai is None:
            continue
        if isinstance(nilai, int | float):
            assert float(nilai) not in epoch, nilai
            continue
        try:
            waktu = baca_waktu(str(nilai))
        except ValueError:
            continue
        assert waktu not in instan, nilai


def test_jam_gerbang_tidak_pernah_ada_di_pesan_autoerp_yang_antre(pabrik):
    service, gate, store, outbox = pabrik
    gate.arrive(PLAT, DATANG)
    _isi(service, "2026-09-30T01:00:00+00:00")
    row = _kosong(service, "2026-09-30T01:00:00+00:00", "2026-09-30T02:00:00+00:00")
    gate.leave(PLAT, PERGI)

    [tiket] = service.weighings(HARI)
    assert (tiket["arrived_at"], tiket["left_at"]) == (DATANG, PERGI)  # the ticket really holds both

    # The daily resend rebuilds the visit from the store, after both gate times exist.
    assert service.erp_queue.visit(row["id"]) is True
    pesan = _pesan_visit(outbox)
    assert pesan, "no visit message was queued"
    for m in pesan:
        assert set(m.payload) == KUNCI_PESAN, sorted(m.payload)
        assert set(m.payload["weighing"]) == KUNCI_TIMBANGAN, sorted(m.payload["weighing"])
        assert set(m.payload["truck"]) == KUNCI_TRUK, sorted(m.payload["truck"])
        _tanpa_jam_gerbang(m.payload)

    # The detail page (R2) is built from the same row: give it both gate times on purpose.
    visit = {**store.visit(row["id"]), "arrived_at": tiket["arrived_at"]}
    assert visit["left_at"] == PERGI
    grading = {"assignment_id": "a1", "line_code": "line-1", "total": 1, "acc": 1,
               "started_at": "2026-09-30T01:05:00+00:00", "ended_at": "2026-09-30T01:50:00+00:00"}
    manifest = build_manifest(visit, grading, [], public_url="https://captures.example",
                              generated_at="2026-09-30T03:00:00+00:00")
    assert set(manifest) == KUNCI_MANIFEST, sorted(manifest)
    _tanpa_jam_gerbang(manifest)


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


def test_tabel_terbaru_dulu_menurut_waktu_nyata_dan_tiket_truk_yang_ditaut(pabrik):
    """User's screenshot 2026-10-02: a browser ticket (`Z`) sat between older seeded ones
    (`+07:00`) because the table was ordered by the ISO text."""
    service, gate, store, _ = pabrik
    _isi(service, "2026-09-30T08:00:00+07:00", plat="BE 1 LAMA")  # 01:00 UTC, seeded
    _isi(service, "2026-09-30T01:30:00.000Z", plat="BE 2 BARU")  # from the browser
    assert [w["plate_number"] for w in service.weighings(HARI)] == ["BE 2 BARU", "BE 1 LAMA"]

    # One truck weighed in twice in two spellings: the newer instant is its ticket.
    _isi(service, "2026-09-30T08:10:00+07:00")  # 01:10 UTC
    _isi(service, "2026-09-30T01:20:00Z")
    terbaru = store.latest_weighing_for_truck_since(truck_id_for(PLAT), 0.0)
    assert store.weighing(terbaru)["entered_at"] == "2026-09-30T01:20:00Z"
    assert terbaru in [r["weighing_id"] for r in store.unloading_queue(0.0)]


def test_tampilan_timbangan_satu_kunjungan_per_tahap(pabrik):
    """User 2026-10-02: A has only arrived, B weighed in from the browser (`Z`), C was seeded
    earlier (`+07:00`) and weighed out. The GET view (items + waiting) is newest first by the
    real instant, every ticket carries its stage and A waits with stage "datang"."""
    service, gate, _, _ = pabrik
    _isi(service, "2026-09-30T08:10:00+07:00", plat="BE 3 CC")  # 01:10 UTC
    _kosong(service, "2026-09-30T08:10:00+07:00", "2026-09-30T08:30:00+07:00", plat="BE 3 CC")
    _isi(service, "2026-09-30T01:40:00.000Z", plat="BE 2 BB")
    assert gate.arrive("BE 1 AA", "2026-09-30T01:55:00Z")["hasil"] == "tercatat"

    items = service.weighings(HARI)
    assert [(w["plate_number"], w["tahap"]) for w in items] == [
        ("BE 2 BB", TAHAP_BONGKAR), ("BE 3 CC", TAHAP_TIMBANG_KOSONG)]
    [menunggu] = service.waiting_arrivals(baca_waktu("2026-09-30T02:00:00Z"))
    assert (menunggu["plate_number"], menunggu["tahap"], menunggu["menit"]) == ("BE1AA", TAHAP_DATANG, 5)

    [c] = [w for w in items if w["plate_number"] == "BE 3 CC"]
    assert gate.leave(at="2026-09-30T02:00:00Z", weighing_id=c["id"])["hasil"] == "tercatat"
    assert {w["plate_number"]: w["tahap"] for w in service.weighings(HARI)}["BE 3 CC"] == TAHAP_SELESAI
