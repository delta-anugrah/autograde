"""`/api/console/dev/plc/*` — the only console lane that moves physical hardware.

Built like `test_dev_routes.py`: a bare app with the console router,
`get_console_service`/`get_auth_service` overridden onto a real store on
`tmp_path`, and `get_dev_service` overridden onto a `DevService` wrapping a
fake `LineClient` — never `create_console_app()`, which would touch a
developer's real `state/*.db`.

The PLC connection itself lives on the LINE process, not the console (only
`main.py` calls `start_plc_worker`; `console_main.py` never does) — so every
one of these routes proxies through `LineClient` to one line, the same way
`piston`/`assign-truck` already do. The fake `LineClient` below stands in for
that line and records what it was asked to write, so a test can assert a
coil was never touched even when the HTTP call returned 200.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import LineEndpoint
from palmgrade.core.log_sink import SqliteLogHandler
from palmgrade.domain.operator_auth import hash_password
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.integrations.notifications.line_client import LinePlcTolak, LineUnavailable
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.console import get_auth_service, get_console_service, get_dev_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.dev_service import DevService

SANDI = "pendukung2026"
LINE_1 = LineEndpoint("line-1", "Line 1", 8001, "m-1")


class _StubConsole:
    """The dev lane touches no console service; only the store is shared."""

    def __init__(self, store: ConsoleStore) -> None:
        self.store = store


class _FakeLineClient:
    """Stands in for the line this console proxies PLC commands to.

    `coil_ditulis` records every coil actually asked of `plc_coil` — the one
    thing every safety test below needs to assert is empty.
    """

    def __init__(self, *, inputs=None, assignment_busy: bool = False, unknown_coils=()):
        self._inputs = inputs if inputs is not None else []
        self._busy = assignment_busy
        self._unknown = set(unknown_coils)
        self.coil_ditulis: list[int] = []

    async def plc_state(self, line: LineEndpoint) -> dict:
        return {"enabled": True, "inputs": self._inputs, "testable_coils": [0, 1, 11]}

    async def plc_coil(self, line: LineEndpoint, *, coil: int, requested_by: str) -> dict:
        if coil in self._unknown:
            raise LinePlcTolak(422, "coil_tidak_dikenal")
        if self._busy:
            raise LinePlcTolak(409, "line_sedang_memproses_truk")
        self.coil_ditulis.append(coil)
        return {"fired": True, "coil": coil}


class _FakeLineClientTidakMenjawab:
    async def plc_state(self, line: LineEndpoint) -> dict:
        raise LineUnavailable("LINE_TIDAK_MENJAWAB", f"{line.line_code} tidak menjawab: timeout", line=line.name)

    async def plc_coil(self, line: LineEndpoint, *, coil: int, requested_by: str) -> dict:
        raise LineUnavailable("LINE_TIDAK_MENJAWAB", f"{line.line_code} tidak menjawab: timeout", line=line.name)


def _app_plc(tmp_path, *, inputs=None, assignment_id=None, unknown_coils=()):
    """`assignment_id` mirrors the brief's fixture name: non-None = line busy."""
    store = ConsoleStore(tmp_path / "console.db")
    log_store = LogStore(tmp_path / "log.db")
    erp_outbox = ErpOutboxStore(tmp_path / "erp_outbox.db")
    line_client = _FakeLineClient(
        inputs=inputs, assignment_busy=assignment_id is not None, unknown_coils=unknown_coils
    )

    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_dev_service] = lambda: DevService(
        log_store, line_client=line_client, lines=(LINE_1,), erp_outbox=erp_outbox, settings=_FakeSettings()
    )
    return app, store, line_client


class _FakeSettings:
    app_version = "9.9.9-test"
    machine_id = "mesin-uji"
    environment = "test"
    lic_enabled = True
    lic_token = "token-rahasia"


def _client_support(app, store, *, email: str = "s@b.c") -> TestClient:
    store.upsert_operator_lokal({"email": email, "nama": "Support", "password_hash": hash_password(SANDI)})
    store.set_peran(store.operator_by_email(email)["id"], "support")
    client = TestClient(app)
    assert client.post("/api/console/login", json={"email": email, "sandi": SANDI}).status_code == 200
    return client


def _client_operator(app, store, *, email: str = "o@b.c") -> TestClient:
    store.upsert_operator_lokal({"email": email, "nama": "Operator", "password_hash": hash_password(SANDI)})
    client = TestClient(app)
    assert client.post("/api/console/login", json={"email": email, "sandi": SANDI}).status_code == 200
    return client


def test_baca_di_tidak_menyentuh_coil(tmp_path):
    """Membaca harus aman; layar ini boleh dibuka kapan saja."""
    app, store, plc = _app_plc(tmp_path, inputs=[True, False, True])
    data = _client_support(app, store).get("/api/console/dev/plc/line-1").json()
    assert data["inputs"] == [True, False, True]
    assert plc.coil_ditulis == []


def test_baca_line_tidak_dikenal_404(tmp_path):
    app, store, _ = _app_plc(tmp_path)
    r = _client_support(app, store).get("/api/console/dev/plc/line-9")
    assert r.status_code == 404


def test_baca_saat_plc_mati_tidak_error(tmp_path):
    """PLC_ENABLED=false adalah keadaan normal dev/cloud — layar harus terbuka,
    bukan gagal, dan mengatakan PLC mati."""
    store = ConsoleStore(tmp_path / "console.db")
    log_store = LogStore(tmp_path / "log.db")
    erp_outbox = ErpOutboxStore(tmp_path / "erp_outbox.db")

    class _LineClientPlcMati:
        async def plc_state(self, line):
            return {"enabled": False, "inputs": [], "testable_coils": []}

    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_dev_service] = lambda: DevService(
        log_store, line_client=_LineClientPlcMati(), lines=(LINE_1,), erp_outbox=erp_outbox, settings=_FakeSettings()
    )
    data = _client_support(app, store).get("/api/console/dev/plc/line-1").json()
    assert data["enabled"] is False


def test_picu_coil_ditolak_saat_line_memproses_truk(tmp_path):
    """Piston bergerak saat janjang lewat itu bahaya, bukan cuma berantakan."""
    app, store, plc = _app_plc(tmp_path, assignment_id="a-1")
    r = _client_support(app, store).post(
        "/api/console/dev/plc/line-1/coil", json={"coil": 11, "konfirmasi": "UJI"}
    )
    assert r.status_code == 409
    assert plc.coil_ditulis == []


def test_picu_coil_ditolak_tanpa_konfirmasi_ketik(tmp_path):
    """Klik bisa kesenggol; ketikan tidak."""
    app, store, plc = _app_plc(tmp_path)
    r = _client_support(app, store).post(
        "/api/console/dev/plc/line-1/coil", json={"coil": 11, "konfirmasi": ""}
    )
    assert r.status_code == 400
    assert plc.coil_ditulis == []


def test_picu_coil_ditolak_konfirmasi_salah_ketik(tmp_path):
    """Bukan cuma "tidak kosong" — harus persis kata yang diminta layar."""
    app, store, plc = _app_plc(tmp_path)
    r = _client_support(app, store).post(
        "/api/console/dev/plc/line-1/coil", json={"coil": 11, "konfirmasi": "uji coba"}
    )
    assert r.status_code == 400
    assert plc.coil_ditulis == []


def test_picu_coil_jalan_saat_line_menganggur(tmp_path):
    app, store, plc = _app_plc(tmp_path, assignment_id=None)
    r = _client_support(app, store).post(
        "/api/console/dev/plc/line-1/coil", json={"coil": 11, "konfirmasi": "UJI"}
    )
    assert r.status_code == 200
    assert plc.coil_ditulis == [11]


def test_penekanan_meninggalkan_jejak_di_log(tmp_path):
    """Kalau ada kejadian di pabrik, ketahuan siapa menekan apa dan kapan.

    Verified through the REAL logging path (SqliteLogHandler attached to
    DevService's own logger, exactly like production's pasang_log_sink) —
    not a mock — so this proves redaksi() actually runs before the row lands,
    and that log_kejadian gets the row at all.
    """
    app, store, _ = _app_plc(tmp_path)
    log_store = LogStore(tmp_path / "log.db")
    dev_logger = logging.getLogger("palmgrade.services.dev_service")
    dev_logger.handlers.clear()
    dev_logger.setLevel(logging.DEBUG)
    dev_logger.addHandler(SqliteLogHandler(log_store))
    dev_logger.propagate = False
    try:
        erp_outbox = ErpOutboxStore(tmp_path / "erp_outbox2.db")
        line_client = _FakeLineClient()
        app.dependency_overrides[get_dev_service] = lambda: DevService(
            log_store, line_client=line_client, lines=(LINE_1,), erp_outbox=erp_outbox, settings=_FakeSettings()
        )
        _client_support(app, store, email="s@b.c").post(
            "/api/console/dev/plc/line-1/coil", json={"coil": 11, "konfirmasi": "UJI"}
        )
        items = log_store.baca(level="WARNING", cari="coil", limit=10, offset=0)["items"]
        assert len(items) == 1
        assert "s@b.c" in items[0]["pesan"]
        assert "11" in items[0]["pesan"]
    finally:
        dev_logger.handlers.clear()


def test_penolakan_juga_meninggalkan_jejak_di_log(tmp_path):
    """A refused press is still an attempt to fire hardware — it belongs in
    the trail too, not just successful ones."""
    log_store = LogStore(tmp_path / "log.db")
    dev_logger = logging.getLogger("palmgrade.services.dev_service")
    dev_logger.handlers.clear()
    dev_logger.setLevel(logging.DEBUG)
    dev_logger.addHandler(SqliteLogHandler(log_store))
    dev_logger.propagate = False
    try:
        app, store, _ = _app_plc(tmp_path, assignment_id="a-1")
        _client_support(app, store, email="s@b.c").post(
            "/api/console/dev/plc/line-1/coil", json={"coil": 11, "konfirmasi": "UJI"}
        )
        items = log_store.baca(level="WARNING", cari="coil", limit=10, offset=0)["items"]
        assert len(items) == 1
        assert "s@b.c" in items[0]["pesan"]
    finally:
        dev_logger.handlers.clear()


def test_coil_di_luar_daftar_ditolak(tmp_path):
    """Hanya coil yang memang dipetakan; nomor asing tidak boleh sampai ke PLC."""
    app, store, plc = _app_plc(tmp_path, unknown_coils=(999,))
    r = _client_support(app, store).post(
        "/api/console/dev/plc/line-1/coil", json={"coil": 999, "konfirmasi": "UJI"}
    )
    assert r.status_code == 422
    assert plc.coil_ditulis == []


def test_picu_line_tidak_dikenal_404(tmp_path):
    app, store, _ = _app_plc(tmp_path)
    r = _client_support(app, store).post(
        "/api/console/dev/plc/line-9/coil", json={"coil": 11, "konfirmasi": "UJI"}
    )
    assert r.status_code == 404


def test_picu_line_tidak_menjawab_502(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    log_store = LogStore(tmp_path / "log.db")
    erp_outbox = ErpOutboxStore(tmp_path / "erp_outbox.db")
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_dev_service] = lambda: DevService(
        log_store, line_client=_FakeLineClientTidakMenjawab(), lines=(LINE_1,),
        erp_outbox=erp_outbox, settings=_FakeSettings(),
    )
    r = _client_support(app, store).post(
        "/api/console/dev/plc/line-1/coil", json={"coil": 11, "konfirmasi": "UJI"}
    )
    assert r.status_code == 502


def test_line_tidak_terjangkau_juga_meninggalkan_jejak_di_log(tmp_path):
    """A network-unreachable line is the ORDINARY state at a mill being
    commissioned or already broken — exactly when this button gets pressed,
    and exactly when the trail matters most. `LineClient` logs its own line
    for the network story (no operator identity there), but the console's
    own trail must still name who pressed what. Asserts the row's CONTENT,
    not merely that a row exists — a row with no email would still pass a
    weaker assertion and hide this exact regression.
    """
    store = ConsoleStore(tmp_path / "console.db")
    log_store = LogStore(tmp_path / "log.db")
    erp_outbox = ErpOutboxStore(tmp_path / "erp_outbox.db")
    dev_logger = logging.getLogger("palmgrade.services.dev_service")
    dev_logger.handlers.clear()
    dev_logger.setLevel(logging.DEBUG)
    dev_logger.addHandler(SqliteLogHandler(log_store))
    dev_logger.propagate = False
    try:
        app = FastAPI()
        app.include_router(console_router)
        app.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
        app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
        app.dependency_overrides[get_dev_service] = lambda: DevService(
            log_store, line_client=_FakeLineClientTidakMenjawab(), lines=(LINE_1,),
            erp_outbox=erp_outbox, settings=_FakeSettings(),
        )
        r = _client_support(app, store, email="s@b.c").post(
            "/api/console/dev/plc/line-1/coil", json={"coil": 11, "konfirmasi": "UJI"}
        )
        assert r.status_code == 502

        items = log_store.baca(level="WARNING", cari="coil", limit=10, offset=0)["items"]
        assert len(items) == 1
        assert "s@b.c" in items[0]["pesan"]
        assert "11" in items[0]["pesan"]
        assert "line-1" in items[0]["pesan"]
    finally:
        dev_logger.handlers.clear()


def test_uji_plc_menolak_operator_biasa(tmp_path):
    app, store, _ = _app_plc(tmp_path)
    assert _client_operator(app, store).get("/api/console/dev/plc/line-1").status_code == 403


def test_uji_plc_coil_menolak_operator_biasa(tmp_path):
    app, store, _ = _app_plc(tmp_path)
    r = _client_operator(app, store).post(
        "/api/console/dev/plc/line-1/coil", json={"coil": 11, "konfirmasi": "UJI"}
    )
    assert r.status_code == 403


def test_uji_plc_tanpa_sesi_401(tmp_path):
    app, _, _ = _app_plc(tmp_path)
    client = TestClient(app)
    assert client.get("/api/console/dev/plc/line-1").status_code == 401
