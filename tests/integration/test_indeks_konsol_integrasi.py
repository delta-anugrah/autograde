"""Integrasi (batch 2.5): database konsol dari sebelum batch 2 mendapat indeksnya saat
konsol menyala, dan semua yang dibaca layar tetap sama persis.

Dirangkai: `ConsoleStore` di berkas SQLite sungguhan + `ConsoleService` + route konsol
yang asli (login sungguhan). Database "lama" = skema hari ini tanpa tiga indeks batch
2.5, persis bentuk `state/console.db` di PC Lampung sebelum rilis ini.
"""
from __future__ import annotations

from dataclasses import replace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService

SANDI = "sandi-integrasi-indeks"
HARI = "2026-09-20"
INDEKS_BARU = ("idx_inspections_assignment", "idx_weighings_assignment", "idx_auto_releases_waktu")
PENUGASAN = [f"a{k}" for k in range(6)]


def _isi(store: ConsoleStore) -> None:
    """600 janjang, 6 penugasan di 3 line dan 3 truk, satu tiket per penugasan."""
    for k, assignment_id in enumerate(PENUGASAN):
        truk = f"t{k % 3}"
        store.upsert_truck({"id": truk, "plate_number": f"BE {k % 3} AA", "status": "active"})
        store.upsert_weighing({
            "id": f"w{k}", "ref": f"SCL-{k}", "plate_number": f"BE {k % 3} AA", "plate_norm": f"BE{k % 3}AA",
            "truck_id": truk, "work_date": HARI, "gross_kg": 14000.0 + k, "tare_kg": 5000.0,
            "net_kg": 9000.0 + k, "entered_at": f"{HARI}T0{k}:00:00+07:00", "exited_at": f"{HARI}T0{k}:50:00+07:00",
        })
        store.link_weighing_to_assignment(f"w{k}", assignment_id)
        for n in range(100):
            store.add_inspection({
                "event_id": f"ev-{k}-{n}", "machine_id": f"m-{k % 3}", "line_code": f"line-{k % 3 + 1}",
                "work_date": HARI, "timestamp": f"{HARI}T0{k}:{n // 60:02d}:{n % 60:02d}+07:00",
                "ripeness_status": "REJ" if n % 5 == 0 else "ACC", "ripeness_confidence": 0.9,
                "capture_type": "auto", "image_path": f"captures/results/{HARI}/{k}-{n}.webp",
                "truck_id": truk, "assignment_id": assignment_id, "prediction": "Rej" if n % 5 == 0 else "Acc",
                "grade_class": "JK" if n % 5 == 0 else "Ripe", "tp_status": None,
                "tp_confidence": 0.95 if n % 7 == 0 else None,
            })
    store.record_auto_release(line_code="line-1", truck_id="t0", plate_number="BE 0 AA", assignment_id="a0")


def _baca_layar(store: ConsoleStore) -> dict:
    """Yang dibaca layar dan pengirim kunjungan, lewat route dan service yang asli."""
    service = ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), store, line_client=None)
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    client = TestClient(app)
    assert client.post("/api/console/login", json={"email": "operator@pks.test", "sandi": SANDI}).status_code == 200
    return {
        "history": client.get("/api/console/history", params={"work_date": HARI, "limit": 200}).json(),
        "history_line": client.get("/api/console/history",
                                   params={"work_date": HARI, "line_code": "line-2", "limit": 200}).json(),
        "recap": client.get("/api/console/recap", params={"work_date": HARI}).json(),
        "weighings": client.get("/api/console/weighings", params={"work_date": HARI}).json(),
        "grading": {a: store.grading_counts(a) for a in PENUGASAN},
        "grading_visit": {f"w{k}": store.grading_counts_for_visit(f"w{k}") for k in range(len(PENUGASAN))},
        "bunches": {f"w{k}": store.bunches_for_visit(f"w{k}") for k in range(len(PENUGASAN))},
        "tiket": {a: store.weighing_for_assignment(a) for a in PENUGASAN},
        "auto_releases": [r["assignment_id"] for r in store.auto_releases_terbaru(sejak_detik=86_400)],
    }


def test_database_lama_mendapat_indeks_dan_layar_membaca_hal_yang_sama(tmp_path):
    path = tmp_path / "console.db"
    lama = ConsoleStore(path)
    lama.upsert_operator_manual(
        {"email": "operator@pks.test", "full_name": "Operator", "password_hash": hash_password(SANDI)}
    )
    _isi(lama)
    with lama._lock, lama._db:
        for nama in INDEKS_BARU:
            lama._db.execute(f"DROP INDEX {nama}")
    sebelum = _baca_layar(lama)
    lama._db.close()

    baru = ConsoleStore(path)                       # konsol menyala dengan build ini

    indeks = {r[0] for r in baru._db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert set(INDEKS_BARU) <= indeks
    assert _baca_layar(baru) == sebelum
    assert sebelum["history"]["total"] == 600 and len(sebelum["recap"]["items"]) == 3
