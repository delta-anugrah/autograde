"""End-to-end health jujur (batch 3.6) dan pemantau disk (batch 3.7).

Line: worker capture + deteksi ASLI (kamera dan model palsu), `PenjagaAi`,
`PemantauDisk` (disk palsu), `/health` asli, `HealthService.get_health_detail`
asli (torch palsu). Konsol: `LineClient` + `LineStatusWorker` + `ConsoleService`
+ `DevService` + router konsol ASLI dengan login sungguhan, lalu layar dirender
lewat node dengan KAMUS asli. Tanpa torch, kamera, PLC, atau ERP: jalan di CI.

Yang dilihat operator: kartu line merah + pita kamera berhenti mengirim gambar, dan
satu pita disk untuk seluruh layar, tanpa kode galat (2026-10-01); keduanya hilang
sendiri. Yang dilihat support: kartu
Diagnostik dengan fps, umur gambar, disk, dan PLC yang jujur.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from collections import namedtuple
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from ai_palsu import JAM_DINDING, LinePalsu
from fastapi import FastAPI
from fastapi.testclient import TestClient
from konsol_js import NODE, jalankan

import palmgrade.plc as plc
from palmgrade.core.config import Settings
from palmgrade.domain.kesehatan_disk import GB
from palmgrade.domain.operator_auth import hash_password
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.console import get_auth_service, get_console_service, get_dev_service
from palmgrade.routes.console import router as console_router
from palmgrade.routes.health_ringan import buat_router_health
from palmgrade.schemas.common_schema import HealthDetailSchema
from palmgrade.schemas.internal_schema import LineStatusResponse
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.dev_service import DevService
from palmgrade.services.health_service import HealthService
from palmgrade.services.pemantau_disk import PemantauDisk, ringkas_disk_dari_state
from palmgrade.services.penjaga_ai import ringkas_ai_dari_state
from palmgrade.workers import frame_capture_worker
from palmgrade.workers.line_status_worker import LineStatusWorker

SANDI = "sandi-e2e-health-jujur"
butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")
Usage = namedtuple("Usage", "total used free")
DIAG = ["tanda", "diagPlc", "diagAngka", "diagFrame", "diagDisk", "diagLisensi", "diagNol", "kartuDiagnostik"]
DASH = 'const dash = (v) => (v === null || v === undefined || v === "" ? KOSONG : esc(v));'


class _Outbox:
    def pending_count(self):
        return 0

    def failed_count(self):
        return 0


class DiskPalsu:
    def __init__(self) -> None:
        self.bebas_gb = 232.0

    def __call__(self, _jalur):
        total, bebas = 468 * GB, int(self.bebas_gb * GB)
        return Usage(total, total - bebas, bebas)


@pytest.fixture
def pabrik(tmp_path, monkeypatch):
    monkeypatch.setattr(frame_capture_worker.time, "sleep", lambda _detik: None)
    cuda = types.SimpleNamespace(is_available=lambda: False, get_device_name=lambda _i: "-")
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=cuda))
    plc_klien = types.SimpleNamespace(connected=False)
    monkeypatch.setattr(plc, "_worker", types.SimpleNamespace(
        client=plc_klien, inputs=[False] * 12, dropped_submissions=0,
        scheduler=types.SimpleNamespace(dropped=0), settings=types.SimpleNamespace(plc_coil_manual=None),
    ), raising=False)

    line = LinePalsu()
    line.kamera.bisa_sambung_ulang = True
    disk = DiskPalsu()
    line.state.pemantau_disk = PemantauDisk(
        settings=replace(line.settings, r2_bucket=""), jalur=(Path("/app/artifacts"),), ukur=disk,
        jam_dinding=lambda: JAM_DINDING + (line.jam.sekarang - 1_000.0),
    )
    health = HealthService(settings=line.settings, state=line.state, camera=line.kamera, outbox=_Outbox())

    # Sisi line: `/health` asli + pengganti `/internal/status` dan `/health/detail`
    # (yang asli menarik torch lewat `core.dependencies`), dibangun dari fungsi
    # yang SAMA dengan controller aslinya.
    line_app = FastAPI()
    line_app.include_router(buat_router_health(lambda: health))

    @line_app.get("/internal/status", response_model=LineStatusResponse)
    async def status() -> LineStatusResponse:
        return LineStatusResponse(machine_id="m-2", truck_id=None, ffb_source=None, piston=None,
                                  ai=ringkas_ai_dari_state(line.state),
                                  disk=ringkas_disk_dari_state(line.state))

    @line_app.get("/health/detail", response_model=HealthDetailSchema)
    async def detail() -> HealthDetailSchema:
        return health.get_health_detail()

    settings = replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta",
                       console_line_host="http://line")
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual(
        {"email": "support@pks.test", "full_name": "Support", "password_hash": hash_password(SANDI)}
    )
    store.set_role(store.operator_by_email("support@pks.test")["id"], "support")
    klien_line = LineClient(settings, transport=httpx.ASGITransport(app=line_app))
    service = ConsoleService(settings, store, klien_line)
    status_worker = LineStatusWorker(service.lines[1:2], klien_line)
    service.line_status = status_worker.snapshot

    konsol = FastAPI()
    konsol.include_router(console_router)
    konsol.dependency_overrides[get_console_service] = lambda: service
    konsol.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    konsol.dependency_overrides[get_dev_service] = lambda: DevService(
        LogStore(tmp_path / "log.db"), line_client=klien_line, lines=service.lines[1:2], settings=settings,
    )
    layar = TestClient(konsol)
    assert layar.post("/api/console/login", json={"email": "support@pks.test", "sandi": SANDI}).status_code == 200

    def poll():
        """Satu putaran worker status (tiap detik di konsol) + satu polling layar."""
        asyncio.run(status_worker.run_once())
        res = layar.get("/api/console/state")
        assert res.status_code == 200, res.text
        return res.json()["lines"]

    def kartu():
        return next(x for x in poll() if x["line_code"] == "line-2")

    return types.SimpleNamespace(line=line, disk=disk, plc_klien=plc_klien, http_line=TestClient(line_app),
                                 layar=layar, poll=poll, kartu=kartu)


def test_kamera_berhenti_mengirim_sampai_ke_kartu_operator_lalu_hilang_sendiri(pabrik):
    p = pabrik
    p.line.mulai()
    p.line.jalan(5)
    assert p.kartu()["plc"]["ai"]["keadaan"] == "sehat"

    p.line.kamera.mengirim = False               # Hikrobot diam, sambung ulangnya tetap berhasil
    p.line.jalan(40, deteksi=False)
    k = p.kartu()
    assert (k["plc"]["ai"]["keadaan"], k["plc"]["ai"]["kode"]) == ("frame_berhenti", "FRAME_BERHENTI")
    assert p.http_line.get("/health").status_code == 503
    assert p.http_line.get("/health/detail").status_code == 200

    # Gabungan: kamera masih diam (frame_berhenti) DAN disk sudah beralarm.
    # `/health/detail` tetap 200 dan status "ok" di kombinasi ini juga: itu yang
    # dipercaya `autograde reset-data` di host dan Danger Zone untuk menilai
    # line masih hidup, bukan mati (aturan 32; rute asli butuh torch, jadi
    # digantikan `detail()` di atas, dibangun dari fungsi yang sama).
    p.disk.bebas_gb = 3.0
    detail = p.http_line.get("/health/detail")
    assert detail.status_code == 200
    assert detail.json()["status"] == "ok"

    p.line.kamera.mengirim = True
    p.line.jalan(1)
    assert p.kartu()["plc"]["ai"]["keadaan"] == "sehat"
    assert p.http_line.get("/health").status_code == 200


@butuh_node
def test_kalimat_frame_berhenti_di_layar(pabrik):
    p = pabrik
    p.line.mulai()
    p.line.jalan(5)
    p.line.kamera.mengirim = False
    p.line.jalan(40, deteksi=False)
    html = jalankan(["jamSinkron", "aiMati", "pitaAi"], f"pitaAi({json.dumps(p.kartu())}, {JAM_DINDING + 60})")
    assert "Line 2: kamera berhenti mengirim gambar" in html
    assert "Sejak 21.13." in html and "FRAME_BERHENTI" not in html


def test_video_uji_yang_habis_tidak_terbaca_rusak(pabrik):
    p = pabrik
    p.line.mulai()
    p.line.jalan(5)
    p.line.kamera.habis = True
    p.line.jalan(40, deteksi=False)
    assert p.kartu()["plc"]["ai"]["keadaan"] == "sumber_selesai"
    assert p.http_line.get("/health").status_code == 200


@butuh_node
def test_disk_hampir_penuh_muncul_di_layar_lalu_hilang_sendiri(pabrik):
    p = pabrik
    assert jalankan(["jamSinkron", "gabungDisk", "pitaDisk"], f"pitaDisk({json.dumps(p.poll())})") == ""

    p.disk.bebas_gb = 12.0
    html = jalankan(["jamSinkron", "gabungDisk", "pitaDisk"], f"pitaDisk({json.dumps(p.poll())}, {JAM_DINDING + 60})")
    assert "Disk PC hampir penuh" in html
    assert "Sejak 21.13, dilaporkan Line 2. Sisa 12 GB dari 468 GB." in html
    assert "DISK_HAMPIR_PENUH" not in html

    p.disk.bebas_gb = 3.0
    html = jalankan(["jamSinkron", "gabungDisk", "pitaDisk"], f"pitaDisk({json.dumps(p.poll())}, {JAM_DINDING + 60})")
    assert 'class="kritis"' in html and "Disk PC hampir habis" in html

    p.disk.bebas_gb = 40.0
    assert jalankan(["jamSinkron", "gabungDisk", "pitaDisk"], f"pitaDisk({json.dumps(p.poll())})") == ""


@butuh_node
def test_diagnostik_support_membaca_detail_line_sungguhan(pabrik):
    p = pabrik
    p.line.mulai()
    p.line.jalan(12)
    p.disk.bebas_gb = 12.0
    lines = p.layar.get("/api/console/dev/diagnostik").json()["lines"]
    html = jalankan(DIAG, f"kartuDiagnostik('line-2', {json.dumps(lines['line-2'])})", tambahan=DASH)
    assert "<dt>FPS kamera / deteksi</dt><dd>1 / " in html
    assert "<dt>Gambar terakhir</dt><dd>1 dtk lalu</dd>" in html
    assert '<dt>Disk</dt><dd><span class="tanda-waspada">12 GB bebas (2,6%)</span></dd>' in html
    assert '<dt>PLC</dt><dd><span class="tanda-gagal">✗</span></dd>' in html   # menyala, tidak tersambung

    p.plc_klien.connected = True
    lines = p.layar.get("/api/console/dev/diagnostik").json()["lines"]
    html = jalankan(DIAG, f"kartuDiagnostik('line-2', {json.dumps(lines['line-2'])})", tambahan=DASH)
    assert '<dt>PLC</dt><dd><span class="tanda-ok">✓</span></dd>' in html
