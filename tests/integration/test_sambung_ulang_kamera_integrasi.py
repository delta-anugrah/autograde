"""Integration: the Sambung ulang button reaches the camera through the capture thread.

Signed-in console route, real `LineClient`, the real line router over
`httpx.ASGITransport`, and the real `FrameCaptureWorker` with a fake camera: the press
answers before the camera is touched, and the next capture turn reconnects it once.
"""
from __future__ import annotations

import logging
from dataclasses import replace

import httpx
import pytest
from ai_palsu import KameraPalsu
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.routes.internal_kamera import buat_router
from palmgrade.services import sambung_ulang_kamera as layanan_kamera
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService
from palmgrade.workers import frame_capture_worker
from palmgrade.workers.frame_capture_worker import FrameCaptureWorker
from palmgrade.workers.runtime_state import RuntimeState

SECRET = "kunci-sambung-ulang-integrasi"
SANDI = "sawit2026"


class KameraHitung(KameraPalsu):
    def __init__(self) -> None:
        super().__init__()
        self.bisa_sambung_ulang = True
        self.sambung = 0

    def connect(self, index=0, serial=None, feature_file=None) -> None:
        self.sambung += 1
        super().connect(index, serial, feature_file)


@pytest.fixture
def pabrik(tmp_path, monkeypatch):
    monkeypatch.setattr(frame_capture_worker.time, "sleep", lambda _detik: None)
    settings = replace(
        Settings(), repo_root=tmp_path, console_line_host="http://line",
        internal_secret=SECRET, factory_tz="Asia/Jakarta",
    )
    state = RuntimeState()
    kamera = KameraHitung()
    worker = FrameCaptureWorker(camera=kamera, state=state, target_fps=0)
    line = FastAPI()
    line.include_router(buat_router(settings=lambda: settings, state=lambda: state, kamera=lambda: kamera))

    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual(
        {"email": "budi@pks.test", "full_name": "Pak Budi", "password_hash": hash_password(SANDI)}
    )
    service = ConsoleService(settings, store, LineClient(settings, transport=httpx.ASGITransport(app=line)))
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    client = TestClient(app)
    assert client.post("/api/console/login", json={"email": "budi@pks.test", "sandi": SANDI}).status_code == 200
    return client, worker, kamera, state


def test_the_press_answers_first_and_the_capture_thread_reconnects_once(pabrik):
    client, worker, kamera, state = pabrik

    jawab = client.post("/api/console/lines/line-1/reconnect-camera")

    assert jawab.status_code == 202
    assert kamera.sambung == 0, "the route must not touch the camera"
    worker.run_once()
    assert kamera.sambung == 1
    assert state.kamera_sambung_ok is True
    worker.run_once()
    assert kamera.sambung == 1
    assert state.frame_terakhir_at > 0


def test_the_console_log_names_the_account(pabrik, caplog):
    client, _, _, _ = pabrik
    with caplog.at_level(logging.WARNING, logger=layanan_kamera.__name__):
        client.post("/api/console/lines/line-1/reconnect-camera")
    baris = [r for r in caplog.records if "Pak Budi" in r.getMessage()]
    assert len(baris) == 1 and baris[0].levelno == logging.WARNING
    assert "line-1" in baris[0].getMessage()
