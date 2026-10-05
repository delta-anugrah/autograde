"""End to end (batch 5.6): the truck the operator is about to assign leads the list.

A real sign-in over ASGI, a real weigh-in through the operator's lane, and the screen's own
functions run in node on the real `/api/console/trucks` answer: the weighed-in truck sits
in the "on site" section above the rest, and typing part of its plate leaves only its row.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI
from konsol_js import NODE, jalankan

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService

pytestmark = pytest.mark.skipif(NODE is None, reason="node tidak ada")

SANDI = "sandi-e2e-pilih"
PLAT = ("BE 1111 AA", "BE 2222 BB", "BE 3333 CC")


@pytest.fixture
def app(tmp_path):
    settings = replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta")
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual(
        {"email": "operator@pks.test", "full_name": "Operator", "password_hash": hash_password(SANDI)}
    )
    service = ConsoleService(settings, store, line_client=None)
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    return app


async def _truk_sesudah_timbang_isi(app) -> list[dict]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://konsol") as klien:
        masuk = await klien.post("/api/console/login", json={"email": "operator@pks.test", "sandi": SANDI})
        assert masuk.status_code == 200, masuk.text
        for plat in PLAT:
            assert (await klien.post("/api/console/trucks", json={"plate_number": plat})).status_code == 201
        isi = await klien.post("/api/console/weighings", json={
            "plate_number": PLAT[2], "gross_kg": "14820,5",
            "entered_at": datetime.now(ZoneInfo("Asia/Jakarta")).isoformat(),
        })
        assert isi.status_code == 201, isi.text
        return (await klien.get("/api/console/trucks")).json()["items"]


def test_the_weighed_in_truck_leads_the_card_list_and_typing_finds_it(app):
    truk = asyncio.run(_truk_sesudah_timbang_isi(app))

    opsi, tampil = jalankan(
        ["ratakanCari", "cocokCari", "hasilSaring", "opsiTrukKartu"],
        "(() => { const opsi = opsiTrukKartu();"
        " const baris = []; let grup;"
        " opsi.forEach((o) => { if (o.grup && o.grup !== grup) baris.push({ grup: true, teks: o.grup });"
        "   grup = o.grup; baris.push({ grup: false, teks: o.teks }); });"
        " return [opsi, baris.filter((b, i) => hasilSaring(baris, 'be3333')[i]).map((b) => b.teks)]; })()",
        tambahan=f"const trucks = {json.dumps(truk)};",
    )

    di_lokasi = jalankan([], "KAMUS[bahasa].grupDiLokasi")
    assert [o["teks"] for o in opsi][:2] == ["Pilih Truk", PLAT[2]]
    assert opsi[1]["grup"] == di_lokasi
    assert {o["teks"] for o in opsi[2:]} == set(PLAT[:2])
    assert tampil == [di_lokasi, PLAT[2]], "the section header stays with the one row that matches"
