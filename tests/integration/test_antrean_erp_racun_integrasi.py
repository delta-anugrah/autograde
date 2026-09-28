"""Integrasi antrean AutoERP (batch 2.7): satu pesan beracun tidak menahan yang lain.

Dirangkai tanpa tiruan di tengah: `ConsoleService` + `ConsoleStore` + `ErpQueue` +
`ErpOutboxStore` (berkas SQLite sungguhan) + `ErpOutboxWorker` + `ErpClient` +
`StatusSinkron`, dengan handler jawaban dari `workers/erp_link.py`. Yang tiruan cuma
server AutoERP (`tests/autoerp_palsu.py`, lewat `httpx.MockTransport`) dan line.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from autoerp_palsu import AutoErpPalsu

from palmgrade.core.config import Settings
from palmgrade.integrations.erp.client import ErpClient
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.erp_queue import ErpQueue
from palmgrade.services.status_sinkron import StatusSinkron
from palmgrade.workers.erp_link import outbox_handlers
from palmgrade.workers.erp_outbox_worker import ErpOutboxWorker

WIB = ZoneInfo("Asia/Jakarta")
PLAT = ("BE 1 AA", "BE 2 BB", "BE 3 CC")


class _Line:
    async def assign_truck(self, line, **_kw) -> None: ...


class Konsol:
    def __init__(self, root) -> None:
        self.erp = AutoErpPalsu()
        self.store = ConsoleStore(root / "console.db")
        self.outbox = ErpOutboxStore(root / "erp_outbox.db")
        self.status = StatusSinkron(self.store, erp_aktif=True, r2_aktif=False)
        settings = replace(Settings(), factory_tz="Asia/Jakarta", erp_url="http://erp.local")
        self.service = ConsoleService(
            settings, self.store, _Line(),
            erp_queue=ErpQueue(self.store, self.outbox), status_sinkron=self.status,
        )
        klien = ErpClient("http://erp.local", "k", "s", transport=httpx.MockTransport(self.erp))
        self.worker = ErpOutboxWorker(self.outbox, klien, outbox_handlers(self.store), status=self.status)

    def timbang_masuk(self, plat: str) -> str:
        tiket = asyncio.run(self.service.record_weighing({
            "ref": f"SCL-{plat}", "plate_number": plat,
            "entered_at": datetime.now(WIB).isoformat(), "gross_kg": 14560,
        }))
        return tiket["id"]

    def kirim(self) -> int:
        return asyncio.run(self.worker.drain_once())


@pytest.fixture
def konsol(tmp_path) -> Konsol:
    return Konsol(tmp_path)


def test_satu_kunjungan_beracun_tidak_menahan_dua_lainnya(konsol):
    konsol.erp.racun.add("BE 1 AA")
    tiket = {plat: konsol.timbang_masuk(plat) for plat in PLAT}

    assert konsol.kirim() == 2

    assert konsol.store.weighing(tiket["BE 2 BB"])["erp_ticket"]
    assert konsol.store.weighing(tiket["BE 3 CC"])["erp_ticket"]
    [racun] = konsol.outbox.failed_rows()
    assert racun["key"] == tiket["BE 1 AA"]
    assert "HTTP 500" in racun["last_error"] and "KeyError" in racun["last_error"]
    # Frappe menjawab: sambungannya hidup, yang bermasalah isi pesan itu.
    assert konsol.status.ringkas("erp", antre=1)["keadaan"] == "tersambung"


def test_jawaban_bukan_frappe_dicatat_dan_last_sync_terputus(konsol):
    konsol.erp.portal = True
    tiket = konsol.timbang_masuk("BE 1 AA")

    assert konsol.kirim() == 0

    [baris] = konsol.outbox.failed_rows()
    assert baris["key"] == tiket and "HTTP 200" in baris["last_error"]
    assert konsol.status.ringkas("erp", antre=1)["keadaan"] == "terputus"


def test_sesudah_portal_hilang_kirim_ulang_mengirim_semuanya(konsol):
    konsol.erp.portal = True
    tiket = [konsol.timbang_masuk(plat) for plat in PLAT[:2]]
    konsol.kirim()
    konsol.erp.portal = False

    assert konsol.outbox.requeue_failed() == 1         # tombol Kirim Ulang
    assert konsol.kirim() == 2
    assert all(konsol.store.weighing(t)["erp_ticket"] for t in tiket)
