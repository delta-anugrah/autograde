"""End-to-end impor grading lewat HTTP dengan login sungguhan (support saja).

- Operator biasa ditolak 403 di keempat rute; tanpa sesi 401. Unduh CSV tetap untuk
  semua operator (tab Riwayat), impor cuma support (keputusan user 2026-09-27).
- Berkas dikirim apa adanya sebagai badan permintaan (tanpa multipart): periksa,
  impor dengan sidik yang sama, janjangnya terbaca di tab Riwayat, lalu dibatalkan.
- Berkas terlalu besar ditolak 413 sebelum dibaca utuh.

App-nya dirakit sendiri dengan dependensi di-override, bukan `create_console_app()`
yang menyentuh `state/console.db` milik developer.
"""
from __future__ import annotations

import csv
import io
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain import impor_grading
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.riwayat import KEPALA_CSV
from palmgrade.domain.role import ROLE_OPERATOR, ROLE_SUPPORT
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.riwayat_repository import RiwayatStore
from palmgrade.routes.console import (
    get_auth_service,
    get_console_service,
    get_impor_grading_service,
    get_riwayat_service,
)
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.impor_grading_service import ImporGradingService
from palmgrade.services.riwayat_service import RiwayatService

SANDI = "sandi-e2e-impor"
HARI_INI = "2026-09-27"
RUTE = (
    ("post", "/api/console/dev/riwayat/impor/periksa"),
    ("post", "/api/console/dev/riwayat/impor"),
    ("get", "/api/console/dev/riwayat/impor"),
    ("post", "/api/console/dev/riwayat/impor/b1/batal"),
)


class _LineDiam:
    async def status(self, line):
        raise AssertionError("tidak dipanggil")


def _csv(n: int = 2, *, tampilan: str = "janjang") -> bytes:
    buffer = io.StringIO()
    penulis = csv.writer(buffer, lineterminator="\r\n")
    penulis.writerow(KEPALA_CSV[tampilan]["id"])
    if tampilan == "janjang":
        for i in range(n):
            penulis.writerow([
                "2026-09-24", f"2026-09-24 08:00:{i:02d}", "line-1", "BE 1234 AB", "CV Maju", "Eksternal",
                "Ripe", "ACC", "", "otomatis", "", f"00000000-0000-5000-8000-{i:012d}",
            ])
    return ("﻿" + buffer.getvalue()).encode()


@pytest.fixture
def rakitan(tmp_path):
    settings = replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta")
    store = ConsoleStore(tmp_path / "console.db")
    for email, role in (("operator@pks.test", ROLE_OPERATOR), ("support@pks.test", ROLE_SUPPORT)):
        store.upsert_operator_manual(
            {"email": email, "nama": email.split("@")[0], "password_hash": hash_password(SANDI), "role": role}
        )
    service = ConsoleService(settings, store, _LineDiam())
    impor = ImporGradingService(store, lines=service.lines, zona="Asia/Jakarta", hari_ini=lambda: HARI_INI,
                                id_baru=lambda: "b1")
    riwayat = RiwayatService(RiwayatStore(tmp_path / "console.db"), hari_ini=lambda: HARI_INI,
                             zona="Asia/Jakarta")
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_impor_grading_service] = lambda: impor
    app.dependency_overrides[get_riwayat_service] = lambda: riwayat
    return app


def _klien(app: FastAPI, email: str | None) -> TestClient:
    klien = TestClient(app)
    if email:
        res = klien.post("/api/console/login", json={"email": email, "sandi": SANDI})
        assert res.status_code == 200, res.text
    return klien


def test_tanpa_sesi_401_dan_operator_biasa_403_di_semua_rute_impor(rakitan):
    tamu, operator = _klien(rakitan, None), _klien(rakitan, "operator@pks.test")

    for metode, jalur in RUTE:
        assert getattr(tamu, metode)(jalur).status_code == 401, jalur
        res = getattr(operator, metode)(jalur)
        assert (res.status_code, res.json()["detail"]["code"]) == (403, "bukan_support"), jalur


def test_operator_biasa_tetap_boleh_unduh_csv(rakitan):
    res = _klien(rakitan, "operator@pks.test").get(
        "/api/console/riwayat/csv", params={"tampilan": "janjang", "dari": "2026-09-24", "sampai": "2026-09-24"}
    )
    assert res.status_code == 200


def test_periksa_impor_terbaca_di_riwayat_lalu_dibatalkan(rakitan):
    support = _klien(rakitan, "support@pks.test")
    isi = _csv(2)
    kepala = {"content-type": "text/csv"}
    rentang = {"tampilan": "janjang", "dari": "2026-09-24", "sampai": "2026-09-24"}

    periksa = support.post("/api/console/dev/riwayat/impor/periksa", params={"nama": "riwayat.csv"},
                           content=isi, headers=kepala).json()
    impor = support.post("/api/console/dev/riwayat/impor",
                         params={"nama": "riwayat.csv", "sidik": periksa["sidik"]}, content=isi, headers=kepala)
    di_riwayat = support.get("/api/console/riwayat", params=rentang).json()["items"]
    daftar = support.get("/api/console/dev/riwayat/impor").json()["items"]
    batal = support.post("/api/console/dev/riwayat/impor/b1/batal")
    sesudah = support.get("/api/console/riwayat", params=rentang).json()["items"]

    assert (periksa["baru"], periksa["bisa_impor"]) == (2, True)
    assert impor.status_code == 201, impor.text
    assert impor.json()["batch"]["added"] == 2
    assert [r["import_batch"] for r in di_riwayat] == ["b1", "b1"]
    assert [(b["id"], b["imported_by"]) for b in daftar] == [("b1", "support@pks.test")]
    assert (batal.status_code, batal.json()["batch"]["status"]) == (200, "undone")
    assert sesudah == []


def test_berkas_ringkasan_ditolak_400_dengan_jenisnya(rakitan):
    res = _klien(rakitan, "support@pks.test").post(
        "/api/console/dev/riwayat/impor/periksa", content=_csv(tampilan="hari"), headers={"content-type": "text/csv"}
    )

    assert res.status_code == 400
    assert (res.json()["detail"]["code"], res.json()["detail"]["params"]["jenis"]) == ("impor_bukan_janjang", "hari")


def test_berkas_terlalu_besar_ditolak_413_sebelum_dibaca(rakitan, monkeypatch):
    monkeypatch.setattr(impor_grading, "MAKS_BYTE", 100)

    res = _klien(rakitan, "support@pks.test").post(
        "/api/console/dev/riwayat/impor/periksa", content=_csv(5), headers={"content-type": "text/csv"}
    )

    assert (res.status_code, res.json()["detail"]["code"]) == (413, "impor_terlalu_besar")


def test_sidik_beda_409_dan_batal_yang_tidak_ada_404(rakitan):
    support = _klien(rakitan, "support@pks.test")

    beda = support.post("/api/console/dev/riwayat/impor", params={"sidik": "0" * 64}, content=_csv(1),
                        headers={"content-type": "text/csv"})
    tidak_ada = support.post("/api/console/dev/riwayat/impor/tidak-ada/batal")

    assert (beda.status_code, beda.json()["detail"]["code"]) == (409, "impor_sidik_beda")
    assert (tidak_ada.status_code, tidak_ada.json()["detail"]["code"]) == (404, "impor_tidak_ada")
