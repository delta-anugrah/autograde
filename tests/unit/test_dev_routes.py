"""`/api/console/dev/*` — support-only developer lanes.

Built the same way as `test_console_routes_auth.py`: a bare app with the
console router, `get_console_service`/`get_auth_service` overridden onto a
real store on `tmp_path`, and `get_dev_service` overridden onto a `DevService`
wrapping real collaborators on `tmp_path` — never `create_console_app()`,
which would touch a developer's real `state/*.db`.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import LineEndpoint
from palmgrade.domain.operator_auth import hash_password
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.console import get_auth_service, get_console_service, get_dev_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.dev_service import DevService

SANDI = "pendukung2026"

LINE_1 = LineEndpoint("line-1", "Line 1", 8001, "m-1")
LINE_2 = LineEndpoint("line-2", "Line 2", 8002, "m-2")


class _StubConsole:
    """The dev lane touches no console service; only the store is shared."""

    def __init__(self, store: ConsoleStore) -> None:
        self.store = store


class _LineClientPalsu:
    """Answers `health_detail` from a fixed map, keyed by `line_code`."""

    def __init__(self, jawaban: dict[str, dict[str, Any]]) -> None:
        self._jawaban = jawaban

    async def health_detail(self, line: LineEndpoint) -> dict[str, Any]:
        return self._jawaban[line.line_code]


class _LineClientMati:
    """Every line raises `LineUnavailable`, like a camera line that never answers."""

    async def health_detail(self, line: LineEndpoint) -> dict[str, Any]:
        raise LineUnavailable("LINE_TIDAK_MENJAWAB", f"{line.line_code} tidak menjawab: timeout", line=line.name)


def _app_dev(tmp_path, *, line_client=None, lines=(LINE_1, LINE_2)):
    store = ConsoleStore(tmp_path / "console.db")
    log_store = LogStore(tmp_path / "log.db")
    erp_outbox = ErpOutboxStore(tmp_path / "erp_outbox.db")

    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_dev_service] = lambda: DevService(
        log_store,
        line_client=line_client,
        lines=lines,
        erp_outbox=erp_outbox,
        settings=_FakeSettings(),
    )
    return app, store, log_store, erp_outbox


class _FakeSettings:
    """Just the fields `DevService.versi()` reads — never a secret among them."""

    app_version = "9.9.9-test"
    machine_id = "mesin-uji"
    environment = "test"
    lic_enabled = True
    lic_token = "token-rahasia-jangan-bocor"


def _client_support(app, store) -> TestClient:
    store.upsert_operator_lokal(
        {"email": "s@b.c", "nama": "Support", "password_hash": hash_password(SANDI)}
    )
    store.set_peran(store.operator_by_email("s@b.c")["id"], "support")
    client = TestClient(app)
    assert client.post(
        "/api/console/login", json={"email": "s@b.c", "sandi": SANDI}
    ).status_code == 200
    return client


@pytest.fixture
def dev(tmp_path):
    return _app_dev(tmp_path)


def test_log_butuh_peran_support(dev):
    app, store, _, _ = dev
    store.upsert_operator_lokal(
        {"email": "o@b.c", "nama": "O", "password_hash": hash_password(SANDI)}
    )
    client = TestClient(app)
    client.post("/api/console/login", json={"email": "o@b.c", "sandi": SANDI})

    assert client.get("/api/console/dev/log").status_code == 403


def test_log_tanpa_sesi_401(dev):
    app, _, _, _ = dev
    client = TestClient(app)

    response = client.get("/api/console/dev/log")

    assert response.status_code == 401


def test_log_mengembalikan_halaman_dan_total(dev):
    app, store, log_store, _ = dev
    # Real-clock timestamps: DevService's own hourly purge (below) compares
    # against wall-clock time.time(), so a fixed-epoch stub like 1000.0 would
    # read as 180 days expired and vanish before the assertion runs.
    dasar = time.time()
    for i in range(25):
        log_store.tulis("ERROR", f"s{i}", f"pesan {i}", None, now=dasar + i)
    client = _client_support(app, store)

    data = client.get("/api/console/dev/log?limit=10").json()

    assert data["total"] == 25
    assert len(data["items"]) == 10


def test_log_saring_level(dev):
    app, store, log_store, _ = dev
    dasar = time.time()
    log_store.tulis("ERROR", "a", "satu", None, now=dasar)
    log_store.tulis("WARNING", "b", "dua", None, now=dasar + 1)
    client = _client_support(app, store)

    assert client.get("/api/console/dev/log?level=ERROR").json()["total"] == 1


def test_log_limit_dibatasi_atas(dev):
    """Satu permintaan tidak boleh menarik 180 hari riwayat sekaligus."""
    app, store, _, _ = dev
    client = _client_support(app, store)

    assert client.get("/api/console/dev/log?limit=99999").status_code == 422


def test_log_offset_tidak_boleh_negatif(dev):
    app, store, _, _ = dev
    client = _client_support(app, store)

    assert client.get("/api/console/dev/log?offset=-1").status_code == 422


def test_log_cari_menyaring_pesan(dev):
    app, store, log_store, _ = dev
    dasar = time.time()
    log_store.tulis("ERROR", "a", "kamera putus", None, now=dasar)
    log_store.tulis("ERROR", "b", "antrean penuh", None, now=dasar + 1)
    client = _client_support(app, store)

    assert client.get("/api/console/dev/log?cari=kamera").json()["total"] == 1


# ── diagnostik: /health/detail per line, gathered concurrently ─────────────


def test_diagnostik_mengumpulkan_tiap_line(tmp_path):
    line_client = _LineClientPalsu({
        "line-1": {"status": "ok", "camera_connected": True},
        "line-2": {"status": "ok", "camera_connected": True},
    })
    app, store, _, _ = _app_dev(tmp_path, line_client=line_client)
    client = _client_support(app, store)

    data = client.get("/api/console/dev/diagnostik").json()

    assert data["lines"]["line-1"] == {"terjangkau": True, "status": "ok", "camera_connected": True}
    assert data["lines"]["line-2"]["terjangkau"] is True


def test_line_mati_dilaporkan_bukan_mengosongkan_layar(tmp_path):
    """Satu line mati justru yang perlu dilihat; layar tidak boleh gagal karenanya."""
    app, store, _, _ = _app_dev(tmp_path, line_client=_LineClientMati())
    client = _client_support(app, store)

    data = client.get("/api/console/dev/diagnostik").json()

    assert data["lines"]["line-1"]["terjangkau"] is False
    assert "tidak menjawab" in data["lines"]["line-1"]["sebab"]
    assert data["lines"]["line-2"]["terjangkau"] is False


def test_satu_line_mati_tidak_menjatuhkan_line_lain(tmp_path):
    """Campuran: satu line hidup, satu mati — masing-masing dilaporkan apa adanya."""
    class _Campuran:
        async def health_detail(self, line: LineEndpoint):
            if line.line_code == "line-1":
                return {"status": "ok"}
            raise LineUnavailable("LINE_TIDAK_MENJAWAB", f"{line.line_code} tidak menjawab: timeout", line=line.name)

    app, store, _, _ = _app_dev(tmp_path, line_client=_Campuran())
    client = _client_support(app, store)

    data = client.get("/api/console/dev/diagnostik").json()

    assert data["lines"]["line-1"]["terjangkau"] is True
    assert data["lines"]["line-2"]["terjangkau"] is False


def test_diagnostik_butuh_peran_support(dev):
    app, store, _, _ = dev
    store.upsert_operator_lokal(
        {"email": "o2@b.c", "nama": "O2", "password_hash": hash_password(SANDI)}
    )
    client = TestClient(app)
    client.post("/api/console/login", json={"email": "o2@b.c", "sandi": SANDI})

    assert client.get("/api/console/dev/diagnostik").status_code == 403


# ── antrean: ERP outbox summary + resend ────────────────────────────────────


def test_antrean_menampilkan_sebab_gagal(dev):
    app, store, _, erp_outbox = dev
    erp_outbox.enqueue("truck", "K1", {"plate_number": "BE 1 AA"})
    erp_outbox.mark_error(erp_outbox.due()[0], "417 unknown field")
    client = _client_support(app, store)

    data = client.get("/api/console/dev/antrean").json()

    assert data["gagal"] == 1
    assert "417" in data["items"][0]["last_error"]


def test_antrean_menghitung_pending_dan_gagal_terpisah(dev):
    app, store, _, erp_outbox = dev
    erp_outbox.enqueue("truck", "K1", {"v": 1})
    erp_outbox.enqueue("truck", "K2", {"v": 2})
    erp_outbox.mark_error(erp_outbox.due()[0], "timeout")
    client = _client_support(app, store)

    data = client.get("/api/console/dev/antrean").json()

    assert data["pending"] == 1
    assert data["gagal"] == 1


def test_kirim_ulang_memindahkan_gagal_jadi_pending(dev):
    app, store, _, erp_outbox = dev
    erp_outbox.enqueue("truck", "K1", {"v": 1})
    erp_outbox.mark_error(erp_outbox.due()[0], "timeout")
    client = _client_support(app, store)

    hasil = client.post("/api/console/dev/antrean/kirim-ulang").json()

    assert hasil["dikirim_ulang"] == 1
    assert client.get("/api/console/dev/antrean").json()["gagal"] == 0


def test_kirim_ulang_adalah_post_bukan_get(dev):
    app, store, _, _ = dev
    client = _client_support(app, store)

    assert client.get("/api/console/dev/antrean/kirim-ulang").status_code == 405


def test_antrean_butuh_peran_support(dev):
    app, store, _, _ = dev
    store.upsert_operator_lokal(
        {"email": "o3@b.c", "nama": "O3", "password_hash": hash_password(SANDI)}
    )
    client = TestClient(app)
    client.post("/api/console/login", json={"email": "o3@b.c", "sandi": SANDI})

    assert client.get("/api/console/dev/antrean").status_code == 403
    assert client.post("/api/console/dev/antrean/kirim-ulang").status_code == 403


# ── versi: version, machine id, licence state — never a secret ─────────────


def test_versi_membawa_machine_id_dan_lisensi(dev):
    app, store, _, _ = dev
    client = _client_support(app, store)

    data = client.get("/api/console/dev/versi").json()

    assert data["machine_id"] == "mesin-uji"
    assert data["versi"] == "9.9.9-test"
    assert "lisensi" in data


def test_versi_tidak_membocorkan_rahasia(dev):
    """The one secret _FakeSettings carries must never reach the response body."""
    app, store, _, _ = dev
    client = _client_support(app, store)

    mentah = client.get("/api/console/dev/versi").text

    assert "token-rahasia-jangan-bocor" not in mentah


def test_versi_butuh_peran_support(dev):
    app, store, _, _ = dev
    store.upsert_operator_lokal(
        {"email": "o4@b.c", "nama": "O4", "password_hash": hash_password(SANDI)}
    )
    client = TestClient(app)
    client.post("/api/console/login", json={"email": "o4@b.c", "sandi": SANDI})

    assert client.get("/api/console/dev/versi").status_code == 403


def test_semua_lane_dev_menolak_operator_biasa(dev):
    """Satu tes untuk keempatnya: penjaganya satu, jadi lupa memasangnya kelihatan."""
    app, store, _, _ = dev
    store.upsert_operator_lokal(
        {"email": "o5@b.c", "nama": "O5", "password_hash": hash_password(SANDI)}
    )
    client = TestClient(app)
    client.post("/api/console/login", json={"email": "o5@b.c", "sandi": SANDI})

    for jalur in ("log", "diagnostik", "antrean", "versi"):
        assert client.get(f"/api/console/dev/{jalur}").status_code == 403
