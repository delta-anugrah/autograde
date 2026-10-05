"""End-to-end: penugasan line otomatis lewat HTTP sungguhan, di belakang sesi.

Dirakit di sini, bukan lewat `create_console_app()` yang membuka `state/console.db`
milik developer. Antrean yang dimaksud adalah antrean bongkar (truk menunggu line),
bukan antrean line ke konsol di tab Status.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.penugasan_line import KUNCI_PENUGASAN
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.routes.console_deps import pasang_penangan_validasi
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService

SANDI = "sawit2026"
OPERATOR = "op@pks.test"
SUPPORT = "sp@pks.test"


class FakeLine:
    async def assign_truck(self, line, *, assignment_id, truck_id, assigned_at, ffb_source=None, plate=None):
        return None


@pytest.fixture
def konsol(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    for email, role in ((OPERATOR, "operator"), (SUPPORT, "support")):
        store.upsert_operator_manual(
            {"email": email, "full_name": email, "password_hash": hash_password(SANDI), "role": role}
        )
    # Start from "turned off"; a never-saved console starts on (2026-10-05), see the test below.
    store.set_state(KUNCI_PENUGASAN, json.dumps({"aktif": False, "lines": ["line-1", "line-2", "line-3"]}))
    service = ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), store, FakeLine())
    app = FastAPI()
    app.include_router(console_router)
    pasang_penangan_validasi(app)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    return app, service


def _masuk(app, email) -> TestClient:
    client = TestClient(app)
    r = client.post("/api/console/login", json={"email": email, "sandi": SANDI})
    assert r.status_code == 200, r.text
    return client


def _isi(client, plat, menit_lalu=0):
    """Timbang isi dengan jam sekarang (antrean bongkar cuma menampung kunjungan yang baru)."""
    jam = datetime.now(ZoneInfo("Asia/Jakarta")).replace(microsecond=0).isoformat()
    r = client.post("/api/console/weighings", json={"plate_number": plat, "gross_kg": "14000", "entered_at": jam})
    assert r.status_code == 201, r.text
    return r.json()


def test_setelan_cuma_untuk_support(konsol):
    app, _ = konsol
    assert _masuk(app, OPERATOR).get("/api/console/dev/auto-assign").status_code == 403
    r = _masuk(app, SUPPORT).get("/api/console/dev/auto-assign")
    assert r.status_code == 200
    assert r.json()["aktif"] is False
    assert [x["line_code"] for x in r.json()["lines_tersedia"]] == ["line-1", "line-2", "line-3"]


def test_setelan_simpan_ditolak_untuk_operator(konsol):
    app, _ = konsol
    r = _masuk(app, OPERATOR).post("/api/console/dev/auto-assign", json={"aktif": True, "lines": ["line-1"]})
    assert r.status_code == 403


def test_nyalakan_lalu_timbang_isi_memasang_truk(konsol):
    app, _ = konsol
    support = _masuk(app, SUPPORT)
    r = support.post("/api/console/dev/auto-assign", json={"aktif": True, "lines": ["line-1", "line-2"]})
    assert r.status_code == 200 and r.json()["lines"] == ["line-1", "line-2"]
    assert support.get("/api/console/dev/auto-assign").json()["aktif"] is True
    hasil = _isi(_masuk(app, OPERATOR), "BE 1 AA")
    assert [d["line_code"] for d in hasil["dipasang"]] == ["line-1", "line-2"]


def test_simpan_nyala_langsung_memasang_truk_yang_menunggu(konsol):
    """Truk yang sudah menunggu saat support menyalakan saklar naik saat itu juga, tidak
    menunggu timbangan atau Lepas berikutnya; jawabannya bilang ke mana."""
    app, _ = konsol
    _isi(_masuk(app, OPERATOR), "BE 1 AA")
    support = _masuk(app, SUPPORT)
    r = support.post("/api/console/dev/auto-assign", json={"aktif": True, "lines": ["line-1", "line-2"]})
    assert r.status_code == 200, r.text
    assert [(d["line_code"], d["plate_number"]) for d in r.json()["dipasang"]] == [
        ("line-1", "BE 1 AA"), ("line-2", "BE 1 AA"),
    ]
    assert support.get("/api/console/state").json()["antrean_bongkar"] == []


def test_simpan_mati_tidak_memasang_apa_pun(konsol):
    app, _ = konsol
    _isi(_masuk(app, OPERATOR), "BE 1 AA")
    r = _masuk(app, SUPPORT).post("/api/console/dev/auto-assign", json={"aktif": False, "lines": ["line-1"]})
    assert r.status_code == 200 and r.json()["dipasang"] == []


@pytest.mark.parametrize(
    ("body", "kode"),
    [
        ({"aktif": True, "lines": []}, "penugasan_tanpa_line"),
        ({"aktif": True, "lines": ["line-9"]}, "line_tidak_dikenal"),
        ({"aktif": "ya", "lines": ["line-1"]}, "input_tidak_sah"),
        ({"aktif": True, "lines": "line-1"}, "input_tidak_sah"),
    ],
)
def test_setelan_salah_ditolak_400_dengan_kodenya(konsol, body, kode):
    app, _ = konsol
    r = _masuk(app, SUPPORT).post("/api/console/dev/auto-assign", json=body)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == kode


def test_body_kosong_tidak_menabrak(konsol):
    """`aktif` dan `lines` boleh tidak ada (keduanya None): hasilnya mati dan tanpa line."""
    app, _ = konsol
    support = _masuk(app, SUPPORT)
    support.post("/api/console/dev/auto-assign", json={"aktif": True, "lines": ["line-1"]})
    r = support.post("/api/console/dev/auto-assign", json={})
    assert r.status_code == 200
    assert r.json()["aktif"] is False and r.json()["lines"] == []


def test_antrean_terlihat_di_state_lalu_ditugaskan_manual(konsol):
    app, _ = konsol
    op = _masuk(app, OPERATOR)
    _isi(op, "BE 1 AA")
    antrean = op.get("/api/console/state").json()["antrean_bongkar"]
    assert [a["plate_number"] for a in antrean] == ["BE 1 AA"]
    r = op.post(f"/api/console/unloading-queue/{antrean[0]['weighing_id']}/assign")
    assert r.status_code == 200 and len(r.json()["dipasang"]) == 3
    assert op.get("/api/console/state").json()["antrean_bongkar"] == []


def test_tugaskan_tiket_di_luar_antrean_409(konsol):
    app, _ = konsol
    r = _masuk(app, OPERATOR).post("/api/console/unloading-queue/tidak-ada/assign")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "bukan_antrean"


def test_semua_line_terpakai_409(konsol):
    app, _ = konsol
    op = _masuk(app, OPERATOR)
    _isi(op, "BE 1 AA")
    _isi(op, "BE 2 AA")
    antrean = op.get("/api/console/state").json()["antrean_bongkar"]
    assert op.post(f"/api/console/unloading-queue/{antrean[0]['weighing_id']}/assign").status_code == 200
    r = op.post(f"/api/console/unloading-queue/{antrean[1]['weighing_id']}/assign")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "line_semua_terpakai"


def test_lewati_dan_tiket_di_luar_antrean_409(konsol):
    app, _ = konsol
    op = _masuk(app, OPERATOR)
    _isi(op, "BE 1 AA")
    wid = op.get("/api/console/state").json()["antrean_bongkar"][0]["weighing_id"]
    r = op.post(f"/api/console/unloading-queue/{wid}/skip")
    assert r.status_code == 200 and r.json() == {"weighing_id": wid, "dilewati": True}
    assert op.get("/api/console/state").json()["antrean_bongkar"] == []
    ulang = op.post(f"/api/console/unloading-queue/{wid}/skip")
    assert ulang.status_code == 409 and ulang.json()["detail"]["code"] == "bukan_antrean"


def test_lepas_manual_menjawab_dipasang(konsol):
    app, _ = konsol
    op = _masuk(app, OPERATOR)
    r = op.post("/api/console/lines/line-1/release-truck")
    assert r.status_code == 200 and r.json()["dipasang"] == []


def test_lepas_line_tak_dikenal_tetap_404(konsol):
    app, _ = konsol
    assert _masuk(app, OPERATOR).post("/api/console/lines/line-9/release-truck").status_code == 404


def test_jalur_antrean_tertutup_tanpa_sesi(konsol):
    app, _ = konsol
    client = TestClient(app)
    assert client.post("/api/console/unloading-queue/x/assign").status_code == 401
    assert client.post("/api/console/unloading-queue/x/skip").status_code == 401
    assert client.get("/api/console/dev/auto-assign").status_code == 401
    assert client.post("/api/console/dev/auto-assign", json={}).status_code == 401


class _PembaruanBerjalan:
    """An Update now install in progress (rule 38): every assign is refused."""

    def sedang_berjalan(self) -> bool:
        return True

    def menugaskan(self, line_code):
        raise AssertionError("no assign may even start while an install runs")


def test_selama_pembaruan_truk_menunggu_dan_tugaskan_sekarang_409(konsol):
    """Automatic assignment takes the Update now lock like manual Tugaskan (2026-10-03)."""
    app, service = konsol
    service.pakai_penjaga_pembaruan(_PembaruanBerjalan())
    sup = _masuk(app, SUPPORT)
    assert sup.post("/api/console/dev/auto-assign", json={"aktif": True, "lines": ["line-1"]}).status_code == 200
    op = _masuk(app, OPERATOR)
    assert _isi(op, "BE 1 AA")["dipasang"] == []
    antrean = op.get("/api/console/state").json()["antrean_bongkar"]
    assert [a["plate_number"] for a in antrean] == ["BE 1 AA"]
    r = op.post(f"/api/console/unloading-queue/{antrean[0]['weighing_id']}/assign")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "pembaruan_berjalan", r.text


def test_konsol_baru_bawaannya_nyala_dan_timbang_isi_langsung_memasang(tmp_path):
    """User 2026-10-05: a console that never saved this setting assigns automatically on every
    line, so the first weigh-in after an install already puts the truck on the lines."""
    store = ConsoleStore(tmp_path / "baru.db")
    store.upsert_operator_manual(
        {"email": SUPPORT, "full_name": SUPPORT, "password_hash": hash_password(SANDI), "role": "support"}
    )
    service = ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), store, FakeLine())
    app = FastAPI()
    app.include_router(console_router)
    pasang_penangan_validasi(app)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    support = _masuk(app, SUPPORT)

    setelan = support.get("/api/console/dev/auto-assign").json()
    assert setelan["aktif"] is True and setelan["lines"] == ["line-1", "line-2", "line-3"]

    tiket = _isi(support, "BE 1 BARU")
    dipasang = service.store.assignments()
    assert len(dipasang) == 3, ("the first weigh-in must go on all three lines", tiket, dipasang)
    assert len({a["truck_id"] for a in dipasang.values()}) == 1
