"""`/internal/setelan` on a line carries the label size (2026-10-05)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

RAHASIA = "rahasia-tes"
SETELAN = {"conf_threshold": 0.6, "minimum_size": 3000}


@pytest.fixture
def line(monkeypatch):
    # `routes/internal` pulls the pipeline, which pulls torch (see test_internal_restart.py).
    pytest.importorskip("torch")
    monkeypatch.setenv("WEBHOOK_SECRET", RAHASIA)
    monkeypatch.setenv("APP_MODE", "line")
    from palmgrade.core.dependencies import get_runtime_state, get_settings
    from palmgrade.routes.internal import router
    from palmgrade.workers.runtime_state import RuntimeState

    get_settings.cache_clear()  # type: ignore[attr-defined]
    state = RuntimeState()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime_state] = lambda: state
    return TestClient(app), state


def _kirim(client, **ekstra):
    return client.post("/internal/setelan", json={**SETELAN, **ekstra}, headers={"X-Internal-Secret": RAHASIA})


def test_ukuran_label_dari_konsol_dipakai_line_dan_dibaca_kembali(line):
    client, state = line

    assert _kirim(client, ukuran_label=175).status_code == 200

    assert state.ukuran_label_override == 175
    assert client.get("/internal/setelan", headers={"X-Internal-Secret": RAHASIA}).json()["ukuran_label"] == 175


def test_konsol_lama_tanpa_field_ini_tetap_diterima(line):
    client, state = line

    assert _kirim(client).status_code == 200

    assert state.ukuran_label_override == 100


def test_ukuran_di_luar_batas_ditolak_line_tidak_berubah(line):
    client, state = line

    assert _kirim(client, ukuran_label=900).status_code == 400
    assert state.ukuran_label_override is None


def test_jawaban_get_membawa_kotak_env_line_ini(line, monkeypatch):
    """Settings shows the PC's own box (2026-10-05): the line tells its `.env` box even while
    the console has set another one."""
    client, _state = line
    _kirim(client, roi_x1=1, roi_y1=2, roi_x2=300, roi_y2=400)

    jawab = client.get("/internal/setelan", headers={"X-Internal-Secret": RAHASIA}).json()

    from palmgrade.core.config import Settings

    s = Settings()
    assert jawab["roi_env"] == [s.roi_x1, s.roi_y1, s.roi_x2, s.roi_y2]
    assert (jawab["roi_x1"], jawab["roi_x2"]) == (1, 300), "the box in use is still the console's"
