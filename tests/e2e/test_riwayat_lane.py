"""End-to-end tab Riwayat lewat HTTP dengan login sungguhan.

- Butuh sesi (401 tanpa cookie), tapi BUKAN lane support: operator biasa yang
  membaca riwayat grading, sama dengan tab Grading dan Rekap.
- Filter yang salah dijawab 400 dengan kode yang diterjemahkan layar; tampilan
  atau hasil yang tidak dikenal 422.
- CSV terunduh sebagai lampiran dengan nama berkas dan BOM.

Rute dirakit lewat dependency graph asli dengan dependensi di-override, bukan
`create_console_app()` yang menyentuh `state/*.db` milik developer.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.domain.operator_auth import hash_password
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.riwayat_repository import RiwayatStore
from palmgrade.routes.console import get_auth_service, get_console_service, get_riwayat_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.riwayat_service import RiwayatService

SANDI = "sandi-e2e-riwayat"


class _StubConsole:
    def __init__(self, store: ConsoleStore) -> None:
        self.store = store


@pytest.fixture
def app(tmp_path):
    db = tmp_path / "console.db"
    store = ConsoleStore(db)
    aplikasi = FastAPI()
    aplikasi.include_router(console_router)
    aplikasi.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    aplikasi.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    aplikasi.dependency_overrides[get_riwayat_service] = lambda: RiwayatService(
        RiwayatStore(db), hari_ini=lambda: "2026-09-26", zona="Asia/Jakarta"
    )
    store.upsert_operator_manual(
        {"email": "operator@pks.test", "full_name": "Operator", "password_hash": hash_password(SANDI)}
    )
    for i, (tgl, kelas, status) in enumerate(
        [("2026-09-24", "Ripe", "ACC"), ("2026-09-24", "JK", "REJ"), ("2026-09-25", "Ripe", "ACC")]
    ):
        store.add_inspection({
            "event_id": f"e{i}", "machine_id": "m-1", "line_code": "line-1", "work_date": tgl,
            "timestamp": f"{tgl}T08:0{i}:00+07:00", "ripeness_status": status,
            "ripeness_confidence": 0.9, "capture_type": "auto",
            "image_path": f"captures/results/{tgl}/e{i}.webp", "truck_id": None,
            "assignment_id": "a-1", "prediction": "Acc" if status == "ACC" else "Rej",
            "grade_class": kelas, "tp_status": None, "tp_confidence": None,
        })
    return aplikasi


def _masuk(aplikasi) -> TestClient:
    client = TestClient(aplikasi)
    res = client.post("/api/console/login", json={"email": "operator@pks.test", "sandi": SANDI})
    assert res.status_code == 200, res.text
    return client


def test_butuh_sesi(app):
    assert TestClient(app).get("/api/console/riwayat").status_code == 401
    assert TestClient(app).get("/api/console/riwayat/csv").status_code == 401


def test_operator_biasa_bisa_membaca_riwayat_bawaan_tujuh_hari(app):
    res = _masuk(app).get("/api/console/riwayat")

    assert res.status_code == 200, res.text
    isi = res.json()
    assert (isi["dari"], isi["sampai"], isi["hari_ini"], isi["tampilan"]) == (
        "2026-09-20", "2026-09-26", "2026-09-26", "hari")
    assert [h["work_date"] for h in isi["items"]] == ["2026-09-25", "2026-09-24"]
    assert isi["ringkasan"]["total"] == 3 and isi["ringkasan"]["jk"] == 1


def test_pindah_halaman_tanpa_ringkasan(app):
    res = _masuk(app).get(
        "/api/console/riwayat",
        params={"tampilan": "janjang", "limit": 2, "offset": 2, "ringkasan": "false"},
    )

    isi = res.json()
    assert "ringkasan" not in isi
    assert (isi["total"], [j["event_id"] for j in isi["items"]]) == (3, ["e0"])


def test_saringan_hasil_di_tampilan_janjang(app):
    isi = _masuk(app).get(
        "/api/console/riwayat", params={"tampilan": "janjang", "hasil": "jk"}
    ).json()

    assert [j["event_id"] for j in isi["items"]] == ["e1"]
    assert isi["items"][0]["image_url"] == "/captures/line-1/results/2026-09-24/e1.webp"


@pytest.mark.parametrize(
    ("params", "kode"),
    [
        ({"dari": "24-09-2026"}, "riwayat_tanggal_tidak_sah"),
        ({"dari": "2026-09-25", "sampai": "2026-09-01"}, "riwayat_rentang_terbalik"),
        ({"dari": "2026-07-01", "sampai": "2026-09-01"}, "riwayat_rentang_panjang"),
    ],
)
def test_filter_salah_dijawab_kode_untuk_layar(app, params, kode):
    client = _masuk(app)

    for path in ("/api/console/riwayat", "/api/console/riwayat/csv"):
        res = client.get(path, params=params)
        assert res.status_code == 400, (path, res.text)
        assert res.json()["detail"]["code"] == kode


@pytest.mark.parametrize("params", [{"tampilan": "bulan"}, {"hasil": "busuk"}, {"bahasa": "fr"}])
def test_pilihan_yang_tidak_dikenal_422(app, params):
    path = "/api/console/riwayat/csv" if "bahasa" in params else "/api/console/riwayat"

    assert _masuk(app).get(path, params=params).status_code == 422


def test_csv_terunduh_sebagai_lampiran(app):
    res = _masuk(app).get(
        "/api/console/riwayat/csv", params={"tampilan": "janjang", "bahasa": "en"}
    )

    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/csv")
    assert res.headers["content-disposition"] == (
        'attachment; filename="riwayat-grading-janjang-2026-09-20_2026-09-26.csv"'
    )
    assert res.content.startswith("﻿".encode())
    baris = res.content.decode("utf-8-sig").strip().split("\r\n")
    assert baris[0].startswith("Work date,Time,Line")
    assert len(baris) == 1 + 3
