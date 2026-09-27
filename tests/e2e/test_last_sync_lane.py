"""End-to-end Last Sync lewat HTTP dengan login sungguhan.

- Operator BIASA mendapat Last Sync di `/api/console/state` (bukan lane support):
  yang melihat sambungan putus itu operator, sama alasannya dengan banner lisensi.
- Perubahan keadaan yang dicatat worker terbaca di polling berikutnya.
- Pesan galat mentah TIDAK ikut ke layar operator (ada di tab Log untuk support).

App-nya dirakit sendiri dengan dependensi di-override, bukan `create_console_app()`
yang menyentuh `state/console.db` milik developer.
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.console import get_auth_service, get_console_service, get_dev_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.dev_service import DevService
from palmgrade.services.status_sinkron import StatusSinkron

SANDI = "sandi-e2e-sinkron"


class _Jam:
    now = 1_790_000_000.0

    def __call__(self) -> float:
        return self.now


class _LineTakDipanggil:
    async def status(self, line):
        raise AssertionError("state tidak boleh memanggil line langsung")


@pytest.fixture
def rakitan(tmp_path):
    settings = replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta",
                       erp_url="http://erp.local", r2_bucket="palmgrade")
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual(
        {"email": "operator@pks.test", "full_name": "Operator", "password_hash": hash_password(SANDI)}
    )
    jam = _Jam()
    status = StatusSinkron(store, erp_aktif=True, r2_aktif=True, jam=jam)
    service = ConsoleService(settings, store, _LineTakDipanggil(), status_sinkron=status)
    service.line_status = lambda: {
        "line-1": {"reachable": True, "unggah": {"aktif": True, "terakhir": jam.now - 1_800,
                                                 "gagal_sejak": None, "antre": 3, "rusak": 0}},
    }
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_dev_service] = lambda: DevService(
        LogStore(tmp_path / "log.db"), console_store=store, settings=settings
    )
    client = TestClient(app)
    res = client.post("/api/console/login", json={"email": "operator@pks.test", "sandi": SANDI})
    assert res.status_code == 200, res.text
    return client, status, jam, service


def test_operator_biasa_mendapat_last_sync_di_polling_state(rakitan):
    client, status, jam, _ = rakitan
    status.berhasil("erp", "tarik", sinkron=True)

    sinkron = client.get("/api/console/state").json()["sinkron"]

    assert (sinkron["autoerp"]["keadaan"], sinkron["autoerp"]["terakhir"]) == ("tersambung", jam.now)
    # Konsol belum pernah mengecek R2, tapi line sudah mengunggah setengah jam lalu.
    cloud = sinkron["cloud"]
    assert (cloud["keadaan"], cloud["terakhir"], cloud["antre"]) == ("tersambung", jam.now - 1_800, 3)


def test_putus_lalu_pulih_terbaca_di_polling_berikutnya(rakitan):
    client, status, jam, _ = rakitan
    status.berhasil("erp", "tarik", sinkron=True)

    jam.now += 60
    status.gagal("erp", "cek", "GET /api/method/ping: [Errno 8] nodename nor servname provided", jaringan=True)
    putus = client.get("/api/console/state").json()["sinkron"]["autoerp"]

    jam.now += 600
    status.berhasil("erp", "cek", sinkron=False)
    pulih = client.get("/api/console/state").json()["sinkron"]["autoerp"]

    assert (putus["keadaan"], putus["sejak"]) == ("terputus", jam.now - 600)
    assert (pulih["keadaan"], pulih["sejak"]) == ("tersambung", None)


def test_pesan_galat_mentah_tidak_sampai_ke_layar_operator(rakitan):
    client, status, _, _ = rakitan
    status.gagal("erp", "cek", "GET http://erp.local/api/method/ping: token rahasia-xyz ditolak")

    res = client.get("/api/console/state")

    assert "rahasia-xyz" not in res.text and "erp.local" not in res.text


def test_tanpa_sesi_tetap_401(rakitan):
    _, _, _, _ = rakitan
    assert TestClient(rakitan[0].app).get("/api/console/state").status_code == 401


def test_alasan_gagal_upload_foto_line_tidak_ikut_ke_layar(rakitan):
    """Blok `unggah` line membawa `pesan` mentah (bisa memuat URL akun R2). Layar cuma
    butuh ringkasan di `sinkron`; kartu line tidak ikut membawa blok itu."""
    client, _, jam, service = rakitan
    service.line_status = lambda: {
        "line-1": {"reachable": True, "unggah": {
            "aktif": True, "terakhir": jam.now - 7_200, "gagal_sejak": jam.now - 3_600, "antre": 4,
            "rusak": 0, "pesan": "PUT R2 gagal: https://akun-rahasia.r2.cloudflarestorage.com/palmgrade",
        }},
    }

    res = client.get("/api/console/state")

    assert res.json()["sinkron"]["cloud"]["keadaan"] == "terputus"
    assert "akun-rahasia" not in res.text
