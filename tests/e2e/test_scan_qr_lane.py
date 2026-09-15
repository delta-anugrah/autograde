"""End-to-end: `POST /api/console/scan` on a real console app, over real HTTP.

The unit tests call `ScanService` directly and the route tests use a stub console.
What neither covers is the wiring: the dependency that hands the scan service the
same store the rest of the console uses, the session gate in front of the lane, and
the status codes a scanner at the gate actually receives.

Assembled here rather than through `create_console_app()`, which would reach for the
developer's own `state/console.db` and leave test rows in it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.operator_error import BELUM_MASUK, PLAT_KOSONG
from palmgrade.domain.plate import truck_id_for
from palmgrade.domain.qr import isi_qr_untuk
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service, get_scan_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.scan_service import ScanService

EMAIL = "gerbang@pks.test"
SANDI = "timbangan2026"
PLAT = "BE 4412 OFL"


class _StubConsole:
    """The scan lane touches none of the console service; only the store is shared."""

    def __init__(self, store: ConsoleStore) -> None:
        self.store = store


@pytest.fixture
def gerbang(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_lokal(
        {"email": EMAIL, "nama": "Operator Gerbang", "password_hash": hash_password(SANDI)}
    )
    store.upsert_truck(
        {
            "id": truck_id_for(PLAT),
            "plate_number": PLAT,
            "status": "active",
            "erp_name": "TRK-0001",
        }
    )

    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_scan_service] = lambda: ScanService(store)
    return TestClient(app), store


def _masuk(client: TestClient) -> None:
    assert client.post(
        "/api/console/login", json={"email": EMAIL, "sandi": SANDI}
    ).status_code == 200


def test_lane_scan_tertutup_tanpa_sesi(gerbang):
    client, _ = gerbang

    jawab = client.post("/api/console/scan", json={"qr": "BE4412OFL"})

    assert jawab.status_code == 401
    assert jawab.json()["detail"]["code"] == BELUM_MASUK


def test_qr_yang_dicetak_terbaca_kembali(gerbang):
    """Lingkaran penuh: yang dicetak `isi_qr_untuk` harus dikenali lane scan. Kalau
    dua sisi ini memakai aturan normalisasi berbeda, QR yang kita cetak sendiri tidak
    terbaca — dan itu baru ketahuan di gerbang pabrik."""
    client, _ = gerbang
    _masuk(client)

    jawab = client.post("/api/console/scan", json={"qr": isi_qr_untuk(PLAT)})

    assert jawab.status_code == 200
    assert jawab.json()["ditemukan"] is True
    assert jawab.json()["truck"]["erp_name"] == "TRK-0001"


def test_tiga_gaya_tulisan_satu_truk(gerbang):
    """Plat ditulis berbeda oleh operator, program timbangan, dan ERP."""
    client, _ = gerbang
    _masuk(client)

    id_truk = {
        client.post("/api/console/scan", json={"qr": q}).json()["truck"]["id"]
        for q in ("BE4412OFL", "be-4412-ofl", "BE 4412 OFL")
    }

    assert len(id_truk) == 1, "satu truk fisik terbaca sebagai beberapa truk"


def test_truk_pinjaman_dijawab_200_bukan_404(gerbang):
    """404 di layar terbaca seperti kerusakan. Truk pinjaman itu kasus normal, dan
    jawabannya harus membuat layar menawarkan input manual."""
    client, _ = gerbang
    _masuk(client)

    jawab = client.post("/api/console/scan", json={"qr": "BE9999XYZ"})

    assert jawab.status_code == 200
    assert jawab.json() == {
        "ditemukan": False,
        "plate_number": "BE9999XYZ",
        "truck": None,
    }


def test_scan_berkali_kali_tidak_menambah_truk(gerbang):
    """Pagar utamanya: satu QR salah baca tidak boleh menambah truk hantu ke master
    data, karena truk itu naik ke AutoERP lewat interface B."""
    client, store = gerbang
    _masuk(client)
    sebelum = len(store.trucks_semua())

    for q in ("BE9999XYZ", "BE1111AAA", "BE9999XYZ"):
        client.post("/api/console/scan", json={"qr": q})

    assert len(store.trucks_semua()) == sebelum


def test_scan_tidak_menulis_timbangan(gerbang):
    """Yang mencatat berat cuma `catat_timbangan`. Dua penulis untuk angka yang
    dibayar adalah cara paling rapi untuk salah bayar berbulan-bulan."""
    client, store = gerbang
    _masuk(client)

    client.post("/api/console/scan", json={"qr": "BE4412OFL"})

    assert store.weighings("2026-09-15") == []


@pytest.mark.parametrize(
    "sampah", ["https://contoh.id/promo", "TRK-0001", "", "   ", "!!!", "1234"]
)
def test_yang_bukan_plat_ditolak_400(gerbang, sampah):
    """Apa pun bisa masuk ke scanner: struk parkir, QR promo, id ERP, bacaan gagal."""
    client, _ = gerbang
    _masuk(client)

    jawab = client.post("/api/console/scan", json={"qr": sampah})

    assert jawab.status_code == 400
    assert jawab.json()["detail"]["code"] == PLAT_KOSONG


# ── cetak QR (lane gambar) ───────────────────────────────────────────────────


def test_gambar_qr_butuh_sesi():
    """Plat truk itu data operasional pabrik. Lane gambarnya ikut di belakang gerbang
    seperti lane operator lain."""
    # App tanpa sesi: fixture `gerbang` sudah sign-in, jadi dirakit sendiri di sini.
    store = ConsoleStore(Path(tempfile.mkdtemp()) / "console.db")
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_scan_service] = lambda: ScanService(store)

    jawab = TestClient(app).get(f"/api/console/trucks/{PLAT}/qr.png")

    assert jawab.status_code == 401


def test_gambar_qr_dikirim_sebagai_png(gerbang):
    client, _ = gerbang
    _masuk(client)

    jawab = client.get(f"/api/console/trucks/{PLAT}/qr.png")

    assert jawab.status_code == 200
    assert jawab.headers["content-type"] == "image/png"
    assert jawab.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_gambar_qr_berisi_plat_yang_diminta(gerbang):
    """Dibuktikan lewat pola QR-nya: pola untuk satu isi bersifat tetap, jadi sama
    dengan pola `BE4412OFL` berarti isinya memang itu."""
    import segno

    from palmgrade.services.qr_cetak import KOREKSI, png_qr

    client, _ = gerbang
    _masuk(client)

    jawab = client.get(f"/api/console/trucks/{PLAT}/qr.png")

    assert jawab.content == png_qr(PLAT)
    # Dan pola itu memang pola platnya, bukan kebetulan dua fungsi yang sama-sama salah.
    assert segno.make("BE4412OFL", error=KOREKSI).matrix is not None


def test_plat_gaya_apa_pun_menghasilkan_qr_yang_sama(gerbang):
    """Satu truk = satu QR. Kalau tidak, dua kartu tercetak untuk satu truk dan
    salah satunya nanti tidak cocok dengan barisnya."""
    client, _ = gerbang
    _masuk(client)

    isi = {
        client.get(f"/api/console/trucks/{p}/qr.png").content
        for p in ("BE4412OFL", "be-4412-ofl", "BE 4412 OFL")
    }

    assert len(isi) == 1


def test_plat_yang_bukan_plat_ditolak_400(gerbang):
    """Isi QR datang dari baris truk, dan baris itu bisa salah isi. Kartu yang isinya
    bukan plat tidak akan pernah bisa di-scan."""
    client, _ = gerbang
    _masuk(client)

    jawab = client.get("/api/console/trucks/bukan-plat-1234567/qr.png")

    assert jawab.status_code == 400
    assert jawab.json()["detail"]["code"] == PLAT_KOSONG


def test_gambar_qr_truk_yang_belum_terdaftar_tetap_dibuat(gerbang):
    """Kartu dicetak DULU, truknya didaftarkan kemudian — itu urutan yang wajar untuk
    truk baru. Menolak di sini memaksa backoffice mendaftarkan dulu sebelum bisa
    mencetak, padahal QR-nya cuma berisi plat."""
    client, _ = gerbang
    _masuk(client)

    jawab = client.get("/api/console/trucks/BE9999XYZ/qr.png")

    assert jawab.status_code == 200
    assert jawab.content.startswith(b"\x89PNG\r\n\x1a\n")
