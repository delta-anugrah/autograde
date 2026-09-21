# tests/unit/test_internal_restart.py
"""POST /internal/restart — line mematikan diri, Docker menyalakannya lagi."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# `routes/internal` menarik pipeline, dan pipeline menarik torch. CI vision
# sengaja tidak memasangnya (lihat test_edge_realtime_outbox.py), jadi tanpa
# penjaga ini berkasnya error di collection — bukan gagal karena apa yang
# diperiksanya, melainkan karena tidak bisa dimuat sama sekali.
@pytest.fixture
def client(monkeypatch):
    pytest.importorskip("torch")
    monkeypatch.setenv("WEBHOOK_SECRET", "rahasia-tes")
    monkeypatch.setenv("APP_MODE", "line")
    from palmgrade.core.config import Settings
    from palmgrade.core.dependencies import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]
    from fastapi import FastAPI

    from palmgrade.routes.internal import router

    app = FastAPI()
    app.include_router(router)
    assert Settings().internal_secret == "rahasia-tes"
    return TestClient(app)


def test_tanpa_secret_ditolak(client):
    r = client.post("/internal/restart")
    assert r.status_code == 401


def test_dengan_secret_menjawab_200_lebih_dulu(client):
    # Line menjawab DULU, baru keluar. Keluar sebelum menjawab membuat konsol
    # melihat koneksi putus dan melaporkannya sebagai gagal, padahal berhasil.
    with patch("palmgrade.routes.internal._jadwalkan_keluar") as jadwal:
        r = client.post("/internal/restart", headers={"X-Internal-Secret": "rahasia-tes"})
    assert r.status_code == 200
    assert r.json()["status"] == "restarting"
    jadwal.assert_called_once()


def test_jeda_disebut_di_jawaban(client):
    with patch("palmgrade.routes.internal._jadwalkan_keluar"):
        r = client.post("/internal/restart", headers={"X-Internal-Secret": "rahasia-tes"})
    assert r.json()["jeda_detik"] > 0
