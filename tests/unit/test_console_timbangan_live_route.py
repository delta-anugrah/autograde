"""`GET /api/console/scale/live` (2026-10-06): signed-in only, an in-memory snapshot."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.domain.timbangan_live import Bacaan
from palmgrade.routes import console_deps
from palmgrade.routes.console_timbangan_live import router
from palmgrade.services.timbangan_live import TimbanganLive

SRC = Path(__file__).resolve().parents[2] / "src" / "palmgrade"


class _TanpaSesi:
    def current(self, token):
        return None


def _app(live: TimbanganLive, masuk: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    console_deps.pasang_penangan_validasi(app)
    app.dependency_overrides[console_deps.get_timbangan_live] = lambda: live
    if masuk:
        app.dependency_overrides[console_deps.require_operator] = lambda: {"email": "op@x", "role": "operator"}
    else:
        # The real guard, with a session store that knows nobody: never the console's
        # own AuthService, which opens the developer's state/console.db.
        app.dependency_overrides[console_deps.get_auth_service] = lambda: _TanpaSesi()
    return TestClient(app)


def test_tidak_dipasang():
    r = _app(TimbanganLive(dipakai=False)).get("/api/console/scale/live")
    assert r.status_code == 200
    assert r.json() == {"keadaan": "tidak_dipakai", "kg": None, "umur_detik": None}


def test_bacaan_stabil():
    live = TimbanganLive(dipakai=True, jam=lambda: 10.0)
    live.berhasil(Bacaan(kg=24310, stabil=True))
    assert _app(live).get("/api/console/scale/live").json() == {
        "keadaan": "stabil", "kg": 24310, "umur_detik": 0.0,
    }


def test_belum_masuk_ditolak():
    r = _app(TimbanganLive(dipakai=False), masuk=False).get("/api/console/scale/live")
    assert r.status_code == 401


def test_router_dan_worker_dipasang_di_console_main():
    teks = (SRC / "console_main.py").read_text()
    assert "app.include_router(timbangan_live_router)" in teks
    assert "build_timbangan_live(service.settings, get_timbangan_live())" in teks
