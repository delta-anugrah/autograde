"""End-to-end: scan 1 dan scan 4 lewat HTTP sungguhan, di belakang sesi operator."""
from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.plate import truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service, get_gate_service
from palmgrade.routes.console import router as console_router
from palmgrade.routes.console_deps import pasang_penangan_validasi
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.gate_service import GateService

EMAIL = "gerbang@pks.test"
SANDI = "timbangan2026"
PLAT = "BE 4412 OFL"


@pytest.fixture
def klien(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual({"email": EMAIL, "full_name": "Operator Gerbang", "password_hash": hash_password(SANDI)})
    store.upsert_truck({"id": truck_id_for(PLAT), "plate_number": PLAT, "status": "active"})
    service = ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), store, None)
    app = FastAPI()
    app.include_router(console_router)
    pasang_penangan_validasi(app)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_gate_service] = lambda: GateService(store, service.tz)
    return TestClient(app)


def _masuk(client):
    assert client.post("/api/console/login", json={"email": EMAIL, "sandi": SANDI}).status_code == 200


def test_jalur_gerbang_tertutup_tanpa_sesi(klien):
    for jalur in ("/api/console/arrivals", "/api/console/departures"):
        assert klien.post(jalur, json={"qr": PLAT}).status_code == 401


def test_empat_scan_satu_kunjungan(klien):
    _masuk(klien)
    r = klien.post("/api/console/arrivals", json={"qr": PLAT, "at": "2026-09-30T00:30:00Z"})
    assert r.status_code == 200 and r.json()["hasil"] == "tercatat"
    antre = klien.get("/api/console/weighings", params={"work_date": "2026-09-30"}).json()
    assert [a["plate_number"] for a in antre["waiting"]] == [PLAT]

    klien.post("/api/console/weighings", json={"plate_number": PLAT, "gross_kg": "14000", "entered_at": "2026-09-30T01:00:00Z"})
    klien.post("/api/console/weighings", json={"plate_number": PLAT, "entered_at": "2026-09-30T01:00:00Z",
                                               "tare_kg": "6000", "exited_at": "2026-09-30T02:00:00Z"})
    assert klien.post("/api/console/departures", json={"qr": PLAT, "at": "2026-09-30T02:10:00Z"}).json()["hasil"] == "tercatat"

    data = klien.get("/api/console/weighings", params={"work_date": "2026-09-30"}).json()
    [tiket] = data["items"]
    assert (tiket["antre_menit"], tiket["total_menit"], tiket["tanpa_scan_1"]) == (30, 100, False)
    assert data["waiting"] == []


def test_keluar_sebelum_timbang_kosong_200_dengan_peringatan(klien):
    _masuk(klien)
    klien.post("/api/console/weighings", json={"plate_number": PLAT, "gross_kg": "14000", "entered_at": "2026-09-30T01:00:00Z"})
    r = klien.post("/api/console/departures", json={"qr": PLAT, "at": "2026-09-30T01:30:00Z"})
    assert r.status_code == 200 and r.json()["hasil"] == "belum_timbang_kosong"


def test_bukan_plat_jam_ngawur_dan_bentuk_salah_400(klien):
    _masuk(klien)
    assert klien.post("/api/console/arrivals", json={"qr": "https://promo.example"}).status_code == 400
    assert klien.post("/api/console/arrivals", json={"qr": PLAT, "at": "besok"}).status_code == 400
    assert klien.post("/api/console/arrivals", json={"qr": 123}).status_code == 400
    assert klien.post("/api/console/departures", json={"qr": "https://promo.example"}).status_code == 400


def _kode(r):
    body = r.json()
    return body.get("code") or (body.get("detail") or {}).get("code") if isinstance(body, dict) else None


def test_jam_ngawur_dijawab_input_tidak_sah_bukan_500(klien):
    _masuk(klien)
    for jam in ("besok", "0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59-23:59", "2026-09-30T00:30:00+99:00"):
        for jalur, badan in (("arrivals", {"qr": PLAT}), ("departures", {"qr": PLAT})):
            r = klien.post(f"/api/console/{jalur}", json={**badan, "at": jam})
            assert r.status_code == 400, (jalur, jam, r.text)
            assert _kode(r) == "input_tidak_sah", (jalur, jam, r.text)
    r = klien.post("/api/console/departures", json={"weighing_id": "w-x", "at": "besok"})
    assert r.status_code == 400 and _kode(r) == "input_tidak_sah"


def test_bukan_plat_dijawab_kode_operator(klien):
    _masuk(klien)
    r = klien.post("/api/console/arrivals", json={"qr": "https://promo.example"})
    assert r.status_code == 400 and _kode(r) == "bukan_plat"
    r = klien.post("/api/console/departures", json={"qr": "https://promo.example"})
    assert r.status_code == 400 and _kode(r) == "bukan_plat"
    r = klien.post("/api/console/arrivals", json={})
    assert r.status_code == 400 and _kode(r) == "plat_kosong"


def test_tombol_baris_keluar_lewat_weighing_id(klien):
    _masuk(klien)
    klien.post("/api/console/weighings", json={"plate_number": PLAT, "gross_kg": "14000", "entered_at": "2026-09-30T01:00:00Z"})
    row = klien.post("/api/console/weighings", json={"plate_number": PLAT, "entered_at": "2026-09-30T01:00:00Z",
                                                     "tare_kg": "6000", "exited_at": "2026-09-30T02:00:00Z"}).json()
    r = klien.post("/api/console/departures", json={"weighing_id": row["id"], "at": "2026-09-30T02:10:00Z"})
    assert r.status_code == 200
    assert r.json() == {"hasil": "tercatat", "plate_number": PLAT, "weighing_id": row["id"],
                        "left_at": "2026-09-30T02:10:00Z"}
