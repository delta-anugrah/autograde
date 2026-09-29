"""Integrasi janjang susulan (batch 2.3): dari lane mesin sampai jawaban AutoERP.

Dirangkai tanpa tiruan di tengah: route ingest yang asli (`x-webhook-secret`) →
`ConsoleService` → `ConsoleStore` + `ErpQueue` + `ErpOutboxStore` di berkas SQLite
sungguhan → `ErpOutboxWorker` + `ErpClient` → handler jawaban `workers/erp_link.py`.
Yang tiruan: AutoERP (`tests/autoerp_palsu.py`) dan line (menerima penugasan).
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from autoerp_palsu import AutoErpPalsu
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.plate import truck_id_for
from palmgrade.domain.vision_event import build_event_payload
from palmgrade.integrations.erp.client import ErpClient
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console_deps import get_console_service
from palmgrade.routes.console_ingest import ingest_router
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.erp_queue import ErpQueue
from palmgrade.workers.erp_link import outbox_handlers
from palmgrade.workers.erp_outbox_worker import ErpOutboxWorker

SECRET = "kunci-integrasi-palsu"
PLAT = "BE 8821 KL"
WIB = ZoneInfo("Asia/Jakarta")


class _Line:
    async def assign_truck(self, line, **_kw) -> None: ...


class Konsol:
    def __init__(self, root) -> None:
        self.settings = replace(
            Settings(), factory_tz="Asia/Jakarta", webhook_secret=SECRET, erp_url="http://erp.local"
        )
        self.store = ConsoleStore(root / "console.db")
        self.outbox = ErpOutboxStore(root / "erp_outbox.db")
        self.service = ConsoleService(
            self.settings, self.store, _Line(), erp_queue=ErpQueue(self.store, self.outbox)
        )
        self.erp = AutoErpPalsu()
        klien = ErpClient("http://erp.local", "k", "s", transport=httpx.MockTransport(self.erp))
        self.worker = ErpOutboxWorker(self.outbox, klien, outbox_handlers(self.store))
        app = FastAPI()
        app.include_router(ingest_router, prefix=self.settings.backend_api_ver)
        app.dependency_overrides[get_console_service] = lambda: self.service
        self.line = TestClient(app)
        self._n = 0

    def janjang(self, assignment_id: str, *, status: str = "ACC", ulang: int | None = None) -> None:
        """Satu janjang lewat lane mesin, seperti OutboxRetryWorker line. `ulang=n` mengirim
        lagi janjang ke-n (event_id yang sama), seperti line yang restart."""
        n = ulang if ulang is not None else self._n + 1
        self._n = max(self._n, n)
        body = build_event_payload(
            machine_id=self.service.lines[0].machine_id, file_ts=f"2026-09-28_07-41-{n:02d}_000000",
            timestamp=datetime.now(UTC).isoformat(), ripeness_status=status, ripeness_confidence=0.9,
            capture_type="auto", image_path=f"captures/results/2026-09-28/{n}.webp",
            truck_id=truck_id_for(PLAT), assignment_id=assignment_id,
        )
        res = self.line.post(
            f"{self.settings.backend_api_ver}/internal/vision/events",
            json=body, headers={"x-webhook-secret": SECRET},
        )
        assert res.status_code == 201, res.text

    def truk_selesai(self, *, janjang: int = 3, timbang_keluar: bool = True) -> tuple[str, str]:
        tiket = asyncio.run(self.service.record_weighing({
            "ref": "SCL-7", "plate_number": PLAT,
            "entered_at": datetime.now(WIB).isoformat(), "gross_kg": 14560,
        }))
        assignment_id = asyncio.run(self.service.assign_truck("line-1", truck_id_for(PLAT)))["assignment_id"]
        for _ in range(janjang):
            self.janjang(assignment_id)
        if timbang_keluar:          # timbang keluar melepas line (G5) dan mengantre rekapnya
            asyncio.run(self.service.record_weighing({
                "ref": "SCL-7", "plate_number": PLAT, "tare_kg": 5400,
                "exited_at": datetime.now(WIB).isoformat(),
            }))
        return tiket["id"], assignment_id

    def kirim(self) -> int:
        return asyncio.run(self.worker.drain_once())


@pytest.fixture
def konsol(tmp_path) -> Konsol:
    return Konsol(tmp_path)


def test_janjang_susulan_sebelum_terkirim_ikut_kiriman_pertama(konsol):
    """Yang paling sering: janjang terakhir masih di antrean simpan line saat truk timbang
    keluar. Baris antrean yang sama diganti; AutoERP menerima SATU kiriman yang lengkap."""
    tiket, assignment_id = konsol.truk_selesai()
    konsol.janjang(assignment_id, status="REJ")

    assert konsol.kirim() == 1

    [kunjungan] = konsol.erp.diterima
    assert (kunjungan["grading"]["counts"]["total"], kunjungan["grading"]["counts"]["rej"]) == (4, 1)
    baris = konsol.store.weighing(tiket)
    assert (baris["erp_status"], baris["erp_note"]) == ("Finalised", None)


def test_janjang_susulan_sesudah_tiket_final_dikirim_dan_jawabannya_disimpan(konsol):
    tiket, assignment_id = konsol.truk_selesai()
    assert konsol.kirim() == 1                          # final dengan 3 janjang
    konsol.janjang(assignment_id, status="REJ")

    assert konsol.kirim() == 1

    assert [k["grading"]["counts"]["total"] for k in konsol.erp.diterima] == [3, 4]
    assert konsol.store.weighing(tiket)["erp_note"] == "ticket already finalised; grading revised"


def test_kiriman_ulang_janjang_lama_tidak_mengantre_ulang(konsol):
    """Line yang restart mengirim ulang antreannya: tidak boleh jadi badai kiriman."""
    _, assignment_id = konsol.truk_selesai()
    assert konsol.kirim() == 1

    for n in (1, 2, 3):
        konsol.janjang(assignment_id, ulang=n)

    assert konsol.outbox.due() == []
    assert konsol.kirim() == 0
    assert len(konsol.erp.diterima) == 1


def test_janjang_truk_yang_masih_di_line_tidak_mengantre(konsol):
    _, assignment_id = konsol.truk_selesai(timbang_keluar=False)
    assert konsol.kirim() == 1                          # hanya kunjungan gerbang

    konsol.janjang(assignment_id)

    assert konsol.outbox.due() == []
