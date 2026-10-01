"""End to end (batch 3.2 + 3.5): support membuka tab Log sesudah line direstart.

Cerita yang dibuktikan: line menulis ERROR bertraceback, container line dibuat ulang
(`--force-recreate`, docker logs kosong), konsol menarik log line itu, dan support yang
masuk lewat HTTP sungguhan melihat barisnya di `GET /api/console/dev/log` dengan tag
line, waktu pertama, dan traceback; layar menggambarnya lewat fungsi `barisLog` asli.
Tab Log juga menyebut keadaan lapor Discord (`GET /api/console/dev/lapor-discord`).

App dirakit sendiri, bukan `create_console_app()` (yang menyentuh `state/` developer).
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from zoneinfo import ZoneInfo

import httpx
import pytest
from antrean_line_rakit import LinePerPort
from fastapi import FastAPI
from fastapi.testclient import TestClient
from konsol_js import NODE, jalankan

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.domain.kirim_discord import JEDA_KUMPUL_S
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.role import ROLE_OPERATOR, ROLE_SUPPORT
from palmgrade.integrations.notifications.discord_client import DiscordClient
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.lapor_discord_repository import LaporDiscordStore
from palmgrade.repositories.log_line_repository import LogLineStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.console import router as console_router
from palmgrade.routes.console_deps import get_auth_service, get_console_service, get_dev_service, get_lapor_discord
from palmgrade.routes.console_lapor_discord import router as lapor_router
from palmgrade.routes.internal_log import buat_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.dev_service import DevService
from palmgrade.services.lapor_discord import LaporDiscord
from palmgrade.workers.lapor_discord_worker import LaporDiscordWorker
from palmgrade.workers.tarik_log_line_worker import TarikLogLineWorker

SANDI = "sokongan2026"
SECRET = "kunci-internal-palsu"
URL = "https://discord.com/api/webhooks/1/token-palsu"
LINE_1 = LineEndpoint("line-1", "Line 1", 8001, "m-1")
butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada (image CI)")


class _StubConsole:
    def __init__(self, store: ConsoleStore) -> None:
        self.store = store


class _Jam:
    def __init__(self) -> None:
        self.t = 1_790_737_200.0

    def __call__(self) -> float:
        return self.t


def _app_line(folder) -> tuple[FastAPI, LogLineStore]:
    """Satu proses line: berkas log di folder DB-nya, router asli."""
    store = LogLineStore(folder / "log_line.db")
    settings = replace(Settings(), internal_secret=SECRET)
    app = FastAPI()
    app.include_router(buat_router(settings=lambda: settings, store=lambda: store))
    return app, store


@pytest.fixture
def pabrik(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    for email, role in (("support@pks.test", ROLE_SUPPORT), ("operator@pks.test", ROLE_OPERATOR)):
        store.upsert_operator_manual(
            {"email": email, "nama": email, "password_hash": hash_password(SANDI), "role": role}
        )
    log_store = LogStore(tmp_path / "log.db")
    jam = _Jam()
    lapor = LaporDiscord(URL, LaporDiscordStore(tmp_path / "lapor_discord.db", jam=jam))

    app = FastAPI()
    app.include_router(console_router)
    app.include_router(lapor_router)
    app.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_dev_service] = lambda: DevService(log_store)
    app.dependency_overrides[get_lapor_discord] = lambda: lapor
    return TestClient(app), log_store, lapor, jam


def _masuk(client: TestClient, email: str) -> None:
    assert client.post("/api/console/login", json={"email": email, "sandi": SANDI}).status_code == 200


def _tarik(line_app: FastAPI, log_store: LogStore, lapor: LaporDiscord, jam: _Jam) -> None:
    klien = LineClient(
        replace(Settings(), console_line_host="http://line", internal_secret=SECRET),
        transport=LinePerPort({8001: line_app}),
    )
    asyncio.run(TarikLogLineWorker([LINE_1], klien, log_store, digest=lapor.store, jam=jam).run_once())


def test_support_melihat_galat_line_dari_sebelum_restart_dengan_traceback(pabrik, tmp_path):
    client, log_store, lapor, jam = pabrik
    _, sebelum = _app_line(tmp_path / "state-line-1")
    sebelum.write("ERROR", "palmgrade.workers.frame_capture_worker", "grab kamera gagal",
                  "Traceback (most recent call last):\nRuntimeError: MV_E_NODATA", now=jam.t - 120)
    # Galat yang sama lagi (baris terakhir traceback sama): tergabung jadi satu baris.
    sebelum.write("ERROR", "palmgrade.workers.frame_capture_worker", "grab kamera gagal",
                  "Traceback (most recent call last):\nRuntimeError: MV_E_NODATA", now=jam.t - 90)

    line_baru, _ = _app_line(tmp_path / "state-line-1")  # container dibuat ulang, berkas sama
    _tarik(line_baru, log_store, lapor, jam)
    _masuk(client, "support@pks.test")

    (baris,) = client.get("/api/console/dev/log?cari=line-1").json()["items"]

    assert (baris["line_code"], baris["message"], baris["count"]) == ("line-1", "grab kamera gagal", 2)
    assert baris["logged_at"] == jam.t - 120
    assert "MV_E_NODATA" in baris["detail"]
    if NODE is not None:
        html = jalankan(
            ["waktu", "waktuLog", "sumberLog", "pesanLog", "barisLog"], f"barisLog({json.dumps(baris)})"
        )
        assert '<span class="log-asal">line-1</span>' in html
        assert "pertama 30/09/2026 09:58:00" in html
        assert "<pre>Traceback (most recent call last):\nRuntimeError: MV_E_NODATA</pre>" in html
        assert "×2" in html


def test_operator_biasa_tidak_bisa_membaca_keadaan_lapor(pabrik):
    client, *_ = pabrik
    _masuk(client, "operator@pks.test")
    assert client.get("/api/console/dev/lapor-discord").status_code == 403


@butuh_node
def test_tab_log_menyebut_discord_ditolak_lalu_pulih(pabrik, tmp_path):
    """Webhook salah (404): support melihat DITOLAK dengan jam, kode, dan tindakan;
    sesudah webhook benar pesan yang sama terkirim, tidak ada yang dibuang."""
    client, log_store, lapor, jam = pabrik
    line_app, line_store = _app_line(tmp_path / "state-line-1")
    line_store.write("ERROR", "palmgrade.x", "AI berhenti memproses", None, now=jam.t)
    _tarik(line_app, log_store, lapor, jam)

    jawaban = {"status": 404}
    diterima: list[str] = []

    def discord(req: httpx.Request) -> httpx.Response:
        if jawaban["status"] == 204:
            diterima.append(json.loads(req.content)["content"])
        return httpx.Response(jawaban["status"])

    worker = LaporDiscordWorker(
        lapor.store, DiscordClient(URL, transport=httpx.MockTransport(discord)),
        identitas="PT Uji", versi="v9", zona=ZoneInfo("Asia/Jakarta"), jam=jam,
    )
    jam.t += JEDA_KUMPUL_S
    asyncio.run(worker.run_once())
    _masuk(client, "support@pks.test")

    ditolak = client.get("/api/console/dev/lapor-discord").json()
    assert (ditolak["keadaan"], ditolak["status_http"], ditolak["kiriman"]) == ("ditolak", 404, 1)
    assert URL not in json.dumps(ditolak)
    kalimat = jalankan(["waktu", "teksLaporDiscord"], f"teksLaporDiscord({json.dumps(ditolak)})")
    assert kalimat["kelas"] == "gagal"
    assert "(HTTP 404)" in kalimat["teks"] and "autograde restart" in kalimat["teks"]

    jawaban["status"] = 204
    jam.t += 3600
    asyncio.run(worker.run_once())

    pulih = client.get("/api/console/dev/lapor-discord").json()
    assert (pulih["keadaan"], pulih["kiriman"]) == ("aktif", 0)
    assert "AI berhenti memproses" in diterima[0]
