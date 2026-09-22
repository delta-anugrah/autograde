"""End-to-end: keadaan langganan sampai ke layar lewat HTTP sungguhan.

Yang cuma bisa dibuktikan di sini, bukan di unit test:

- **operator BIASA** ikut mendapat keadaan langganan. Ini yang paling penting:
  banner-nya untuk operator, dan kalau datanya cuma lewat `/api/console/dev/*`
  dia akan dijawab 403 dan layar diam persis di saat kamera berhenti;
- token tidak ikut keluar di jawaban mana pun;
- satu proses konsol memverifikasi tokennya sendiri, tanpa menyentuh line.

App-nya dirakit sendiri di sini dengan dependensi di-override, bukan
`create_console_app()` — yang itu menyentuh `state/console.db` milik developer.
"""

from __future__ import annotations

import base64
import json
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.role import ROLE_OPERATOR, ROLE_SUPPORT
from palmgrade.license.manager import LicenseManager
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.console import get_auth_service, get_console_service, get_dev_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.dev_service import DevService

SANDI = "sokongan2026"
SECONDS_PER_DAY = 86_400
COMPANY = "PT Sawit Rambang Lestari"
TOKEN_RAHASIA = "token.yang.tidak.boleh.muncul.di.layar"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def manager_untuk(expires_in_days: float, *, grace_days: int = 60, warning_days: int = 30):
    """Token Ed25519 sungguhan — bukan mock, supaya jalur verifikasinya ikut teruji."""
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    now = int(time.time())
    expires_at = now + int(expires_in_days * SECONDS_PER_DAY)
    payload = {
        "company_id": COMPANY,
        "company_name": COMPANY,
        "status": "ACTIVE",
        "iat": now,
        "nbf": now,
        "license_expires_at": expires_at,
        "grace_days_after_expiry": grace_days,
        "warning_days_before_expiry": warning_days,
        "exp": expires_at + grace_days * SECONDS_PER_DAY,
        "server_time": now,
        "nonce": "n" * 32,
        "kid": "v1",
    }
    header = _b64(json.dumps({"alg": "EdDSA", "typ": "JWT", "kid": "v1"}).encode())
    body = _b64(json.dumps(payload).encode())
    return LicenseManager(pub, None, f"{header}.{body}.{_b64(key.sign(f'{header}.{body}'.encode()))}")


class _FakeSettings:
    app_version = "9.9.9-e2e"
    machine_id = "mesin-e2e"
    environment = "test"
    factory_tz = "Asia/Jakarta"
    lic_enabled = True
    lic_token = TOKEN_RAHASIA


class _StubConsole:
    """Cukup untuk `/api/console/state`; sisanya tidak disentuh test ini."""

    def __init__(self, store: ConsoleStore) -> None:
        self.store = store
        self.settings = _FakeSettings()

    def state(self) -> dict:
        return {
            "work_date": "2026-09-22",
            "timezone": "Asia/Jakarta",
            "lines": [],
            "recent": [],
            "auto_releases": [],
        }


class _LineClientYangGagal:
    """Kalau lisensi pernah ditanyakan ke line, test ini yang meledak."""

    async def health_detail(self, line):
        raise AssertionError("lisensi tidak boleh diambil dari line")


def _rakit(tmp_path, manager):
    store = ConsoleStore(tmp_path / "console.db")
    for email, role in (("operator@pks.test", ROLE_OPERATOR), ("support@pks.test", ROLE_SUPPORT)):
        store.upsert_operator_manual(
            {
                "email": email,
                "nama": email,
                "password_hash": hash_password(SANDI),
                "role": role,
            }
        )

    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_dev_service] = lambda: DevService(
        LogStore(tmp_path / "log.db"),
        line_client=_LineClientYangGagal(),
        lines=(),
        settings=_FakeSettings(),
        license_manager=manager,
    )
    return TestClient(app)


@pytest.fixture
def sehat(tmp_path):
    return _rakit(tmp_path, manager_untuk(180))


@pytest.fixture
def hampir_habis(tmp_path):
    return _rakit(tmp_path, manager_untuk(10))


@pytest.fixture
def tenggang(tmp_path):
    return _rakit(tmp_path, manager_untuk(-5))


@pytest.fixture
def mati(tmp_path):
    return _rakit(tmp_path, manager_untuk(-90))


def _masuk(client: TestClient, email: str) -> None:
    assert client.post(
        "/api/console/login", json={"email": email, "sandi": SANDI}
    ).status_code == 200


# --------------------------------------------------------- operator biasa


def test_operator_biasa_mendapat_keadaan_langganan(sehat):
    """Inti dari fitur ini: banner-nya untuk operator, jadi datanya harus
    sampai ke akun operator — bukan cuma ke support."""
    _masuk(sehat, "operator@pks.test")

    jawab = sehat.get("/api/console/state")

    assert jawab.status_code == 200
    assert jawab.json()["lisensi"]["severity"] == "none"


def test_operator_biasa_melihat_peringatan_mendekati_habis(hampir_habis):
    _masuk(hampir_habis, "operator@pks.test")

    lisensi = hampir_habis.get("/api/console/state").json()["lisensi"]

    assert lisensi["severity"] == "warning"
    assert lisensi["sisa_hari"] == 10


def test_operator_biasa_melihat_masa_tenggang(tenggang):
    _masuk(tenggang, "operator@pks.test")

    lisensi = tenggang.get("/api/console/state").json()["lisensi"]

    assert lisensi["severity"] == "grace"
    assert lisensi["sisa_hari"] == 55


def test_operator_biasa_melihat_grading_berhenti(mati):
    """Ini keadaan yang dulu sama sekali tidak dijelaskan ke operator."""
    _masuk(mati, "operator@pks.test")

    lisensi = mati.get("/api/console/state").json()["lisensi"]

    assert lisensi["severity"] == "blocked"


def test_tanpa_sesi_state_tetap_401(sehat):
    """Menumpangkan lisensi di `state` tidak boleh melonggarkan gerbangnya."""
    assert sehat.get("/api/console/state").status_code == 401


# ------------------------------------------------------------------ support


def test_kartu_support_membawa_tanggal(sehat):
    _masuk(sehat, "support@pks.test")

    lisensi = sehat.get("/api/console/dev/versi").json()["lisensi"]

    assert lisensi["perusahaan"] == COMPANY
    assert lisensi["aktif_sampai"] > time.time()
    assert lisensi["tenggang_sampai"] > lisensi["aktif_sampai"]


def test_operator_biasa_tetap_ditolak_di_lane_support(sehat):
    """Tanggalnya boleh dilihat operator lewat `state`; lane support tetap 403."""
    _masuk(sehat, "operator@pks.test")

    assert sehat.get("/api/console/dev/versi").status_code == 403


# ------------------------------------------------------------------ rahasia


def test_token_tidak_pernah_keluar_lewat_http(sehat):
    """Layar ini dibaca lewat AnyDesk di PC yang bisa diakses orang lain."""
    _masuk(sehat, "support@pks.test")

    for jalur in ("/api/console/state", "/api/console/dev/versi"):
        assert TOKEN_RAHASIA not in sehat.get(jalur).text, jalur


def test_lisensi_tidak_diambil_dari_line(sehat):
    """`_LineClientYangGagal` meledak kalau ada yang bertanya ke line. Konsol
    harus memverifikasi tokennya sendiri: line yang sedang restart tidak boleh
    membuat langganan terlihat rusak."""
    _masuk(sehat, "operator@pks.test")

    assert sehat.get("/api/console/state").status_code == 200
