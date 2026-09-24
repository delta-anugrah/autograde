"""End-to-end: the PLC commissioning test screen on a real console app.

Same shape as `test_dev_diagnostik_lane.py`: a real session cookie from a real
login, a role read from the same store the rest of the console uses, and
`get_dev_service` resolving through the actual dependency graph — not
`create_console_app()`, which would reach for a developer's own `state/*.db`.

This is the only lane in the whole console that moves physical hardware, so
every scenario here maps to one of its three mandatory guards: typed
confirmation, refused while the target line is processing a truck, and every
attempt leaving a WARNING row in `event_log`.
"""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import LineEndpoint
from palmgrade.core.log_sink import SqliteLogHandler
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.operator_error import BUKAN_SUPPORT
from palmgrade.domain.role import ROLE_OPERATOR, ROLE_SUPPORT
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.integrations.notifications.line_client import LinePlcTolak, LineUnavailable
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.console import get_auth_service, get_console_service, get_dev_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.dev_service import DevService

SANDI = "sokongan2026"

LINE_1 = LineEndpoint("line-1", "Line 1", 8001, "m-1")


class _StubConsole:
    """The dev lane touches no console service; only the store is shared."""

    def __init__(self, store: ConsoleStore) -> None:
        self.store = store


class _LineClientPlc:
    """One line, standing in for the real camera process the PLC lives on.

    `writes` records every coil the line was actually asked to fire — the
    fact every safety test below turns on.
    """

    def __init__(self, *, busy: bool = False, unreachable: bool = False, inputs=None):
        self.busy = busy
        self.unreachable = unreachable
        self.inputs = inputs or [False, False, True]
        self.writes: list[int] = []

    async def plc_state(self, line: LineEndpoint) -> dict:
        return {"enabled": True, "inputs": self.inputs, "testable_coils": [0, 1, 11]}

    async def plc_coil(self, line: LineEndpoint, *, coil: int, requested_by: str) -> dict:
        if self.unreachable:
            raise LineUnavailable(
                "LINE_TIDAK_MENJAWAB", f"{line.line_code} tidak menjawab: timeout", line=line.name
            )
        if self.busy:
            raise LinePlcTolak(409, "line_sedang_memproses_truk")
        self.writes.append(coil)
        return {"fired": True, "coil": coil}


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
    line_client = _LineClientPlc()

    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_dev_service] = lambda: DevService(
        log_store,
        line_client=line_client,
        lines=(LINE_1,),
        erp_outbox=erp_outbox,
        settings=_FakeSettings(),
    )
    return TestClient(app), store, log_store, line_client


def _masuk(client: TestClient, email: str) -> None:
    assert client.post(
        "/api/console/login", json={"email": email, "sandi": SANDI}
    ).status_code == 200


def test_support_membaca_di_line(gerbang):
    client, _, _, line_client = gerbang
    _masuk(client, "support@pks.test")

    jawab = client.get("/api/console/dev/plc/line-1")

    assert jawab.status_code == 200
    assert jawab.json()["inputs"] == [False, False, True]
    assert line_client.writes == []


def test_operator_biasa_ditolak_403(gerbang):
    """The developer tab is support-only; a plain operator account never
    reaches a screen that can move hardware."""
    client, _, _, _ = gerbang
    _masuk(client, "operator@pks.test")

    baca = client.get("/api/console/dev/plc/line-1")
    picu = client.post(
        "/api/console/dev/plc/line-1/coil", json={"coil": 11}
    )

    assert baca.status_code == 403
    assert baca.json()["detail"]["code"] == BUKAN_SUPPORT
    assert picu.status_code == 403


def test_picu_tanpa_konfirmasi_ketik_tetap_jalan(gerbang):
    """Ketikan UJI dicabut 2026-09-24 atas permintaan pengguna: layar ini milik
    developer/teknisi saat commissioning, dan mengetik kata yang sama sebelum
    tiap coil memperlambat pekerjaan yang memang berulang.

    Dua penjaga yang benar-benar menahan kecelakaan TETAP, dan keduanya diuji
    di berkas ini: ditolak 409 selama line memproses truk, dan tiap percobaan
    meninggalkan baris WARNING di event_log."""
    client, _, _, line_client = gerbang
    _masuk(client, "support@pks.test")

    jawab = client.post("/api/console/dev/plc/line-1/coil", json={"coil": 11})

    assert jawab.status_code == 200
    assert line_client.writes == [11]


def test_picu_saat_line_sibuk_ditolak(gerbang):
    """A truck being graded on that line refuses the fire outright (409) —
    a piston moving under a passing bunch is dangerous, not just untidy."""
    client, _, _, line_client = gerbang
    line_client.busy = True
    _masuk(client, "support@pks.test")

    jawab = client.post(
        "/api/console/dev/plc/line-1/coil", json={"coil": 11}
    )

    assert jawab.status_code == 409
    assert line_client.writes == []


def test_picu_berhasil_meninggalkan_baris_warning_di_log(gerbang):
    """The full happy path: confirmed, line idle, coil fired — and the press
    is still recorded, through the SAME logging path production uses
    (SqliteLogHandler on DevService's logger), so redaksi() is proven to run.
    """
    client, _, log_store, line_client = gerbang
    dev_logger = logging.getLogger("palmgrade.services.dev_service")
    dev_logger.handlers.clear()
    dev_logger.setLevel(logging.DEBUG)
    dev_logger.addHandler(SqliteLogHandler(log_store))
    dev_logger.propagate = False
    try:
        _masuk(client, "support@pks.test")

        jawab = client.post(
            "/api/console/dev/plc/line-1/coil", json={"coil": 11}
        )

        assert jawab.status_code == 200
        assert line_client.writes == [11]

        baris = log_store.read(level="WARNING", search="coil", limit=10, offset=0)["items"]
        assert len(baris) == 1
        assert "support@pks.test" in baris[0]["message"]
        assert "11" in baris[0]["message"]
        assert "line-1" in baris[0]["message"]
    finally:
        dev_logger.handlers.clear()


def test_line_tidak_terjangkau_juga_meninggalkan_jejak_di_log(gerbang):
    """A network-unreachable line is the ORDINARY state at a mill being
    commissioned or already broken — exactly when this button gets pressed,
    and exactly when the trail matters most. Before this test existed,
    `LineUnavailable` propagated past DevService's logging entirely and the
    press left NO row at all — asserting the row's content (not merely its
    presence) is what would have caught that.
    """
    client, _, log_store, line_client = gerbang
    line_client.unreachable = True
    dev_logger = logging.getLogger("palmgrade.services.dev_service")
    dev_logger.handlers.clear()
    dev_logger.setLevel(logging.DEBUG)
    dev_logger.addHandler(SqliteLogHandler(log_store))
    dev_logger.propagate = False
    try:
        _masuk(client, "support@pks.test")

        jawab = client.post(
            "/api/console/dev/plc/line-1/coil", json={"coil": 11}
        )

        assert jawab.status_code == 502
        assert line_client.writes == []

        baris = log_store.read(level="WARNING", search="coil", limit=10, offset=0)["items"]
        assert len(baris) == 1
        assert "support@pks.test" in baris[0]["message"]
        assert "11" in baris[0]["message"]
        assert "line-1" in baris[0]["message"]
    finally:
        dev_logger.handlers.clear()


def test_tanpa_sesi_401_bukan_403(gerbang):
    """No cookie must read as "sign in again", never as "wrong role"."""
    client, _, _, _ = gerbang

    jawab = client.get("/api/console/dev/plc/line-1")

    assert jawab.status_code == 401
