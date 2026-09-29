"""Perakit uji antrean line ke konsol (batch 2.4), dipakai unit, integrasi, dan e2e.

Modul biasa seperti `bahaya_palsu.py`, bukan fixture: test di tiga folder memakai
rakitan yang SAMA (conftest menaruh folder `tests/` di sys.path).
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.integrations.outbox.outbox_store import OutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import router as console_router
from palmgrade.routes.console_antrean_line import router as antrean_line_router
from palmgrade.routes.console_deps import get_auth_service, get_console_service, get_pantau_antrean_line
from palmgrade.routes.console_ingest import ingest_router
from palmgrade.routes.internal_outbox import buat_router
from palmgrade.services.antrean_line import AntreanLine
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.pantau_antrean_line import PantauAntreanLine
from palmgrade.workers.outbox_retry_worker import NAMA_WORKER, OutboxRetryWorker
from palmgrade.workers.runtime_state import RuntimeState

# ── berkas outbox tulisan versi sebelum batch 2.4 ───────────────────────

#: Skema persis versi sebelum batch 2.4: tanpa `dibuat_at`, dan `failed` masih ditulis.
SKEMA_OUTBOX_VERSI_LAMA = """
CREATE TABLE outbox_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    TEXT NOT NULL UNIQUE,
    machine_id  TEXT NOT NULL,
    payload     TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at REAL NOT NULL DEFAULT 0,
    last_error  TEXT,
    status      TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX idx_outbox_status_retry ON outbox_events (status, next_retry_at);
"""


def berkas_outbox_versi_lama(jalur: Path, baris: list[tuple[str, str, int, str]]) -> None:
    """Tulis `outbox.db` seperti versi sebelum batch 2.4 meninggalkannya.

    `baris`: (event_id, status, retry_count, payload). Jadwalnya semenit lalu dan
    `last_error`-nya dari antrean ke palmgrade-api yang sudah mati, keadaan PC
    Lampung sesudah api dimatikan 2026-09-20.
    """
    jalur.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(jalur))
    db.executescript(SKEMA_OUTBOX_VERSI_LAMA)
    with db:
        db.executemany(
            "INSERT INTO outbox_events "
            "(event_id, machine_id, payload, retry_count, next_retry_at, last_error, status) "
            "VALUES (?, 'm-1', ?, ?, ?, 'HTTP 503: api mati', ?)",
            [(eid, payload, retry, time.time() - 60, status) for eid, status, retry, payload in baris],
        )
    db.close()


# ── kabel line ke konsol (sisi worker) ──────────────────────────────────


class KabelKonsol:
    """Handler `httpx.MockTransport` untuk `OutboxRetryWorker`: diteruskan ke app konsol, atau putus.

    `putus = True` meniru konsol mati (ConnectError, port yang tidak didengar
    siapa pun). `permintaan` menghitung setiap percobaan, sampai atau tidak.
    """

    def __init__(self, app: FastAPI) -> None:
        self._klien = TestClient(app, raise_server_exceptions=False)
        self.putus = False
        self.permintaan = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.permintaan += 1
        if self.putus:
            raise httpx.ConnectError("konsol mati", request=request)
        jawab = self._klien.post(
            request.url.path,
            content=request.content,
            headers={k: v for k, v in request.headers.items() if k in ("content-type", "x-webhook-secret")},
        )
        return httpx.Response(
            jawab.status_code,
            content=jawab.content,
            headers={"content-type": jawab.headers.get("content-type", "text/plain")},
        )

    def klien(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def app_ingest(konsol: ConsoleService) -> FastAPI:
    """Lane mesin konsol yang ASLI (`/api/v1/internal/vision/events`) di atas `konsol`."""
    app = FastAPI()
    app.include_router(ingest_router, prefix=konsol.settings.backend_api_ver)
    app.dependency_overrides[get_console_service] = lambda: konsol
    return app


def klien_konsol_mati() -> httpx.Client:
    """Klien worker yang tidak pernah sampai: konsol mati sejak awal."""

    def mati(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("konsol mati", request=request)

    return httpx.Client(transport=httpx.MockTransport(mati))


# ── line (router /internal/outbox*) dan konsol (layar support) ──────────


class LinePerPort(httpx.AsyncBaseTransport):
    """Transport `LineClient` konsol: satu app line per port, in-process.

    Port tanpa app = line mati (ConnectError), persis seperti line yang
    containernya berhenti.
    """

    def __init__(self, apps: dict[int, FastAPI]) -> None:
        self._tujuan = {port: httpx.ASGITransport(app=app) for port, app in apps.items()}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        tujuan = self._tujuan.get(request.url.port)
        if tujuan is None:
            raise httpx.ConnectError(f"tidak ada line di port {request.url.port}", request=request)
        return await tujuan.handle_async_request(request)


@dataclass
class LineUji:
    app: FastAPI
    settings: Settings
    store: OutboxStore
    state: RuntimeState
    worker: OutboxRetryWorker


def rakit_line(
    folder: Path,
    *,
    internal_secret: str,
    klien_konsol: httpx.Client,
    jam: Callable[[], float] = time.time,
    **setelan: Any,
) -> LineUji:
    """Satu line seperti `main.py` merakitnya: store, worker terdaftar, router `/internal/outbox*`."""
    settings = replace(Settings(), repo_root=folder, internal_secret=internal_secret, **setelan)
    store = OutboxStore(settings.state_dir / "outbox.db")
    state = RuntimeState()
    worker = OutboxRetryWorker(store, settings, state, client=klien_konsol, jam=jam)
    state.worker_threads.append((NAMA_WORKER, None, worker))
    app = FastAPI()
    app.include_router(
        buat_router(
            settings=lambda: settings,
            antrean=lambda: AntreanLine(store, settings, state, settings.state_dir),
        )
    )
    return LineUji(app, settings, store, state, worker)


class _KonsolTanpaLayanan:
    """Lane layar support tidak menyentuh `ConsoleService`; login cuma butuh store-nya."""

    def __init__(self, store: ConsoleStore) -> None:
        self.store = store


def app_konsol(store: ConsoleStore, pantau: PantauAntreanLine) -> FastAPI:
    """Rute konsol yang ASLI (login + tab Status → Antrean line) di atas `store` dan `pantau`."""
    app = FastAPI()
    app.include_router(console_router)
    app.include_router(antrean_line_router)
    app.dependency_overrides[get_console_service] = lambda: _KonsolTanpaLayanan(store)
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_pantau_antrean_line] = lambda: pantau
    return app


def masuk(app: FastAPI, store: ConsoleStore, *, role: str, sandi: str = "sandi-uji-antrean") -> TestClient:
    """Akun lokal ber-`role` itu dibuat lalu masuk; klien membawa cookie sesinya."""
    email = f"{role}@pks.test"
    store.upsert_operator_manual(
        {"email": email, "full_name": role.title(), "password_hash": hash_password(sandi), "role": role}
    )
    client = TestClient(app)
    assert client.post("/api/console/login", json={"email": email, "sandi": sandi}).status_code == 200
    return client
