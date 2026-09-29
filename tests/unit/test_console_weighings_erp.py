"""Tab Timbangan membawa kode jawaban AutoERP yang butuh orang (batch 2.3).

Layar tidak mengurai kalimat AutoERP: server yang menggolongkan (`erp_perlu_dicek`),
layar cuma memberi kata.
"""
from __future__ import annotations

from dataclasses import replace

from palmgrade.core.config import Settings
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService

HARI = "2026-09-28"


def test_baris_timbangan_membawa_kode_jawaban_autoerp(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    service = ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), store, line_client=None)
    for n, note in enumerate((
        "ticket already finalised; grading revised",
        "ticket cancelled; visit ignored",
        "ticket already finalised; visit unchanged",
        None,
    ), start=1):
        store.upsert_weighing({
            "id": f"w{n}", "ref": f"SCL-{n}", "plate_number": f"BE {n} AA", "plate_norm": f"BE{n}AA",
            "truck_id": None, "work_date": HARI, "gross_kg": 14560.0, "tare_kg": None, "net_kg": None,
            "entered_at": f"{HARI}T07:4{n}:00+07:00", "exited_at": None,
        })
        store.record_visit_answer(f"w{n}", ticket=f"WB-{n}", status="Finalised", note=note)

    baris = {r["id"]: r for r in service.weighings(HARI)}

    assert {k: r["erp_perlu_dicek"] for k, r in baris.items()} == {
        "w1": "tiket_final_berbeda", "w2": "tiket_dibatalkan", "w3": None, "w4": None,
    }
    assert "has_supplier" not in baris["w1"] and "source_label" in baris["w1"]
