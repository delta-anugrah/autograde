"""End to end (batch 5.10, 5.12): the request the Grading filter builds is answered by the
real route, and the rows it returns are drawn with the small photo.

A real sign-in over ASGI on a real SQLite store; `paramGrading`, `barisRecent` and `selFoto`
run in node on the real answer.
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

SANDI = "sandi-e2e-saring"
_LAYAR = """
let gradingOffset = 0;
const dash = (v) => (v === null || v === undefined || v === "" ? KOSONG : esc(v));
const tagHasil = (s, kelas) => `<span class="tag">${esc(kelas || s)}</span>`;
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


def test_the_line_filter_brings_back_only_that_line_drawn_with_small_photos(rakitan):
    app, service = rakitan
    for nomor, line in ((1, 0), (2, 1), (3, 1)):
        service.ingest(build_event_payload(
            machine_id=service.lines[line].machine_id, file_ts=f"2026-10-05_07-41-0{nomor}_000000",
            timestamp=datetime.now(UTC).isoformat(), ripeness_status="ACC", ripeness_confidence=0.9,
            capture_type="auto", image_path=f"captures/results/2026-10-05/x/bbox/Ripe/{nomor}.webp",
            truck_id=None, assignment_id=None,
        ))
    alamat = jalankan(["paramGrading"], 'paramGrading(25, 0, { line: "line-2", truk: "" })')

    async def tanya():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://konsol") as klien:
            masuk = await klien.post("/api/console/login", json={"email": "operator@pks.test", "sandi": SANDI})
            assert masuk.status_code == 200, masuk.text
            return (await klien.get(f"/api/console/history?{alamat}")).json()

    jawab = asyncio.run(tanya())
    html = jalankan(["chipPlat", "waktu", "selFoto", "barisRecent"],
                    f"{json.dumps(jawab['items'])}.map(barisRecent).join('')", tambahan=_LAYAR)

    assert jawab["total"] == 2
    assert html.count("<tr>") == 2 and "line-1" not in html
    assert html.count("/thumb/Ripe/") == 2, "the table loads the small copies"
    assert html.count('data-foto="/captures/line-2/results/2026-10-05/x/bbox/Ripe/') == 2
