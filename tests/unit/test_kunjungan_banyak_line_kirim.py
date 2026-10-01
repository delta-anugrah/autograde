"""Truk yang dibongkar di dua line sampai ke AutoERP, halaman detail, dan tab Log UTUH."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain import erp_messages
from palmgrade.domain.plate import normalisasi_plat
from palmgrade.domain.working_day import JENDELA_KUNJUNGAN_DETIK
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.erp_queue import ErpQueue
from palmgrade.workers.erp_link import _konteks
from palmgrade.workers.visit_manifest_worker import VisitManifestWorker

WIB = ZoneInfo("Asia/Jakarta")
PLAT = "BE 1 AA"


class FakeLine:
    async def assign_truck(self, line, *, assignment_id, truck_id, assigned_at, ffb_source=None, plate=None):
        return None


class FakeUploader:
    def put_bytes(self, body, r2_key, *, content_type):
        return None


def _konsol(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    outbox = ErpOutboxStore(tmp_path / "erp_outbox.db")
    service = ConsoleService(
        replace(Settings(), factory_tz="Asia/Jakarta"), store, FakeLine(),
        erp_queue=ErpQueue(store, outbox),
    )
    return service, store, outbox


@pytest.fixture
def pabrik(tmp_path):
    service, store, outbox = _konsol(tmp_path)
    truck = service.register_manual_truck(PLAT)
    # The ticket is found through the truck's newest weigh-in, so it is weighed in now.
    row = asyncio.run(service.record_weighing(
        {"plate_number": PLAT, "gross_kg": 14000, "entered_at": datetime.now(WIB).isoformat()}
    ))
    return service, store, outbox, truck["id"], row["id"]


def _janjang(service, line_code: str, n: int, *, awal: int = 0) -> None:
    assignment_id = service.store.assignments()[line_code]["assignment_id"]
    for i in range(awal, awal + n):
        service.store.add_inspection({
            "event_id": f"{line_code}-{i}", "machine_id": f"m-{line_code}", "line_code": line_code,
            "work_date": service.today(), "timestamp": f"{service.today()}T01:{i:02d}:00+07:00",
            "ripeness_status": "ACC", "ripeness_confidence": 0.9, "capture_type": "auto",
            "image_path": None, "truck_id": None, "assignment_id": assignment_id,
            "prediction": "Acc", "tp_status": None, "tp_confidence": None,
        })


def _kiriman_terakhir(outbox, weighing_id):
    pesan = [m for m in outbox.due(50) if m.kind == erp_messages.VISIT and m.key == weighing_id]
    return pesan[-1].payload


def _bongkar_dua_line(service, truck_id):
    for line in ("line-1", "line-2"):
        asyncio.run(service.assign_truck(line, truck_id))
    _janjang(service, "line-1", 3)
    _janjang(service, "line-2", 2)
    for line in ("line-1", "line-2"):
        asyncio.run(service.release_truck(line))


def test_truk_di_dua_line_terkirim_utuh_ke_autoerp(pabrik):
    service, _, outbox, truck_id, wid = pabrik
    _bongkar_dua_line(service, truck_id)
    grading = _kiriman_terakhir(outbox, wid)["grading"]
    assert grading["counts"]["total"] == 5, "cuma satu line yang terkirim ke AutoERP"


def test_janjang_susulan_line_pertama_ikut_terkirim(pabrik):
    """Janjang yang tiba sesudah line-1 dilepas mengantre ulang kunjungannya. Dulu cuma
    penugasan line yang dilepas TERAKHIR yang menemukan tiketnya."""
    service, store, outbox, truck_id, wid = pabrik
    for line in ("line-1", "line-2"):
        asyncio.run(service.assign_truck(line, truck_id))
    aid_line1 = store.assignments()["line-1"]["assignment_id"]
    _janjang(service, "line-1", 3)
    _janjang(service, "line-2", 2)
    for line in ("line-1", "line-2"):
        asyncio.run(service.release_truck(line))

    # Lewat jalur ingest sungguhan: dia yang memanggil `_kunjungan_susulan`.
    service.ingest({
        "event_id": "susulan-1", "machine_id": service.lines[0].machine_id,
        "timestamp": datetime.now(WIB).isoformat(), "ripeness_status": "REJ",
        "assignment_id": aid_line1, "truck_id": truck_id,
    })

    assert _kiriman_terakhir(outbox, wid)["grading"]["counts"]["total"] == 6


def _penugasan(store, weighing_id):
    with store._lock:  # noqa: SLF001 (test reads the link table directly)
        rows = store._db.execute(  # noqa: SLF001
            "SELECT assignment_id FROM visit_assignments WHERE weighing_id = ? ORDER BY linked_at",
            (weighing_id,),
        ).fetchall()
    return [r["assignment_id"] for r in rows]


def test_line_tercatat_di_tautan(pabrik):
    service, store, _, truck_id, wid = pabrik
    _bongkar_dua_line(service, truck_id)
    assert len(_penugasan(store, wid)) == 2
    with store._lock:  # noqa: SLF001 (test reads the link table directly)
        lines = store._db.execute(  # noqa: SLF001
            "SELECT line_code FROM visit_assignments WHERE weighing_id = ? ORDER BY line_code", (wid,)
        ).fetchall()
    assert [r["line_code"] for r in lines] == ["line-1", "line-2"]
    assert store.grading_counts_for_visit(wid)["line_code"] == "line-1, line-2"


def test_halaman_detail_memuat_janjang_dua_line(pabrik, tmp_path):
    service, store, _, truck_id, wid = pabrik
    _bongkar_dua_line(service, truck_id)
    viewer = tmp_path / "viewer.html"
    viewer.write_text("<html></html>")
    worker = VisitManifestWorker(
        store, ErpOutboxStore(tmp_path / "m.db"), FakeUploader(),
        public_url="https://captures.example", viewer_html=viewer, clock=lambda: "2026-10-01T09:00:00+07:00",
    )
    manifest = json.loads(worker._build(wid, {"assignment_id": "apa-saja"}))
    assert manifest["counts"]["total"] == 5
    assert len(manifest["bunches"]) == 5


def test_baris_log_menyebut_semua_line(pabrik):
    service, store, _, truck_id, wid = pabrik
    _bongkar_dua_line(service, truck_id)
    konteks = _konteks(store, wid, {}, WIB)
    assert konteks.janjang == 5
    assert konteks.line == "line-1, line-2"


# ---- Tiket ditemukan lewat jendela waktu, bukan hari kerja (lintas tengah malam) ----

def _tiket_lampau(store, truck_id: str, jam_lalu: float, *, wid: str) -> str:
    """A ticket weighed in `jam_lalu` hours ago, filed under YESTERDAY's work date, as one
    weighed in at 23:30 is once the clock passes midnight."""
    sekarang = datetime.now(WIB)
    masuk = sekarang - timedelta(hours=jam_lalu)
    store.upsert_weighing({
        "id": wid, "ref": None, "plate_number": PLAT, "plate_norm": normalisasi_plat(PLAT),
        "truck_id": truck_id, "work_date": (sekarang - timedelta(days=1)).strftime("%Y-%m-%d"),
        "gross_kg": 14000.0, "tare_kg": None, "net_kg": None,
        "entered_at": masuk.isoformat(), "exited_at": None,
    })
    with store._lock, store._db:  # noqa: SLF001 (the clock the window reads is not settable)
        store._db.execute(  # noqa: SLF001
            "UPDATE weighings SET received_at = ? WHERE id = ?", (time.time() - jam_lalu * 3600, wid)
        )
    return wid


def test_jendela_kunjungan_dua_belas_jam():
    assert JENDELA_KUNJUNGAN_DETIK == 12 * 60 * 60


def test_tiket_sebelum_tengah_malam_tertaut_saat_dilepas_sesudahnya(tmp_path):
    service, store, outbox = _konsol(tmp_path)
    truck_id = service.register_manual_truck(PLAT)["id"]
    wid = _tiket_lampau(store, truck_id, 1.0, wid="w-semalam")
    asyncio.run(service.assign_truck("line-1", truck_id))
    _janjang(service, "line-1", 3)

    asyncio.run(service.release_truck("line-1"))

    assert len(_penugasan(store, wid)) == 1
    assert _kiriman_terakhir(outbox, wid)["grading"]["counts"]["total"] == 3


def test_tiket_tiga_belas_jam_lalu_tidak_ditautkan(tmp_path):
    service, store, outbox = _konsol(tmp_path)
    truck_id = service.register_manual_truck(PLAT)["id"]
    wid = _tiket_lampau(store, truck_id, 13.0, wid="w-kemarin")
    asyncio.run(service.assign_truck("line-1", truck_id))
    _janjang(service, "line-1", 3)

    asyncio.run(service.release_truck("line-1"))

    assert _penugasan(store, wid) == []
    assert [m for m in outbox.due(50) if m.kind == erp_messages.VISIT] == []


def test_dua_tiket_dalam_jendela_tertaut_ke_yang_terbaru(tmp_path):
    service, store, _ = _konsol(tmp_path)
    truck_id = service.register_manual_truck(PLAT)["id"]
    lama = _tiket_lampau(store, truck_id, 3.0, wid="w-lama")
    baru = _tiket_lampau(store, truck_id, 1.0, wid="w-baru")
    asyncio.run(service.assign_truck("line-1", truck_id))
    _janjang(service, "line-1", 2)

    asyncio.run(service.release_truck("line-1"))

    assert len(_penugasan(store, baru)) == 1
    assert _penugasan(store, lama) == []
