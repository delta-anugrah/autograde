"""Perakit uji antrean line ke konsol (batch 2.4), dipakai unit, integrasi, dan e2e.

Modul biasa seperti `bahaya_palsu.py`, bukan fixture: test di tiga folder memakai
rakitan yang SAMA (conftest menaruh folder `tests/` di sys.path).
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.routes.console_deps import get_console_service
from palmgrade.routes.console_ingest import ingest_router
from palmgrade.services.console_service import ConsoleService

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
