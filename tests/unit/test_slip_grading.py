"""Printable grading slip per truck (batch 5.9): what the slip says, worked out on the server.

The rate is computed here (standard L4), from the binary verdict like the Rekap tab, and the
net weight is the sum of that truck's tickets that day. The slip exists only while support
has switched it on; the screen merely hides the button.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.operator_error import SLIP_MATI, SLIP_TIDAK_ADA, OperatorError
from palmgrade.domain.slip_grading import rasio_ripe_persen, susun_slip
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.slip_grading import SlipGrading

WIB = ZoneInfo("Asia/Jakarta")


@pytest.mark.parametrize(("acc", "total", "rasio"), [(0, 0, None), (3, 4, 75.0), (2, 3, 66.7), (5, 5, 100.0)])
def test_the_rate_is_the_accepted_share_rounded_to_one_decimal(acc, total, rasio):
    assert rasio_ripe_persen(acc, total) == rasio


def test_the_slip_folds_every_ticket_of_the_truck_into_one_net_weight():
    rekap = {"truck_id": "t1", "plate_number": "BE 1 AA", "supplier_name": "KUD A", "source_label": "External",
             "total": 4, "acc": 3, "ripe": 3, "unripe": 1, "jk": 0, "tp": 1, "tanpa_kelas": 0,
             "started_at": "2026-10-05T01:00:00+00:00", "ended_at": "2026-10-05T02:00:00+00:00"}
    tiket = [
        {"net_kg": 7000.0, "gross_kg": 12000.0, "tare_kg": 5000.0, "entered_at": "a", "exited_at": "b"},
        {"net_kg": 500.5, "gross_kg": 5500.5, "tare_kg": 5000.0, "entered_at": "c", "exited_at": None},
        {"net_kg": None, "gross_kg": 9000.0, "tare_kg": None, "entered_at": "d", "exited_at": None},
    ]

    slip = susun_slip(rekap, tiket, work_date="2026-10-05", perusahaan="PT Uji")

    assert slip["neto_kg"] == 7500.5
    assert slip["rasio_ripe"] == 75.0
    assert [t["neto_kg"] for t in slip["tiket"]] == [7000.0, 500.5, None]
    assert (slip["plate_number"], slip["perusahaan"], slip["work_date"]) == ("BE 1 AA", "PT Uji", "2026-10-05")
    assert slip["kelas"] == {"ripe": 3, "unripe": 1, "jk": 0, "tp": 1, "tanpa_kelas": 0, "total": 4}


def test_no_ticket_means_no_net_weight_rather_than_zero():
    rekap = {"truck_id": "t1", "plate_number": "BE 1 AA", "total": 1, "acc": 1}
    assert susun_slip(rekap, [], work_date="2026-10-05", perusahaan="")["neto_kg"] is None


@pytest.fixture
def pabrik(tmp_path):
    settings = replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta", erp_company="PT Sawit Uji")
    store = ConsoleStore(tmp_path / "console.db")
    konsol = ConsoleService(settings, store, line_client=None)
    return konsol, SlipGrading(store, perusahaan=settings.erp_company)


def test_the_switch_is_off_until_support_turns_it_on_and_it_survives_a_restart(pabrik, tmp_path):
    _, slip = pabrik
    assert slip.aktif() is False

    assert slip.atur(True) == {"aktif": True}

    assert SlipGrading(ConsoleStore(tmp_path / "console.db"), perusahaan="").aktif() is True


def test_a_slip_is_refused_while_the_switch_is_off(pabrik):
    _, slip = pabrik
    with pytest.raises(OperatorError) as e:
        slip.slip("2026-10-05", "t1")
    assert e.value.code == SLIP_MATI


def test_a_truck_with_no_bunch_that_day_has_no_slip(pabrik):
    _, slip = pabrik
    slip.atur(True)
    with pytest.raises(OperatorError) as e:
        slip.slip("2026-10-05", "tidak-ada")
    assert e.value.code == SLIP_TIDAK_ADA


def test_a_slip_from_real_rows(pabrik):
    konsol, slip = pabrik
    slip.atur(True)
    truk = konsol.register_manual_truck("BE 1 AA")["id"]
    konsol.store.set_assignment("line-1", "as-1", truk)
    sekarang = datetime.now(WIB)
    for nomor, (status, kelas) in enumerate((("ACC", "Ripe"), ("ACC", "Ripe"), ("REJ", "JK"))):
        konsol.ingest({
            "event_id": f"ev-{nomor}", "machine_id": konsol.lines[0].machine_id, "timestamp": sekarang.isoformat(),
            "ripeness_status": status, "ripeness_confidence": 0.9, "capture_type": "auto", "grade_class": kelas,
            "image_path": f"captures/results/x/{nomor}.webp", "truck_id": truk, "assignment_id": "as-1",
        })
    asyncio.run(konsol.record_weighing({"plate_number": "BE 1 AA", "gross_kg": 12000, "tare_kg": 4000,
                                        "entered_at": sekarang.isoformat()}))

    hasil = slip.slip(konsol.today(), truk)

    assert (hasil["plate_number"], hasil["perusahaan"]) == ("BE 1 AA", "PT Sawit Uji")
    assert hasil["kelas"]["total"] == 3 and hasil["kelas"]["jk"] == 1
    assert hasil["rasio_ripe"] == 66.7 and hasil["neto_kg"] == 8000.0
    assert "has_supplier" not in hasil and "in_erp" not in hasil
