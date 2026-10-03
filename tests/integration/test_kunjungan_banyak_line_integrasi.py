"""Integrasi satu truk di tiga line: dari janjang di tiap line sampai AutoERP dan halaman detail.

Dirangkai tanpa tiruan di tengah: lane mesin konsol yang asli (`x-webhook-secret`) →
`ConsoleService` → `ConsoleStore` di berkas SQLite sungguhan → `LineClient` sungguhan ke tiga
line palsu (satu app per port) → `ErpQueue` + `ErpOutboxWorker` + `ErpClient` → handler jawaban
`workers/erp_link.py`, dan `VisitManifestWorker` sungguhan untuk halaman detailnya. Yang
tiruan: tiga line (menerima penugasan), AutoERP (`tests/autoerp_palsu.py`) dan R2.

Truk yang dibongkar di tiga line adalah SATU kunjungan: rekap ke AutoERP dan halaman detail
menjumlah ketiganya. Dulu cuma line yang dilepas terakhir yang terhitung.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from antrean_line_rakit import LinePerPort, app_ingest
from autoerp_palsu import AutoErpPalsu
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.plate import truck_id_for
from palmgrade.domain.vision_event import build_event_payload
from palmgrade.integrations.erp.client import ErpClient
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.erp_queue import ErpQueue
from palmgrade.workers.erp_link import outbox_handlers
from palmgrade.workers.erp_outbox_worker import ErpOutboxWorker
from palmgrade.workers.visit_manifest_worker import VisitManifestWorker

SECRET_WEBHOOK = "kunci-webhook-palsu"
SECRET_INTERNAL = "kunci-internal-palsu"
PLAT = "BE 8821 KL"
WIB = ZoneInfo("Asia/Jakarta")
LINES = ("line-1", "line-2", "line-3")
PORT = {"line-1": 8001, "line-2": 8002, "line-3": 8003}


class LinePalsu:
    """Satu line yang menerima penugasan dan mencatatnya, seperti `/internal/assignment` aslinya."""

    def __init__(self) -> None:
        self.diterima: list[dict] = []
        self.app = FastAPI()

        @self.app.post("/internal/assignment")
        async def penugasan(request: Request) -> dict:
            assert request.headers["x-internal-secret"] == SECRET_INTERNAL
            self.diterima.append(await request.json())
            return {"status": "ok"}


class R2Palsu:
    def __init__(self) -> None:
        self.unggahan: dict[str, bytes] = {}

    def put_bytes(self, body: bytes, r2_key: str, *, content_type: str) -> None:
        self.unggahan[r2_key] = body


class Pabrik:
    def __init__(self, root) -> None:
        settings = replace(
            Settings(), factory_tz="Asia/Jakarta", webhook_secret=SECRET_WEBHOOK,
            internal_secret=SECRET_INTERNAL, console_line_host="http://line", erp_url="http://erp.local",
        )
        self.settings = settings
        self.store = ConsoleStore(root / "console.db")
        self.outbox = ErpOutboxStore(root / "erp_outbox.db")
        self.line = {kode: LinePalsu() for kode in LINES}
        klien_line = LineClient(
            settings, transport=LinePerPort({PORT[k]: self.line[k].app for k in LINES})
        )
        viewer = root / "viewer.html"
        viewer.write_text("<html></html>")
        self.r2 = R2Palsu()
        self.halaman = VisitManifestWorker(
            self.store, ErpOutboxStore(root / "manifest_outbox.db"), self.r2,
            public_url="https://captures.example", viewer_html=viewer,
            clock=lambda: datetime.now(WIB).isoformat(),
        )
        self.service = ConsoleService(
            settings, self.store, klien_line,
            erp_queue=ErpQueue(self.store, self.outbox), manifest_queue=self.halaman,
        )
        self.erp = AutoErpPalsu()
        klien_erp = ErpClient("http://erp.local", "k", "s", transport=httpx.MockTransport(self.erp))
        self.erp_worker = ErpOutboxWorker(self.outbox, klien_erp, outbox_handlers(self.store, tz=WIB))
        self.mesin = TestClient(app_ingest(self.service))
        self._n = 0

    def janjang(self, line_code: str, *, status: str = "ACC") -> None:
        """Satu janjang lewat lane mesin, seperti OutboxRetryWorker line itu."""
        self._n += 1
        line = next(ln for ln in self.service.lines if ln.line_code == line_code)
        body = build_event_payload(
            machine_id=line.machine_id, file_ts=f"2026-09-28_07-41-{self._n:02d}_000000",
            timestamp=datetime.now(UTC).isoformat(), ripeness_status=status, ripeness_confidence=0.9,
            capture_type="auto", image_path=f"captures/results/2026-09-28/{self._n}.webp",
            truck_id=truck_id_for(PLAT),
            assignment_id=self.store.assignments()[line_code]["assignment_id"],
        )
        res = self.mesin.post(
            f"{self.settings.backend_api_ver}/internal/vision/events",
            json=body, headers={"x-webhook-secret": SECRET_WEBHOOK},
        )
        assert res.status_code == 201, res.text


@pytest.fixture
def pabrik(tmp_path) -> Pabrik:
    return Pabrik(tmp_path)


def _truk_dibongkar_di_tiga_line(pabrik: Pabrik) -> tuple[str, str]:
    """Timbang masuk, tiga line menerima truk, 3 + 2 + 4 janjang (3 ditolak), timbang keluar.

    Mengembalikan id tiket dan penugasan line-1, yang pertama tertaut (dibaca sebelum timbang
    keluar, sebab pelepasan mengosongkannya)."""
    tiket = asyncio.run(pabrik.service.record_weighing({
        "ref": "SCL-9", "plate_number": PLAT,
        "entered_at": datetime.now(WIB).isoformat(), "gross_kg": 14560,
    }))
    for kode in LINES:
        asyncio.run(pabrik.service.assign_truck(kode, truck_id_for(PLAT)))
    penugasan_line_1 = pabrik.store.assignments()["line-1"]["assignment_id"]
    for kode, ditolak, diterima in (("line-1", 1, 2), ("line-2", 0, 2), ("line-3", 2, 2)):
        for _ in range(diterima):
            pabrik.janjang(kode)
        for _ in range(ditolak):
            pabrik.janjang(kode, status="REJ")
    asyncio.run(pabrik.service.record_weighing({
        "ref": "SCL-9", "plate_number": PLAT, "tare_kg": 5400,
        "exited_at": datetime.now(WIB).isoformat(),
    }))
    return tiket["id"], penugasan_line_1


def test_timbang_keluar_melepas_ketiga_line_lewat_klien_sungguhan(pabrik):
    _truk_dibongkar_di_tiga_line(pabrik)

    assert pabrik.store.assignments_for_truck(truck_id_for(PLAT)) == []
    for kode in LINES:
        masuk, lepas = pabrik.line[kode].diterima
        assert masuk["assignment_id"] and masuk["truck_id"] == truck_id_for(PLAT)
        assert lepas["assignment_id"] == "" and lepas["truck_id"] == ""


def test_pesan_autoerp_membawa_jumlah_ketiga_line(pabrik):
    tiket, penugasan_line_1 = _truk_dibongkar_di_tiga_line(pabrik)

    assert asyncio.run(pabrik.erp_worker.drain_once()) >= 1

    grading = pabrik.erp.diterima[-1]["grading"]
    assert grading["counts"]["total"] == 9, "cuma satu line yang terkirim ke AutoERP"
    assert grading["counts"]["rej"] == 3
    # Nothing carrying the tare ever reached AutoERP with fewer than the three lines.
    dengan_tara = [k for k in pabrik.erp.diterima if "tare_kg" in k["weighing"]]
    assert dengan_tara and all(k["grading"]["counts"]["total"] == 9 for k in dengan_tara)
    # Satu penugasan jadi kunci tiket di AutoERP (unik): yang pertama tertaut, tetap sama tiap kirim ulang.
    assert grading["assignment_id"] == penugasan_line_1
    assert pabrik.store.weighing(tiket)["erp_status"] == "Finalised"


def test_halaman_detail_memuat_setiap_janjang_ketiga_line(pabrik):
    tiket, _ = _truk_dibongkar_di_tiga_line(pabrik)

    assert asyncio.run(pabrik.halaman.drain_once()) == 1

    manifest = json.loads(pabrik.r2.unggahan[f"visits/{tiket}.json"])
    assert manifest["counts"]["total"] == 9 and len(manifest["bunches"]) == 9
    assert manifest["line_code"] == "line-1, line-2, line-3"
    assert len({b["event_id"] for b in manifest["bunches"]}) == 9
