"""`/internal/assignment` menolak TRUK BARU selama perintah hapus menunggu boot.

Line keluar 1 detik sesudah menerima `/internal/hapus-data`. Truk yang
dipasang di detik itu akan digrading ke penugasan yang baris konsolnya segera
dihapus — sesudahnya `lepas` tidak menemukan apa pun dan janjangnya tidak
pernah tertaut ke tiket (review 2026-09-25, I-3b). Melepas truk tetap boleh.

Router internal menarik torch — dilewati di CI; penjaga teksnya ada di
`tests/unit/test_main_bahaya_wiring.py`.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

pytest.importorskip("numpy")
pytest.importorskip("cv2")
pytest.importorskip("torch")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from palmgrade.core.config import Settings  # noqa: E402
from palmgrade.core.dependencies import get_runtime_state, get_settings  # noqa: E402
from palmgrade.routes import internal as internal_routes  # noqa: E402
from palmgrade.services.hapus_data_line import tulis_penanda  # noqa: E402
from palmgrade.workers.runtime_state import RuntimeState  # noqa: E402

BODY = {
    "machine_id": "m-1", "assignment_id": "11111111-1111-1111-1111-111111111111",
    "truck_id": "22222222-2222-2222-2222-222222222222", "assigned_at": "2026-09-25T01:00:00Z",
}


@pytest.fixture
def line(tmp_path, monkeypatch):
    monkeypatch.delenv("ARTIFACTS_DIR", raising=False)
    settings = replace(Settings(), repo_root=tmp_path)
    state = RuntimeState()
    app = FastAPI()
    app.include_router(internal_routes.router)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_runtime_state] = lambda: state
    app.dependency_overrides[internal_routes._verify_internal_secret] = lambda: None
    return TestClient(app), settings, state


def test_tanpa_penanda_truk_dipasang_seperti_biasa(line):
    client, _settings, state = line
    assert client.post("/internal/assignment", json=BODY).status_code == 200
    assert state.current_truck_id == BODY["truck_id"]


def test_truk_baru_ditolak_selama_hapus_menunggu(line):
    client, settings, state = line
    tulis_penanda(settings.artifacts_dir, mode="transaksi", diminta_oleh="s", now=1.0)

    res = client.post("/internal/assignment", json=BODY)

    assert res.status_code == 409
    assert res.json()["detail"]["kode"] == "hapus_berjalan"
    assert state.current_truck_id is None


def test_melepas_truk_tetap_boleh(line):
    client, settings, _state = line
    tulis_penanda(settings.artifacts_dir, mode="transaksi", diminta_oleh="s", now=1.0)

    res = client.post("/internal/assignment", json={**BODY, "assignment_id": "", "truck_id": ""})

    assert res.status_code == 200
