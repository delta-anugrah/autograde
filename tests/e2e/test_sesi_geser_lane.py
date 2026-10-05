"""End to end (batch 5.7): a 20-hour mill day on one sign-in, and a screen left alone after.

A real sign-in over ASGI on a real SQLite store, with a clock the test moves. Every few
minutes the operator touches the screen; whether that touch sends a renew is decided by the
screen's own `perluPerpanjang` (run in node, real constants), and the renew goes through the
real route. The 2 s poll (`/api/console/state`) runs throughout and never slides anything.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI
from konsol_js import NODE, jalankan, konstanta

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service, get_dev_service, get_pembaruan_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService

pytestmark = pytest.mark.skipif(NODE is None, reason="node tidak ada")

SANDI = "sandi-e2e-sesi"
MENIT = 60
SENTUH_TIAP_S = 7 * MENIT
SHIFT_S = 20 * 60 * MENIT
DIAM_MAKS_S = 48 * 60 * MENIT


class _Dev:
    async def license_state(self) -> dict:
        return {}

    def app_version(self) -> str:
        return "v-e2e"


class _Keadaan:
    def as_dict(self) -> dict:
        return {}


class _Pembaruan:
    def keadaan(self) -> _Keadaan:
        return _Keadaan()


@pytest.fixture
def rakitan(tmp_path):
    settings = replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta")
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual(
        {"email": "operator@pks.test", "full_name": "Operator", "password_hash": hash_password(SANDI)}
    )
    jam = [2_000_000.0]
    app = FastAPI()
    app.include_router(console_router)
    service = ConsoleService(settings, store, line_client=None)
    auth = AuthService(store, now=lambda: jam[0])
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_dev_service] = lambda: _Dev()
    app.dependency_overrides[get_pembaruan_service] = lambda: _Pembaruan()
    return app, jam


def _keputusan_layar(sentuhan: list[tuple[int, int]]) -> list[bool]:
    """For each (ms since the last renew, ms left), whether the screen renews."""
    daftar = ", ".join(f"[{lalu}, {sisa}]" for lalu, sisa in sentuhan)
    return jalankan(
        ["dalamPeringatan", "perluPerpanjang"],
        f"[{daftar}].map(([lalu, sisa]) => perluPerpanjang({{ aktif: true, terakhir: 0, sekarang: lalu, sisaMs: sisa }}))",
        tambahan=konstanta("JEDA_PERPANJANG_MS", "PERINGATAN_SESI_MS"),
    )


async def _hari_giling(app, jam) -> tuple[int, int, int]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://konsol") as klien:
        masuk = await klien.post("/api/console/login", json={"email": "operator@pks.test", "sandi": SANDI})
        assert masuk.status_code == 200, masuk.text
        sisa = masuk.json()["sisa_detik"]
        mulai, terakhir_perpanjang, diperpanjang = jam[0], jam[0], 0
        while jam[0] - mulai < SHIFT_S:
            jam[0] += SENTUH_TIAP_S
            sisa -= SENTUH_TIAP_S
            assert (await klien.get("/api/console/state")).status_code == 200, "signed out mid-shift"
            lalu_ms = int((jam[0] - terakhir_perpanjang) * 1000)
            if _keputusan_layar([(lalu_ms, sisa * 1000)])[0]:
                jawab = await klien.post("/api/console/session/renew")
                assert jawab.status_code == 200, jawab.text
                sisa, terakhir_perpanjang, diperpanjang = jawab.json()["sisa_detik"], jam[0], diperpanjang + 1
        # The shift is over; the screen is left on, polling, untouched.
        # Bounded: a session that polls kept alive must fail this test, not hang it.
        diam = 0
        while diam <= DIAM_MAKS_S and (await klien.get("/api/console/state")).status_code == 200:
            jam[0] += 30 * MENIT
            diam += 30 * MENIT
        return diperpanjang, diam, (await klien.post("/api/console/session/renew")).status_code


def test_a_twenty_hour_day_on_one_sign_in_and_an_idle_screen_signs_itself_out(rakitan):
    app, jam = rakitan

    diperpanjang, diam, terlambat = asyncio.run(_hari_giling(app, jam))

    assert diperpanjang >= 20 * 60 // 7 // 2, "a touch every 7 minutes renews about every other touch"
    assert 11 * 60 * MENIT <= diam <= 12 * 60 * MENIT, f"signed out after {diam / 3600:.1f} h idle"
    assert terlambat == 401, "a touch after the end does not bring the session back"
