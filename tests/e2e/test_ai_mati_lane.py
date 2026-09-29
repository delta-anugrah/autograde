"""End-to-end AI mati (batch 2.1), dari CUDA yang rusak sampai kalimat di layar.

Line: worker capture + deteksi ASLI (kamera dan model palsu), `PenjagaAi`,
`/health` asli. Konsol: `LineClient` + `LineStatusWorker` + `ConsoleService` +
router konsol ASLI dengan login sungguhan, lalu kartu line dirender lewat node
dengan KAMUS asli. Tanpa torch, kamera, PLC, atau ERP: jalan di CI.

Yang dilihat operator: kartu line merah + pita "AI berhenti memproses" dengan
kode, line, jam, dan tindakan; hilang sendiri begitu AI pulih, tanpa sentuhan.
Yang dilihat Docker/launcher: `/health` 503 selama AI mati.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from ai_palsu import JAM_DINDING, LinePalsu
from fastapi import FastAPI
from fastapi.testclient import TestClient
from konsol_js import NODE, jalankan

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.routes.health_ringan import buat_router_health
from palmgrade.schemas.internal_schema import LineStatusResponse
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.health_service import HealthService
from palmgrade.services.penjaga_ai import ringkas_ai_dari_state
from palmgrade.workers.line_status_worker import LineStatusWorker

SANDI = "sandi-e2e-ai-mati"
butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")


class _Outbox:
    def pending_count(self):
        return 0

    def failed_count(self):
        return 0


@pytest.fixture
def pabrik(tmp_path):
    line = LinePalsu()

    # Sisi line: `/health` asli + pengganti `/internal/status` (yang asli menarik torch).
    line_app = FastAPI()
    health = HealthService(settings=line.settings, state=line.state, camera=line.kamera, outbox=_Outbox())
    line_app.include_router(buat_router_health(lambda: health))

    @line_app.get("/internal/status", response_model=LineStatusResponse)
    async def status() -> LineStatusResponse:
        return LineStatusResponse(machine_id="m-2", truck_id=None, ffb_source=None,
                                  piston=None, ai=ringkas_ai_dari_state(line.state))

    # Sisi konsol, dirakit seperti console_main (tanpa `create_console_app()`,
    # yang menyentuh state/ developer).
    settings = replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta",
                       console_line_host="http://line")
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual(
        {"email": "operator@pks.test", "full_name": "Operator", "password_hash": hash_password(SANDI)}
    )
    klien_line = LineClient(settings, transport=httpx.ASGITransport(app=line_app))
    service = ConsoleService(settings, store, klien_line)
    status_worker = LineStatusWorker(service.lines[1:2], klien_line)
    service.line_status = status_worker.snapshot

    konsol = FastAPI()
    konsol.include_router(console_router)
    konsol.dependency_overrides[get_console_service] = lambda: service
    konsol.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    operator = TestClient(konsol)
    masuk = operator.post("/api/console/login", json={"email": "operator@pks.test", "sandi": SANDI})
    assert masuk.status_code == 200, masuk.text

    def layar():
        """Satu putaran worker status (tiap detik di konsol) + satu polling layar."""
        asyncio.run(status_worker.run_once())
        res = operator.get("/api/console/state")
        assert res.status_code == 200, res.text
        return next(x for x in res.json()["lines"] if x["line_code"] == "line-2"), res.text

    return line, TestClient(line_app), layar


def test_cuda_rusak_sampai_ke_kartu_operator_lalu_hilang_sendiri(pabrik):
    line, http_line, layar = pabrik
    line.mulai()
    line.jalan(5)
    kartu, _ = layar()
    assert kartu["plc"]["ai"]["keadaan"] == "sehat"

    line.pipeline.galat = RuntimeError("CUDA error: an illegal memory access was encountered")
    line.jalan(31)
    line.capture.run_once()

    kartu, mentah = layar()
    assert kartu["plc"]["ai"]["mati"] is True
    assert kartu["plc"]["ai"]["kode"] == "AI_MATI"
    assert kartu["plc"]["ai"]["sejak"] == JAM_DINDING + 4
    assert "illegal memory access" not in mentah, "galat mentah bukan untuk layar operator"
    assert http_line.get("/health").status_code == 503

    line.pipeline.galat = None
    line.jalan(1)
    kartu, _ = layar()
    assert kartu["plc"]["ai"]["mati"] is False
    assert http_line.get("/health").status_code == 200


@butuh_node
def test_kalimat_di_layar_memuat_kode_line_jam_dan_tindakan(pabrik):
    line, _, layar = pabrik
    line.mulai()
    line.jalan(5)
    line.pipeline.galat = RuntimeError("CUDA error")
    line.jalan(31)
    kartu, _ = layar()

    html = jalankan(["jamSinkron", "aiMati", "pitaAi"],
                    f"pitaAi({json.dumps(kartu)}, {JAM_DINDING + 60})")
    assert "Line 2: AI berhenti memproses" in html
    assert "Kode AI_MATI, sejak 21.13." in html
    assert "Tahan umpan buah ke line ini dan panggil teknisi" in html


def test_baru_menyala_tidak_pernah_merah(pabrik):
    """Tenggang start: gambar sudah masuk, frame pertama belum selesai."""
    line, http_line, layar = pabrik
    line.mulai()
    line.jalan(20, deteksi=False)
    kartu, _ = layar()
    assert (kartu["plc"]["ai"]["keadaan"], kartu["plc"]["ai"]["mati"]) == ("memulai", False)
    assert http_line.get("/health").status_code == 200
