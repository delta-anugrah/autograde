"""Galat line sampai ke Discord lewat komponen SUNGGUHAN (batch 3.2 + 3.5).

Line (`LogLineStore` + router `/internal/log`) → `LineClient` → `TarikLogLineWorker` →
`LogStore` + `LaporDiscordStore` → `LaporDiscordWorker` → `DiscordClient` →
`httpx.MockTransport` (Discord tidak pernah dipanggil). Plus galat konsol sendiri lewat
handler ERROR yang asli, layar support lewat rute yang asli, dan lifespan konsol yang asli.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from zoneinfo import ZoneInfo

import httpx
from antrean_line_rakit import LinePerPort, app_konsol, masuk
from fastapi import FastAPI

from palmgrade import console_main
from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.domain.kirim_discord import JEDA_KUMPUL_S
from palmgrade.domain.role import ROLE_OPERATOR, ROLE_SUPPORT
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.integrations.notifications.discord_client import DiscordClient
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.lapor_discord_repository import LaporDiscordStore
from palmgrade.repositories.log_line_repository import LogLineStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes import console_deps
from palmgrade.routes.console_lapor_discord import router as lapor_discord_router
from palmgrade.routes.internal_log import buat_router
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.erp_queue import ErpQueue
from palmgrade.services.lapor_discord import LaporDiscord, pasang_handler_lapor
from palmgrade.services.pantau_antrean_line import PantauAntreanLine
from palmgrade.workers.lapor_discord_worker import LaporDiscordWorker
from palmgrade.workers.tarik_log_line_worker import TarikLogLineWorker

SECRET = "kunci-internal-palsu"
URL = "https://discord.com/api/webhooks/1/token-palsu"
LINE_2 = LineEndpoint("line-2", "Line 2", 8002, "m-2")


class _Jam:
    def __init__(self) -> None:
        self.t = 1_790_737_200.0

    def __call__(self) -> float:
        return self.t


def _rakit(tmp_path, jam: _Jam):
    line_store = LogLineStore(tmp_path / "line-2" / "log_line.db")
    settings_line = replace(Settings(), internal_secret=SECRET)
    line_app = FastAPI()
    line_app.include_router(buat_router(settings=lambda: settings_line, store=lambda: line_store))

    diterima: list[dict] = []

    def discord(req: httpx.Request) -> httpx.Response:
        diterima.append(json.loads(req.content))
        return httpx.Response(204)

    log_store = LogStore(tmp_path / "log.db")
    lapor = LaporDiscordStore(tmp_path / "lapor_discord.db", jam=jam)
    klien_line = LineClient(
        replace(Settings(), console_line_host="http://line", internal_secret=SECRET),
        transport=LinePerPort({8002: line_app}),
    )
    tarik = TarikLogLineWorker([LINE_2], klien_line, log_store, digest=lapor, jam=jam)
    kirim = LaporDiscordWorker(
        lapor, DiscordClient(URL, transport=httpx.MockTransport(discord)),
        identitas="PT Uji (host pc-uji)", versi="v9.9.9", zona=ZoneInfo("Asia/Jakarta"), jam=jam,
    )
    return line_store, lapor, tarik, kirim, diterima


def test_error_line_dan_error_konsol_satu_ringkasan_warning_tidak_ikut(tmp_path):
    jam = _Jam()
    line_store, lapor, tarik, kirim, diterima = _rakit(tmp_path, jam)
    for _ in range(3):
        line_store.write("ERROR", "palmgrade.workers.frame_capture_worker", "grab kamera gagal", "Traceback BARIS-DALAM", now=jam.t)
    line_store.write("WARNING", "palmgrade.plc", "plc lambat", None, now=jam.t)
    handler = pasang_handler_lapor(lapor)
    try:
        logging.getLogger("palmgrade.uji.konsol").error("AutoERP menolak kunjungan token=rahasia123")
    finally:
        logging.getLogger().removeHandler(handler)

    asyncio.run(tarik.run_once())
    jam.t += JEDA_KUMPUL_S
    asyncio.run(kirim.run_once())

    (pesan,) = diterima
    isi = pesan["content"]
    assert pesan["allowed_mentions"] == {"parse": []}
    assert "3x line-2 · palmgrade.workers.frame_capture_worker: `grab kamera gagal`" in isi
    assert "1x konsol · palmgrade.uji.konsol: `AutoERP menolak kunjungan token=«redacted»`" in isi
    assert "plc lambat" not in isi
    assert "rahasia123" not in isi
    assert "BARIS-DALAM" not in isi  # traceback tidak keluar pabrik


def test_tarikan_ulang_tidak_menggandakan_hitungan_di_ringkasan(tmp_path):
    jam = _Jam()
    line_store, lapor, tarik, kirim, diterima = _rakit(tmp_path, jam)
    line_store.write("ERROR", "palmgrade.x", "grab gagal", None, now=jam.t)
    asyncio.run(tarik.run_once())
    jam.t += 11
    line_store.write("ERROR", "palmgrade.x", "grab gagal", None, now=jam.t)  # digabung di line
    asyncio.run(tarik.run_once())
    asyncio.run(tarik.run_once())

    jam.t += JEDA_KUMPUL_S
    asyncio.run(kirim.run_once())

    assert "2x line-2" in diterima[0]["content"]


# ── Layar support: rute → service → store yang asli ─────────────────────────


def test_layar_support_membaca_keadaan_tanpa_alamat_webhook(tmp_path):
    lapor = LaporDiscordStore(tmp_path / "lapor_discord.db")
    lapor.write("ERROR", "palmgrade.x", "kamera putus", None, now=1.0)
    lapor.susun(lambda kelompok: ["isi ringkasan"], now=2.0)
    lapor.tandai_gagal(lapor.kiriman_berikut().id, galat="Discord menjawab HTTP 404", status_http=404, now=3.0)

    store = ConsoleStore(tmp_path / "console.db")
    app = app_konsol(store, PantauAntreanLine(LineClient(Settings()), ()))
    app.include_router(lapor_discord_router)
    app.dependency_overrides[console_deps.get_lapor_discord] = lambda: LaporDiscord(URL, lapor)

    support = masuk(app, store, role=ROLE_SUPPORT)
    jawab = support.get("/api/console/dev/lapor-discord")

    assert jawab.status_code == 200
    isi = jawab.json()
    assert (isi["keadaan"], isi["status_http"], isi["kiriman"], isi["galat_at"]) == ("ditolak", 404, 1, 3.0)
    assert "token-palsu" not in jawab.text
    operator = masuk(app, store, role=ROLE_OPERATOR, sandi="sandi-operator-uji")
    assert operator.get("/api/console/dev/lapor-discord").status_code == 403


# ── Lifespan konsol yang asli ─────────────────────────────────────────────────


def _layanan(tmp_path, url: str = URL) -> ConsoleService:
    # repo_root di tmp_path: state_dir (console.db, log, lapor_discord.db) ikut ke sana,
    # tidak pernah ke state/ milik developer.
    settings = Settings(
        repo_root=tmp_path, discord_webhook_url=url,
        console_default_hash="", console_support_hash="", erp_url="",
    )
    store = ConsoleStore(settings.console_db_path)
    erp_queue = ErpQueue(store, ErpOutboxStore(settings.erp_outbox_db_path))
    return ConsoleService(settings, store, LineClient(settings), erp_queue=erp_queue)


def _kosongkan_singleton() -> None:
    console_deps.get_auth_service.cache_clear()
    console_deps.get_dev_service.cache_clear()
    console_deps.get_lapor_discord.cache_clear()


def _jalankan_lifespan(service: ConsoleService, selama) -> list[logging.Handler]:
    """Satu kali lewat `lifespan` konsol; mengembalikan handler root SESUDAH lifespan
    selesai, sebelum dipulihkan (untuk memeriksa apa yang tertinggal)."""
    original = console_main.get_console_service
    original_deps = console_deps.get_console_service
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    console_main.get_console_service = lambda: service
    console_deps.get_console_service = lambda: service
    _kosongkan_singleton()
    try:
        async def _runner() -> None:
            async with console_main.lifespan(FastAPI()):
                selama()

        asyncio.run(_runner())
        return list(root.handlers)
    finally:
        console_main.get_console_service = original
        console_deps.get_console_service = original_deps
        _kosongkan_singleton()
        root.handlers = original_handlers


def test_konsol_menyala_walau_berkas_antrean_discord_rusak(tmp_path):
    """Carry B-T7 no. 1: berkas rusak = lapor Discord mati, konsol tetap menyala, layar
    support menyebutnya, dan alasannya tercatat di tab Log."""
    service = _layanan(tmp_path)
    jalur = service.settings.lapor_discord_db_path
    jalur.parent.mkdir(parents=True, exist_ok=True)
    jalur.write_bytes(b"bukan basis data sqlite " * 64)
    terlihat = {}

    _jalankan_lifespan(service, lambda: terlihat.update(console_deps.get_lapor_discord().ringkasan()))

    assert terlihat["keadaan"] == "rusak"
    log = LogStore(service.settings.log_db_path)
    (baris,) = log.read(level="WARNING", search="lapor_discord.db", limit=10, offset=0)["items"]
    assert "DatabaseError" in baris["message"]
    assert URL not in baris["message"]


def test_handler_lapor_dilepas_saat_konsol_berhenti(tmp_path):
    """R3c: handler lapor terpasang selama konsol hidup dan dilepas sesudah worker
    dihentikan, supaya proses (atau test) berikutnya tidak menulis ke store yang lama."""
    service = _layanan(tmp_path)
    terpasang = {}

    def selama() -> None:
        store = console_deps.get_lapor_discord().store
        terpasang["ada"] = any(getattr(h, "_store", None) is store for h in logging.getLogger().handlers)

    sisa = _jalankan_lifespan(service, selama)

    assert terpasang["ada"] is True
    assert not [h for h in sisa if type(h).__name__ == "_HandlerLapor"]


def test_konsol_menyala_walau_alamat_webhook_idna_rusak(tmp_path):
    """`https://xn--a.com/...` lolos pemeriksaan awalan, host, dan port, tapi host IDNA-nya
    tidak bisa didekode: `httpx.URL(...).host` melempar `idna.InvalidCodepoint` (turunan
    `ValueError`, bukan `httpx.InvalidURL`). Dulu itu terjadi saat singleton lapor
    dihangatkan di lifespan, jadi konsol tidak menyala sama sekali."""
    service = _layanan(tmp_path, url="https://xn--a.com/api/webhooks/1/rahasia")
    terlihat = {}

    _jalankan_lifespan(service, lambda: terlihat.update(console_deps.get_lapor_discord().ringkasan()))

    assert terlihat == {"keadaan": "url_salah"}
    assert not service.settings.lapor_discord_db_path.exists()
