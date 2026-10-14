"""DEMO_MODE is read-only: demo-autograde.smagri.id faces the internet, and a visitor's click
must not store a truck, a weighing or a setting (the screen simulates them instead)."""
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from palmgrade.domain.operator_error import CODES, MODE_DEMO
from palmgrade.routes.console import router as console_router
from palmgrade.routes.console_deps import tolak_tulis_saat_demo


class _Permintaan:
    def __init__(self, method: str, path: str) -> None:
        self.method = method
        self.url = type("U", (), {"path": path})()


@pytest.mark.parametrize("path", ["/api/console/arrivals", "/api/console/weighings",
                                  "/api/console/dev/setelan", "/api/console/lines/line-1/assign-truck"])
def test_writes_are_refused_in_demo_mode(path):
    with pytest.raises(HTTPException) as e:
        tolak_tulis_saat_demo(_Permintaan("POST", path), True)
    assert e.value.status_code == 403
    assert e.value.detail["code"] == MODE_DEMO


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/console/login"), ("POST", "/api/console/logout"),
    ("POST", "/api/console/session/renew"), ("GET", "/api/console/weighings"),
])
def test_signing_in_and_reading_still_work(method, path):
    tolak_tulis_saat_demo(_Permintaan(method, path), True)


def test_nothing_is_refused_outside_demo_mode():
    tolak_tulis_saat_demo(_Permintaan("POST", "/api/console/arrivals"), False)


def test_the_code_is_known_to_the_screen():
    assert MODE_DEMO in CODES


def test_every_console_route_carries_the_guard(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    app = FastAPI()
    app.include_router(console_router)
    res = TestClient(app).post("/api/console/arrivals", json={"plate_number": "BE 8605 TSD"})
    assert (res.status_code, res.json()["detail"]["code"]) == (403, MODE_DEMO)


@pytest.mark.parametrize("modul", ["console_antrean_line", "console_roi_bawaan",
                                   "console_lapor_discord", "console_timbangan_live"])
def test_routers_mounted_beside_the_console_router_carry_the_guard_too(modul):
    """console_main mounts these next to `console.router`; a write added to one later must not
    slip past the read-only demo (final review 2026-10-13)."""
    import importlib

    router = importlib.import_module(f"palmgrade.routes.{modul}").router
    assert any(d.dependency is tolak_tulis_saat_demo for d in router.dependencies), modul


def test_a_resend_from_the_status_tab_is_refused_in_demo_mode(monkeypatch):
    from palmgrade.routes.console_antrean_line import router

    monkeypatch.setenv("DEMO_MODE", "1")
    app = FastAPI()
    app.include_router(router)
    res = TestClient(app).post("/api/console/dev/antrean/line/line-1/kirim-ulang")
    assert (res.status_code, res.json()["detail"]["code"]) == (403, MODE_DEMO)
