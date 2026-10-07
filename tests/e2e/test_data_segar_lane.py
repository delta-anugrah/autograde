"""End to end (batch 5.3, 5.4): what the operator's polls bring back, drawn by the screen.

Real routes behind a real sign-in over ASGI, a real SQLite store, and the screen's own
functions run in node on the real answers:

- a truck registered after the line cards were drawn reaches the Tugaskan list of a card
  that is already on screen, and what the operator had picked stays picked;
- two polls with nothing new in between give the Grading table the very same markup, so
  `tulisKalauBeda` leaves the table (and a finger on it) alone.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI
from konsol_js import NODE, jalankan

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.vision_event import build_event_payload
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService

pytestmark = pytest.mark.skipif(NODE is None, reason="node tidak ada")

SANDI = "sandi-e2e-segar"

_ROOT = """
let trucks = [];
function buatRoot(nilai) {
  const panel = { innerHTML: "" };
  const teks = { textContent: "" };
  return { dataset: { nilai, buka: "" }, panel, teks,
    querySelector(s) { return s === ".pilih-panel" ? panel : teks; } };
}
"""
_LAYAR = """
let gradingOffset = 0;
const dash = (v) => (v === null || v === undefined || v === "" ? KOSONG : esc(v));
const tagHasil = (s, kelas) => `<span class="tag">${esc(kelas || s)}</span>`;
const sel = { innerHTML: "", ditulis: 0 };
Object.defineProperty(sel, "innerHTML", { set() { sel.ditulis++; }, get() { return ""; } });
"""


@pytest.fixture
def rakitan(tmp_path):
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
    return app, service


async def _dengan_klien(app, kerja):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://konsol") as klien:
        masuk = await klien.post("/api/console/login", json={"email": "operator@pks.test", "sandi": SANDI})
        assert masuk.status_code == 200, masuk.text
        return await kerja(klien)


def test_a_truck_registered_later_reaches_a_card_that_is_already_on_screen(rakitan):
    app, _ = rakitan

    async def kerja(klien):
        pertama = await klien.post("/api/console/trucks", json={"plate_number": "BE 1111 AA"})
        assert pertama.status_code == 201, pertama.text
        awal = (await klien.get("/api/console/trucks")).json()["items"]
        kedua = await klien.post("/api/console/trucks", json={"plate_number": "BE 2222 BB"})
        assert kedua.status_code == 201, kedua.text
        return pertama.json()["id"], awal, (await klien.get("/api/console/trucks")).json()["items"]

    dipilih, awal, kini = asyncio.run(_dengan_klien(app, kerja))

    hasil = jalankan(
        ["tulisKalauBeda", "barisPilih", "isiUlangPilih", "opsiTrukKartu"],
        f"(() => {{ const r = buatRoot({json.dumps(dipilih)});"
        f" trucks = {json.dumps(awal)}; isiUlangPilih(r, opsiTrukKartu()); const lama = r.panel.innerHTML;"
        f" trucks = {json.dumps(kini)}; isiUlangPilih(r, opsiTrukKartu());"
        " return [lama, r.panel.innerHTML, r.dataset.nilai, r.teks.textContent]; })()",
        tambahan=_ROOT,
    )

    lama, baru, nilai, teks = hasil
    assert "BE 2222 BB" not in lama and "BE 2222 BB" in baru
    assert nilai == dipilih and teks == "BE 1111 AA", "what was picked stays picked"


def _janjang(service: ConsoleService, nomor: int) -> dict:
    return build_event_payload(
        machine_id=service.lines[0].machine_id, file_ts=f"2026-10-04_07-41-0{nomor}_000000",
        timestamp=datetime.now(UTC).isoformat(), ripeness_status="ACC", ripeness_confidence=0.9,
        capture_type="auto", image_path=f"captures/results/2026-10-04/{nomor}.webp",
        truck_id=None, assignment_id=None,
    )


def test_two_polls_with_nothing_new_write_the_grading_table_once(rakitan):
    app, service = rakitan
    service.ingest(_janjang(service, 1))
    service.ingest(_janjang(service, 2))

    async def kerja(klien):
        alamat = "/api/console/history?limit=25&offset=0"
        pertama = (await klien.get(alamat)).json()
        kedua = (await klien.get(alamat)).json()
        service.ingest(_janjang(service, 3))
        return pertama, kedua, (await klien.get(alamat)).json()

    pertama, kedua, ketiga = asyncio.run(_dengan_klien(app, kerja))
    assert pertama["total"] == 2 and ketiga["total"] == 3

    ditulis = jalankan(
        ["chipPlat", "waktu", "selFoto", "barisRecent", "tulisKalauBeda"],
        "(() => { const hasil = [];"
        f" for (const r of {json.dumps([pertama, kedua, ketiga])}) {{"
        "   tulisKalauBeda(sel, r.items.map(barisRecent).join(\"\")); hasil.push(sel.ditulis); }"
        " return hasil; })()",
        tambahan=_LAYAR,
    )

    assert ditulis == [1, 1, 2], "written for the first answer and for the new bunch, not in between"
