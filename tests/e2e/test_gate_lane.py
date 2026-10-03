"""End-to-end: scan 1 dan scan 4 lewat HTTP sungguhan, di belakang sesi operator."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.plate import truck_id_for
from palmgrade.domain.working_day import work_date_for
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
ANEH = "TNI 1234-00"  # registered, but not plate-shaped (Q2)


@pytest.fixture
def klien(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual({"email": EMAIL, "full_name": "Operator Gerbang", "password_hash": hash_password(SANDI)})
    store.upsert_truck({"id": truck_id_for(PLAT), "plate_number": PLAT, "status": "active"})
    store.upsert_truck({"id": truck_id_for(ANEH), "plate_number": ANEH, "status": "active"})
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


def _jam(dt):
    return dt.isoformat().replace("+00:00", "Z")


def test_empat_scan_satu_kunjungan(klien):
    """Jam relatif ke sekarang: daftar "Menunggu timbang" memakai jendela klaim dari jam
    server (Q3), jadi tanggal yang ditulis mati akan selalu di luar jendela."""
    _masuk(klien)
    t0 = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=3)
    datang, masuk, kosong, pergi = (_jam(t0 + timedelta(minutes=m)) for m in (0, 30, 90, 100))
    hari = work_date_for(masuk, ZoneInfo("Asia/Jakarta"))

    r = klien.post("/api/console/arrivals", json={"qr": PLAT, "at": datang})
    assert r.status_code == 200 and r.json()["hasil"] == "tercatat"
    antre = klien.get("/api/console/weighings", params={"work_date": hari}).json()
    assert [a["plate_number"] for a in antre["waiting"]] == [PLAT]
    # Yang menunggu itu selalu "sekarang", hari apa pun yang sedang dibuka tabelnya.
    lama = klien.get("/api/console/weighings", params={"work_date": "2020-01-01"}).json()
    assert [a["plate_number"] for a in lama["waiting"]] == [PLAT]

    klien.post("/api/console/weighings", json={"plate_number": PLAT, "gross_kg": "14000", "entered_at": masuk})
    klien.post("/api/console/weighings", json={"plate_number": PLAT, "entered_at": masuk,
                                               "tare_kg": "6000", "exited_at": kosong})
    assert klien.post("/api/console/departures", json={"qr": PLAT, "at": pergi}).json()["hasil"] == "tercatat"

    data = klien.get("/api/console/weighings", params={"work_date": hari}).json()
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


def test_truk_terdaftar_berplat_menyimpang_catat_datang_dari_dropdown(klien):
    """Dropdown "Catat datang" mengirim plat truk terdaftar; bentuknya menyimpang tapi
    trucknya dikenal, jadi dicatat, bukan "Yang di-scan bukan nomor polisi"."""
    _masuk(klien)
    jam = _jam(datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=5))
    r = klien.post("/api/console/arrivals", json={"qr": ANEH, "at": jam})
    assert r.status_code == 200, r.text
    assert (r.json()["hasil"], r.json()["plate_number"]) == ("tercatat", ANEH)
    assert [a["plate_number"] for a in klien.get("/api/console/weighings").json()["waiting"]] == [ANEH]
    r = klien.post("/api/console/arrivals", json={"qr": "TNI 9999-00"})
    assert r.status_code == 400 and _kode(r) == "bukan_plat"


def test_tombol_baris_keluar_lewat_weighing_id(klien):
    _masuk(klien)
    klien.post("/api/console/weighings", json={"plate_number": PLAT, "gross_kg": "14000", "entered_at": "2026-09-30T01:00:00Z"})
    row = klien.post("/api/console/weighings", json={"plate_number": PLAT, "entered_at": "2026-09-30T01:00:00Z",
                                                     "tare_kg": "6000", "exited_at": "2026-09-30T02:00:00Z"}).json()
    r = klien.post("/api/console/departures", json={"weighing_id": row["id"], "at": "2026-09-30T02:10:00Z"})
    assert r.status_code == 200
    assert r.json() == {"hasil": "tercatat", "plate_number": PLAT, "weighing_id": row["id"],
                        "left_at": "2026-09-30T02:10:00Z"}


def test_tabel_lewat_rute_terbaru_dulu_menurut_waktu_nyata(klien):
    """The browser writes `Z`, the seeder `+07:00`: the route orders by the real instant."""
    _masuk(klien)
    for plat, jam in (("BE 1 AA", "2026-09-30T08:00:00+07:00"),  # 01:00 UTC
                      ("BE 2 BB", "2026-09-30T01:30:00.000Z"),
                      ("BE 3 CC", "2026-09-30T08:45:00+07:00")):  # 01:45 UTC
        r = klien.post("/api/console/weighings", json={"plate_number": plat, "gross_kg": "14000", "entered_at": jam})
        assert r.status_code == 201, r.text
    data = klien.get("/api/console/weighings", params={"work_date": "2026-09-30"}).json()
    assert [w["plate_number"] for w in data["items"]] == ["BE 3 CC", "BE 2 BB", "BE 1 AA"]


def test_tahap_tiap_langkah_lewat_rute(klien):
    """The Status badge's value comes from the route at every step: datang (in `waiting`),
    bongkar, timbang_kosong, selesai."""
    _masuk(klien)
    t0 = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=3)
    datang, masuk, kosong, pergi = (_jam(t0 + timedelta(minutes=m)) for m in (0, 30, 90, 100))
    hari = work_date_for(masuk, ZoneInfo("Asia/Jakarta"))

    def _lihat():
        data = klien.get("/api/console/weighings", params={"work_date": hari}).json()
        return [w["tahap"] for w in data["items"]], [a["tahap"] for a in data["waiting"]]

    klien.post("/api/console/arrivals", json={"qr": PLAT, "at": datang})
    assert _lihat() == ([], ["datang"])
    klien.post("/api/console/weighings", json={"plate_number": PLAT, "gross_kg": "14000", "entered_at": masuk})
    assert _lihat() == (["bongkar"], [])
    klien.post("/api/console/weighings", json={"plate_number": PLAT, "entered_at": masuk,
                                               "tare_kg": "6000", "exited_at": kosong})
    assert _lihat() == (["timbang_kosong"], [])
    assert klien.post("/api/console/departures", json={"qr": PLAT, "at": pergi}).json()["hasil"] == "tercatat"
    assert _lihat() == (["selesai"], [])


# ── Batal datang and "tanpa scan 4" (user 2026-10-03) ────────────────────────


def test_batal_datang_tertutup_tanpa_sesi(klien):
    assert klien.post("/api/console/arrivals/apa-saja/cancel").status_code == 401


def test_batal_datang_lewat_rute(klien):
    _masuk(klien)
    datang = _jam(datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=10))
    klien.post("/api/console/arrivals", json={"qr": PLAT, "at": datang})
    [a] = klien.get("/api/console/weighings").json()["waiting"]
    assert set(a) >= {"id", "plate_number", "arrived_at", "menit", "tahap"}

    r = klien.post(f"/api/console/arrivals/{a['id']}/cancel")
    assert r.status_code == 200 and r.json() == {"hasil": "dibatalkan", "plate_number": PLAT}
    assert klien.get("/api/console/weighings").json()["waiting"] == []
    # A second press and an unknown id are answers, not errors.
    assert klien.post(f"/api/console/arrivals/{a['id']}/cancel").json() == {"hasil": "tidak_ada"}
    assert klien.post("/api/console/arrivals/tidak-dikenal/cancel").json() == {"hasil": "tidak_ada"}


def test_tabel_membawa_tanpa_scan_4(klien):
    """A visit weighed out more than 24 h ago that never got its Keluar: SELESAI, flagged,
    total to the weigh-out, and its row button closes nothing."""
    _masuk(klien)
    t0 = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=26)
    datang, masuk, kosong = (_jam(t0 + timedelta(minutes=m)) for m in (0, 30, 90))
    hari = work_date_for(masuk, ZoneInfo("Asia/Jakarta"))
    klien.post("/api/console/arrivals", json={"qr": PLAT, "at": datang})
    klien.post("/api/console/weighings", json={"plate_number": PLAT, "gross_kg": "14000", "entered_at": masuk})
    klien.post("/api/console/weighings", json={"plate_number": PLAT, "entered_at": masuk,
                                               "tare_kg": "6000", "exited_at": kosong})

    [tiket] = klien.get("/api/console/weighings", params={"work_date": hari}).json()["items"]
    assert (tiket["tahap"], tiket["tanpa_scan_4"], tiket["total_menit"], tiket["left_at"]) == (
        "selesai", True, 90, None)
    r = klien.post("/api/console/departures", json={"weighing_id": tiket["id"], "at": _jam(datetime.now(UTC))})
    assert r.json()["hasil"] == "sudah_keluar"
