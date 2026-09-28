"""End-to-end lane mesin: secret dibaca dari environment seperti di pabrik."""
from __future__ import annotations

from dataclasses import replace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.routes.internal_bahaya import buat_router
from palmgrade.workers.runtime_state import RuntimeState

WEBHOOK = "kunci-timbangan-palsu"


def _line(tmp_path, monkeypatch, **env) -> TestClient:
    monkeypatch.delenv("INTERNAL_SECRET", raising=False)
    monkeypatch.setenv("REKAMAN_DIR", str(tmp_path / "videos"))
    for nama, nilai in env.items():
        monkeypatch.setenv(nama, nilai)
    settings = replace(Settings(), repo_root=tmp_path)
    state = RuntimeState()
    app = FastAPI()
    app.include_router(buat_router(settings=lambda: settings, state=lambda: state, keluar=lambda _j: None))
    return TestClient(app)


def test_line_menolak_perintah_tanpa_secret(tmp_path, monkeypatch):
    c = _line(tmp_path, monkeypatch, WEBHOOK_SECRET=WEBHOOK)
    assert c.get("/internal/rekam/berkas").status_code == 401


def test_secret_kosong_di_env_tidak_membuka_line(tmp_path, monkeypatch):
    c = _line(tmp_path, monkeypatch, WEBHOOK_SECRET="")
    assert c.get("/internal/rekam/berkas", headers={"x-internal-secret": ""}).status_code == 401
