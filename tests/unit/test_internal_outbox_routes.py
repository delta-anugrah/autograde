"""Router `/internal/outbox*` sisi LINE (batch 2.4): tanpa torch, jadi jalan di CI.

Dirakit lewat fungsi pabrik seperti `routes/internal_bahaya.py`. `main.py` memberi
store, Settings, dan RuntimeState yang asli; test memberi yang di folder sementara.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.integrations.outbox.outbox_store import OutboxStore
from palmgrade.routes.internal_outbox import buat_router
from palmgrade.services.antrean_line import AntreanLine
from palmgrade.workers.runtime_state import RuntimeState

SECRET = "rahasia-internal-uji"
HEADER = {"x-internal-secret": SECRET}
TS = "2026-09-20T03:00:00+00:00"


@pytest.fixture
def line(tmp_path):
    settings = replace(Settings(), repo_root=tmp_path, internal_secret=SECRET)
    store = OutboxStore(settings.state_dir / "outbox.db")
    state = RuntimeState()
    app = FastAPI()
    app.include_router(
        buat_router(
            settings=lambda: settings,
            antrean=lambda: AntreanLine(store, settings, state, settings.state_dir),
        )
    )
    return TestClient(app), store


def _mundur(store: OutboxStore) -> None:
    store.add_event("e1", "m-1", {"event_id": "e1", "timestamp": TS})
    for row in store.get_pending():
        store.mark_failed_attempt(row["id"], "putus")


@pytest.mark.parametrize("metode,jalur", [("get", "/internal/outbox"), ("post", "/internal/outbox/requeue")])
@pytest.mark.parametrize("header", [{}, {"x-internal-secret": ""}, {"x-internal-secret": "bukan-" + SECRET}])
def test_tanpa_kunci_yang_benar_401_dan_tidak_menyentuh_antrean(line, metode, jalur, header):
    client, store = line
    _mundur(store)

    assert getattr(client, metode)(jalur, headers=header).status_code == 401
    assert store.get_pending() == []


def test_ringkasan_antrean(line):
    client, store = line
    _mundur(store)

    isi = client.get("/internal/outbox", headers=HEADER).json()

    assert (isi["menunggu"], isi["tertua_at"], isi["tersambung"]) == (1, 1789873200.0, None)


def test_kirim_ulang_bentuk_jawaban_lama_tetap(line):
    """URL dan `{"requeued": n}` sama dengan rute yang dipindah dari routes/internal.py."""
    client, store = line
    _mundur(store)

    jawab = client.post("/internal/outbox/requeue", headers=HEADER)

    assert (jawab.status_code, jawab.json()) == (200, {"requeued": 1})
    assert [r["event_id"] for r in store.get_pending()] == ["e1"]


def test_modul_tidak_menarik_torch_cv2_atau_ultralytics():
    """Kalau modul ini suatu hari mengimpor sesuatu yang menarik torch, semua test di
    atas dilewati di CI tanpa ada yang sadar, persis nasib test `routes/internal.py`."""
    src = Path(__file__).resolve().parents[2] / "src"
    skrip = (
        "import sys\n"
        "for m in ('torch', 'cv2', 'ultralytics'):\n"
        "    sys.modules[m] = None\n"
        "import palmgrade.routes.internal_outbox\n"
        "import palmgrade.services.antrean_line\n"
        "import palmgrade.workers.outbox_retry_worker\n"
    )
    hasil = subprocess.run(
        [sys.executable, "-c", skrip], capture_output=True, text=True,
        env={"PYTHONPATH": str(src), "PATH": "/usr/bin:/bin"}, timeout=60,
    )
    assert hasil.returncode == 0, hasil.stderr[-800:]
