"""End-to-end tab Akun yang bisa MENULIS: semuanya lewat HTTP dengan login sungguhan.

Yang dibuktikan di sini, bukan di unit test:

- lane-nya benar-benar di balik `require_support` (401 tanpa sesi, 403 untuk
  operator biasa) untuk keempat aksi;
- akun yang dibuat dari layar bisa dipakai masuk lewat gerbang yang sama;
- ganti sandi dan matikan akun memutus sesi yang SEDANG dipakai orang itu;
- penolakan datang sebagai kode yang diterjemahkan layar, dengan status HTTP
  yang masuk akal (400 isian, 404 tidak ada, 409 keadaan menolak);
- hash sandi tidak pernah keluar di jawaban mana pun.

Rute dirakit lewat dependency graph asli dengan dependensi di-override, bukan
`create_console_app()` yang menyentuh `state/*.db` milik developer.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.domain.operator_auth import hash_password
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.console import (
    get_auth_service,
    get_console_service,
    get_dev_service,
    get_operator_admin,
)
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.dev_service import DevService
from palmgrade.services.operator_admin import OperatorAdmin

SANDI = "sandi-e2e-akun"
BARU = "sandi-baru-e2e"
ERP_HASH = "$pbkdf2-sha256$29000$LuX8f895T2kNYcx5T2nt3Q$D5HIS3SGDVbL0W7HeOWXMlT9lQuv4dWlA8wOFbs0AW8"


class _StubConsole:
    def __init__(self, store: ConsoleStore) -> None:
        self.store = store


@pytest.fixture
def store(tmp_path) -> ConsoleStore:
    return ConsoleStore(tmp_path / "console.db")


@pytest.fixture
def app(tmp_path, store):
    aplikasi = FastAPI()
    aplikasi.include_router(console_router)
    aplikasi.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    aplikasi.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    aplikasi.dependency_overrides[get_dev_service] = lambda: DevService(
        LogStore(tmp_path / "log.db"), console_store=store
    )
    aplikasi.dependency_overrides[get_operator_admin] = lambda: OperatorAdmin(store)
    for email, role in (("support@pks.test", "support"), ("operator@pks.test", "operator")):
        store.upsert_operator_manual(
            {"email": email, "full_name": email.split("@")[0], "password_hash": hash_password(SANDI)}
        )
        store.set_role(store.operator_by_email(email)["id"], role)
    store.upsert_operator_erp(
        {"email": "erp@pks.test", "full_name": "Orang ERP", "password_hash": ERP_HASH, "active": 1}
    )
    return aplikasi


def _masuk(aplikasi, email: str, sandi: str = SANDI) -> TestClient:
    client = TestClient(aplikasi)
    res = client.post("/api/console/login", json={"email": email, "sandi": sandi})
    assert res.status_code == 200, res.text
    return client


def _bisa_masuk(aplikasi, email: str, sandi: str) -> bool:
    res = TestClient(aplikasi).post("/api/console/login", json={"email": email, "sandi": sandi})
    return res.status_code == 200


def _akun(client: TestClient) -> dict[str, dict]:
    return {a["email"]: a for a in client.get("/api/console/dev/akun").json()["akun"]}


_BARU = {"email": "budi@pks.test", "nama": "Pak Budi", "sandi": BARU, "sandi_ulang": BARU,
         "role": "operator"}

_AKSI = [
    ("/api/console/dev/akun", _BARU),
    ("/api/console/dev/akun/sandi", {"email": "operator@pks.test", "sandi": BARU,
                                     "sandi_ulang": BARU}),
    ("/api/console/dev/akun/status", {"email": "operator@pks.test", "aktif": False}),
    ("/api/console/dev/akun/role", {"email": "operator@pks.test", "role": "support"}),
]


@pytest.mark.parametrize(("path", "isi"), _AKSI)
def test_keempat_aksi_ditolak_tanpa_sesi_dan_untuk_operator_biasa(app, store, path, isi):
    assert TestClient(app).post(path, json=isi).status_code == 401
    operator = _masuk(app, "operator@pks.test")

    res = operator.post(path, json=isi)

    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "bukan_support"
    # Tidak ada yang berubah: operator itu masih bisa masuk dengan sandi lamanya.
    assert _bisa_masuk(app, "operator@pks.test", SANDI)
    assert store.operator_by_email("operator@pks.test")["role"] == "operator"
    assert store.operator_by_email("budi@pks.test") is None


def test_akun_baru_dari_layar_bisa_langsung_dipakai_masuk(app):
    support = _masuk(app, "support@pks.test")

    res = support.post("/api/console/dev/akun", json=_BARU)

    assert res.status_code == 201, res.text
    assert res.json() == {"akun": {"email": "budi@pks.test", "role": "operator"}}
    budi = _masuk(app, "budi@pks.test", BARU)
    assert budi.get("/api/console/me").json()["operator"]["role"] == "operator"
    akun = _akun(support)["budi@pks.test"]
    assert (akun["nama"], akun["asal"], akun["keadaan"]) == ("Pak Budi", "lokal", "aktif")
    assert "scrypt$" not in res.text and "password_hash" not in res.text


def test_akun_support_baru_bisa_membuka_menu_support(app):
    support = _masuk(app, "support@pks.test")
    support.post("/api/console/dev/akun", json={**_BARU, "role": "support"})

    budi = _masuk(app, "budi@pks.test", BARU)

    assert budi.get("/api/console/dev/akun").status_code == 200


@pytest.mark.parametrize(
    ("ubah", "status", "kode"),
    [
        ({"email": "support@pks.test"}, 409, "akun_sudah_ada"),
        ({"email": "erp@pks.test"}, 409, "akun_milik_erp"),
        ({"email": "bukan email"}, 400, "akun_email_tidak_sah"),
        ({"nama": "  "}, 400, "akun_nama_kosong"),
        ({"sandi_ulang": "sandi-lain-e2e"}, 400, "akun_sandi_beda"),
        ({"sandi": "pendek", "sandi_ulang": "pendek"}, 400, "sandi_pendek"),
    ],
)
def test_penolakan_tambah_berupa_kode_untuk_layar(app, ubah, status, kode):
    support = _masuk(app, "support@pks.test")

    res = support.post("/api/console/dev/akun", json={**_BARU, **ubah})

    assert res.status_code == status, res.text
    assert res.json()["detail"]["code"] == kode
    # Akun lama tidak tersentuh oleh upaya yang ditolak.
    assert _bisa_masuk(app, "support@pks.test", SANDI)


def test_ganti_sandi_memutus_sesi_yang_sedang_dipakai(app):
    operator = _masuk(app, "operator@pks.test")
    support = _masuk(app, "support@pks.test")

    res = support.post("/api/console/dev/akun/sandi", json={
        "email": "operator@pks.test", "sandi": BARU, "sandi_ulang": BARU,
    })

    assert res.status_code == 200, res.text
    assert operator.get("/api/console/me").status_code == 401
    assert not _bisa_masuk(app, "operator@pks.test", SANDI)
    assert _bisa_masuk(app, "operator@pks.test", BARU)


def test_matikan_memutus_sesi_lalu_aktifkan_membuka_lagi(app):
    operator = _masuk(app, "operator@pks.test")
    support = _masuk(app, "support@pks.test")

    mati = support.post("/api/console/dev/akun/status",
                        json={"email": "operator@pks.test", "aktif": False})

    assert (mati.status_code, mati.json()) == (200, {"status": "off"})
    assert operator.get("/api/console/me").status_code == 401
    assert not _bisa_masuk(app, "operator@pks.test", SANDI)
    assert _akun(support)["operator@pks.test"]["keadaan"] == "mati"

    hidup = support.post("/api/console/dev/akun/status",
                         json={"email": "operator@pks.test", "aktif": True})

    assert (hidup.status_code, hidup.json()) == (200, {"status": "active"})
    assert _bisa_masuk(app, "operator@pks.test", SANDI)


def test_ubah_role_berlaku_di_klik_berikutnya_tanpa_login_ulang(app):
    operator = _masuk(app, "operator@pks.test")
    support = _masuk(app, "support@pks.test")
    assert operator.get("/api/console/dev/akun").status_code == 403

    res = support.post("/api/console/dev/akun/role",
                       json={"email": "operator@pks.test", "role": "support"})

    assert (res.status_code, res.json()) == (200, {"role": "support"})
    assert operator.get("/api/console/dev/akun").status_code == 200


@pytest.mark.parametrize(
    ("path", "isi"),
    [
        ("/api/console/dev/akun/status", {"email": "support@pks.test", "aktif": False}),
        ("/api/console/dev/akun/role", {"email": "support@pks.test", "role": "operator"}),
    ],
)
def test_tidak_bisa_mematikan_atau_menurunkan_akun_sendiri(app, path, isi):
    support = _masuk(app, "support@pks.test")

    res = support.post(path, json=isi)

    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "akun_diri_sendiri"
    assert support.get("/api/console/dev/akun").status_code == 200


@pytest.mark.parametrize(
    ("path", "isi"),
    [
        ("/api/console/dev/akun/sandi", {"sandi": BARU, "sandi_ulang": BARU}),
        ("/api/console/dev/akun/status", {"aktif": False}),
        ("/api/console/dev/akun/role", {"role": "support"}),
    ],
)
def test_akun_autoerp_dan_akun_yang_tidak_ada_ditolak(app, store, path, isi):
    support = _masuk(app, "support@pks.test")

    erp = support.post(path, json={"email": "erp@pks.test", **isi})
    hilang = support.post(path, json={"email": "siapa@pks.test", **isi})

    assert (erp.status_code, erp.json()["detail"]["code"]) == (409, "akun_milik_erp")
    assert (hilang.status_code, hilang.json()["detail"]["code"]) == (404, "akun_tidak_ada")
    row = store.operator_by_email("erp@pks.test")
    assert (row["password_hash"], row["status"], row["role"]) == (ERP_HASH, "active", "operator")


def test_status_harus_benar_salah_bukan_teks_bebas(app, store):
    """`bool("false")` bernilai True di Python. Nilai yang tidak jelas ditolak,
    bukan ditebak jadi 'aktifkan'."""
    support = _masuk(app, "support@pks.test")

    res = support.post("/api/console/dev/akun/status",
                       json={"email": "operator@pks.test", "aktif": "mungkin"})

    assert res.status_code == 422
    assert store.operator_by_email("operator@pks.test")["status"] == "active"
