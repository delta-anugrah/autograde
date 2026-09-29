"""End-to-end (batch 2.3): janjang susulan sampai ke AutoERP, dan tiket final yang tidak
bisa dibetulkan terlihat di layar.

Jalur yang dilalui jalur pabrik: timbang masuk dan keluar dari lane operator, janjang
dari lane mesin (`x-webhook-secret`), `ErpOutboxWorker` + `ErpClient` asli ke AutoERP
tiruan (`tests/autoerp_palsu.py`, aturan finalisasi `upsert_visit` yang sama), lalu yang
dibaca operator (tab Timbangan) dan support (tab Log, lewat log sink yang asli).
Tandanya digambar `tandaErp` console.html lewat node dengan kamus yang asli.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from autoerp_palsu import AutoErpPalsu
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.core.log_sink import install_log_sink
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.plate import truck_id_for
from palmgrade.domain.vision_event import build_event_payload
from palmgrade.integrations.erp.client import ErpClient
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.console import get_auth_service, get_console_service, get_dev_service
from palmgrade.routes.console import router as console_router
from palmgrade.routes.console_ingest import ingest_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.dev_service import DevService
from palmgrade.services.erp_queue import ErpQueue
from palmgrade.workers.erp_link import outbox_handlers
from palmgrade.workers.erp_outbox_worker import ErpOutboxWorker

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()
NODE = shutil.which("node")
SANDI = "sandi-e2e-susulan"
SECRET = "kunci-e2e-palsu"
PLAT = "BE 8821 KL"
WIB = ZoneInfo("Asia/Jakarta")


class _Line:
    async def assign_truck(self, line, **_kw) -> None: ...


class Pabrik:
    def __init__(self, root: Path) -> None:
        self.settings = replace(Settings(), repo_root=root, factory_tz="Asia/Jakarta",
                                webhook_secret=SECRET, erp_url="http://erp.local")
        store = ConsoleStore(root / "console.db")
        for email, role in (("operator@pks.test", "operator"), ("support@pks.test", "support")):
            store.upsert_operator_manual(
                {"email": email, "full_name": email, "password_hash": hash_password(SANDI), "role": role}
            )
        outbox = ErpOutboxStore(root / "erp_outbox.db")
        self.service = ConsoleService(self.settings, store, _Line(), erp_queue=ErpQueue(store, outbox))
        self.erp = AutoErpPalsu()
        klien = ErpClient("http://erp.local", "k", "s", transport=httpx.MockTransport(self.erp))
        self.worker = ErpOutboxWorker(outbox, klien, outbox_handlers(store, tz=WIB))
        self.log = LogStore(root / "log.db")
        dev = DevService(self.log, console_store=store, settings=self.settings)
        app = FastAPI()
        app.include_router(console_router)
        app.include_router(ingest_router, prefix=self.settings.backend_api_ver)
        app.dependency_overrides[get_console_service] = lambda: self.service
        app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
        app.dependency_overrides[get_dev_service] = lambda: dev
        self.app = app
        self._n = 0

    def masuk(self, email: str) -> TestClient:
        client = TestClient(self.app)
        res = client.post("/api/console/login", json={"email": email, "sandi": SANDI})
        assert res.status_code == 200, res.text
        return client

    def janjang(self, client: TestClient, assignment_id: str, status: str = "ACC") -> None:
        self._n += 1
        body = build_event_payload(
            machine_id=self.service.lines[0].machine_id, file_ts=f"2026-09-28_07-41-{self._n:02d}_000000",
            timestamp=datetime.now(UTC).isoformat(), ripeness_status=status, ripeness_confidence=0.9,
            capture_type="auto", image_path=f"captures/results/2026-09-28/{self._n}.webp",
            truck_id=truck_id_for(PLAT), assignment_id=assignment_id,
        )
        res = client.post(f"{self.settings.backend_api_ver}/internal/vision/events",
                          json=body, headers={"x-webhook-secret": SECRET})
        assert res.status_code == 201, res.text

    def truk_selesai(self, operator: TestClient) -> str:
        """Timbang masuk, tugaskan ke line-1, tiga janjang, timbang keluar (melepas line).

        Jam masuk dikirim seperti tombol Timbang masuk mengirimnya: `new Date().toISOString()`,
        UTC dengan `Z`."""
        self.masuk_utc = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        res = operator.post("/api/console/weighings", json={
            "ref": "SCL-7", "plate_number": PLAT, "entered_at": self.masuk_utc, "gross_kg": 14560,
        })
        assert res.status_code == 201, res.text
        res = operator.post("/api/console/lines/line-1/assign-truck", json={"truck_id": truck_id_for(PLAT)})
        assert res.status_code == 200, res.text
        assignment_id = res.json()["assignment_id"]
        for _ in range(3):
            self.janjang(operator, assignment_id)
        res = operator.post("/api/console/weighings", json={
            "ref": "SCL-7", "plate_number": PLAT, "tare_kg": 5400, "exited_at": datetime.now(WIB).isoformat(),
        })
        assert res.status_code == 201, res.text
        return assignment_id

    def kirim(self) -> int:
        return asyncio.run(self.worker.drain_once())

    def kirim_ulang_harian(self) -> None:
        self.service.erp_queue.visits_on(self.service.today(), tz=self.service.tz)


@pytest.fixture
def pabrik(tmp_path):
    p = Pabrik(tmp_path)
    sink = install_log_sink(p.log)
    yield p
    logging.getLogger().removeHandler(sink)


def _tiket(operator: TestClient) -> dict:
    [baris] = operator.get("/api/console/weighings").json()["items"]
    return baris


def _log(pabrik: Pabrik, cari: str) -> list[dict]:
    support = pabrik.masuk("support@pks.test")
    return support.get("/api/console/dev/log", params={"cari": cari}).json()["items"]


def test_janjang_susulan_sebelum_kiriman_berangkat_masuk_rekap_pertama(pabrik):
    operator = pabrik.masuk("operator@pks.test")
    assignment_id = pabrik.truk_selesai(operator)
    pabrik.janjang(operator, assignment_id, status="REJ")    # masih di antrean simpan line

    assert pabrik.kirim() == 1

    assert [k["grading"]["counts"]["total"] for k in pabrik.erp.diterima] == [4]
    assert (_tiket(operator)["erp_status"], _tiket(operator)["erp_perlu_dicek"]) == ("Finalised", None)


def test_tiket_final_yang_menerima_janjang_susulan_ditandai_untuk_operator_dan_support(pabrik):
    operator = pabrik.masuk("operator@pks.test")
    assignment_id = pabrik.truk_selesai(operator)
    assert pabrik.kirim() == 1                                # final dengan 3 janjang
    pabrik.janjang(operator, assignment_id, status="REJ")    # konsol sempat tidak terjangkau

    assert pabrik.kirim() == 1

    assert [k["grading"]["counts"]["total"] for k in pabrik.erp.diterima] == [3, 4]
    tiket = _tiket(operator)
    assert (tiket["erp_ticket"], tiket["erp_perlu_dicek"]) == ("WB-2026-00001", "tiket_final_berbeda")
    [catatan] = _log(pabrik, "TIKET_FINAL_BERBEDA")
    assert catatan["level"] == "WARNING"
    jam_pabrik = datetime.fromisoformat(pabrik.masuk_utc).astimezone(WIB).strftime("%Y-%m-%d %H:%M")
    assert f"Truk BE 8821 KL, line-1, timbang masuk {jam_pabrik}: " in catatan["message"]
    assert "Yang berbeda: grading berubah. Rekap pabrik sekarang: 4 janjang, mentah 25%. " in catatan["message"]
    assert "WB-2026-00001" in catatan["message"] and "Tindakan: " in catatan["message"]


def test_kirim_ulang_harian_tiket_final_yang_sama_tidak_mengisi_tab_log(pabrik):
    operator = pabrik.masuk("operator@pks.test")
    pabrik.truk_selesai(operator)
    assert pabrik.kirim() == 1
    pabrik.kirim_ulang_harian()

    assert pabrik.kirim() == 1                                # "visit unchanged"

    assert _tiket(operator)["erp_perlu_dicek"] is None
    assert _log(pabrik, "TIKET_") == []


def test_kirim_ulang_harian_tiket_yang_sudah_ditandai_tidak_mencatat_lagi(pabrik):
    """AutoERP membandingkan dengan angka yang dibukukan, jadi kirim ulang rekap yang sama
    dijawab "grading revised" lagi. Satu WARNING per perubahan: tandanya tetap di baris."""
    operator = pabrik.masuk("operator@pks.test")
    assignment_id = pabrik.truk_selesai(operator)
    pabrik.kirim()
    pabrik.janjang(operator, assignment_id, status="REJ")
    pabrik.kirim()
    pabrik.kirim_ulang_harian()

    assert pabrik.kirim() == 1

    assert pabrik.erp.diterima[-1]["grading"]["counts"]["total"] == 4
    assert _tiket(operator)["erp_perlu_dicek"] == "tiket_final_berbeda"
    [catatan] = _log(pabrik, "TIKET_FINAL_BERBEDA")
    assert catatan["count"] == 1


@pytest.mark.skipif(NODE is None, reason="node tidak ada (image CI)")
def test_tanda_tergambar_di_baris_timbangan_dengan_kamus_asli(pabrik):
    operator = pabrik.masuk("operator@pks.test")
    assignment_id = pabrik.truk_selesai(operator)
    pabrik.kirim()
    # REJ, bukan ACC: AutoERP membandingkan PERSEN, dan 4 ACC sama dengan 3 ACC (0% mentah).
    pabrik.janjang(operator, assignment_id, status="REJ")
    pabrik.kirim()

    awal = HTML.index("function tandaErp(")
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    skrip = (
        'const esc = (s) => String(s ?? "").replace(/[&<>"\'`]/g, (c) =>'
        ' ({"&":"&amp;","<":"&lt;",">":"&gt;",\'"\':"&quot;","\'":"&#39;","`":"&#96;"}[c]));\n'
        'const KOSONG = "-";\n'
        f"const KAMUS = {{{kamus}\n}};\n"
        'const bahasa = "id";\nconst t = (k) => KAMUS[bahasa][k] ?? k;\n'
        + HTML[awal : HTML.index("\n}", awal) + 2]
        + f"\nconsole.log(tandaErp({json.dumps(_tiket(operator))}));"
    )
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)

    assert hasil.returncode == 0, hasil.stderr[-800:]
    assert 'class="tag no"' in hasil.stdout and "Cek AutoERP" in hasil.stdout
    assert "Tiket WB-2026-00001 sudah final di AutoERP" in hasil.stdout
