"""End-to-end: diagnostics, ERP queue, and version lanes on a real console app.

Same shape as `test_dev_log_lane.py`: a real session cookie from a real login, a
role read from the same store the rest of the console uses, and `get_dev_service`
resolving through the actual dependency graph — not `create_console_app()`, which
would reach for a developer's own `state/*.db`.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import LineEndpoint
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.operator_error import BUKAN_SUPPORT
from palmgrade.domain.role import ROLE_OPERATOR, ROLE_SUPPORT
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.console import get_auth_service, get_console_service, get_dev_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.dev_service import DevService

SANDI = "sokongan2026"

LINE_1 = LineEndpoint("line-1", "Line 1", 8001, "m-1")
LINE_2 = LineEndpoint("line-2", "Line 2", 8002, "m-2")
LINE_3 = LineEndpoint("line-3", "Line 3", 8003, "m-3")


class _StubConsole:
    """The dev lane touches no console service; only the store is shared."""

    def __init__(self, store: ConsoleStore) -> None:
        self.store = store


class _LineClientDuaMati:
    """One line answers, two do not — the common shape on a real factory floor."""

    async def health_detail(self, line: LineEndpoint) -> dict:
        if line.line_code == "line-1":
            return {"status": "ok", "camera_connected": True, "gpu_available": True}
        raise LineUnavailable(
            "LINE_TIDAK_MENJAWAB", f"{line.line_code} tidak menjawab: timeout", line=line.name
        )


class _FakeSettings:
    app_version = "9.9.9-e2e"
    machine_id = "mesin-e2e"
    environment = "test"
    lic_enabled = True
    lic_token = "rahasia-tidak-boleh-bocor-ke-layar"


@pytest.fixture
def gerbang(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    log_store = LogStore(tmp_path / "log.db")
    erp_outbox = ErpOutboxStore(tmp_path / "erp_outbox.db")
    store.upsert_operator_manual(
        {
            "email": "operator@pks.test",
            "nama": "Operator Biasa",
            "password_hash": hash_password(SANDI),
            "role": ROLE_OPERATOR,
        }
    )
    store.upsert_operator_manual(
        {
            "email": "support@pks.test",
            "nama": "Akun Support",
            "password_hash": hash_password(SANDI),
            "role": ROLE_SUPPORT,
        }
    )

    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_dev_service] = lambda: DevService(
        log_store,
        line_client=_LineClientDuaMati(),
        lines=(LINE_1, LINE_2, LINE_3),
        erp_outbox=erp_outbox,
        settings=_FakeSettings(),
    )
    return TestClient(app), store, erp_outbox


def _masuk(client: TestClient, email: str) -> None:
    assert client.post(
        "/api/console/login", json={"email": email, "sandi": SANDI}
    ).status_code == 200


def test_support_membaca_ketiga_lane(gerbang):
    client, _, _ = gerbang
    _masuk(client, "support@pks.test")

    for jalur in ("diagnostik", "antrean", "versi"):
        jawab = client.get(f"/api/console/dev/{jalur}")
        assert jawab.status_code == 200, jalur


def test_operator_biasa_ditolak_403_di_ketiga_lane(gerbang):
    client, _, _ = gerbang
    _masuk(client, "operator@pks.test")

    for jalur in ("diagnostik", "antrean", "versi"):
        jawab = client.get(f"/api/console/dev/{jalur}")
        assert jawab.status_code == 403, jalur
        assert jawab.json()["detail"]["code"] == BUKAN_SUPPORT


def test_line_yang_tidak_menjawab_dilaporkan_bukan_menggagalkan_permintaan(gerbang):
    """Two of three lines are down: the screen still answers 200, and each line is
    reported exactly as it stands."""
    client, _, _ = gerbang
    _masuk(client, "support@pks.test")

    jawab = client.get("/api/console/dev/diagnostik")

    assert jawab.status_code == 200
    data = jawab.json()
    assert data["lines"]["line-1"]["terjangkau"] is True
    assert data["lines"]["line-2"]["terjangkau"] is False
    assert data["lines"]["line-3"]["terjangkau"] is False
    assert "tidak menjawab" in data["lines"]["line-2"]["sebab"]


def test_tombol_kirim_ulang_memindahkan_baris_gagal_jadi_pending(gerbang):
    client, _, erp_outbox = gerbang
    erp_outbox.enqueue("truck", "K1", {"plate_number": "BE 1 AA"})
    erp_outbox.mark_error(erp_outbox.due()[0], "AutoERP unreachable")
    _masuk(client, "support@pks.test")
    before = client.get("/api/console/dev/antrean").json()
    assert before["gagal"] == 1
    # next_attempt_at is what the "next attempt" column reads - must actually
    # be in the HTTP body, not just present on the store's internal row.
    assert before["items"][0]["next_attempt_at"] > 0

    hasil = client.post("/api/console/dev/antrean/kirim-ulang")

    assert hasil.status_code == 200
    assert hasil.json()["dikirim_ulang"] == 1
    assert client.get("/api/console/dev/antrean").json()["gagal"] == 0
    assert client.get("/api/console/dev/antrean").json()["pending"] == 1


def test_versi_tidak_membocorkan_rahasia_lewat_http(gerbang):
    client, _, _ = gerbang
    _masuk(client, "support@pks.test")

    mentah = client.get("/api/console/dev/versi").text

    assert "rahasia-tidak-boleh-bocor-ke-layar" not in mentah
