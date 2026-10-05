"""The cutoff is read from console.db on every call, so a change applies to the next row
without a restart, and rows already stored never move (rule 10)."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.operator_error import CUTOFF_TIDAK_SAH, OperatorError
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.hari_kerja import KUNCI_CUTOFF, HariKerja

WIB = ZoneInfo("Asia/Jakarta")


@pytest.fixture
def konsol(tmp_path):
    settings = replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta")
    return ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), line_client=None)


def _janjang(konsol, nomor: int, ts: str) -> str:
    return konsol.ingest({
        "event_id": f"ev-{nomor}", "machine_id": konsol.lines[0].machine_id, "timestamp": ts,
        "ripeness_status": "ACC", "ripeness_confidence": 0.9, "capture_type": "auto",
        "image_path": f"captures/results/x/{nomor}.webp", "truck_id": None, "assignment_id": None,
    })


def test_midnight_until_support_sets_a_cutoff(konsol):
    assert konsol.hari_kerja.cutoff().strftime("%H:%M") == "00:00"
    assert _janjang(konsol, 1, "2026-10-06T02:30:00+07:00") == "2026-10-06"


def test_a_saved_cutoff_applies_to_the_next_bunch_and_old_rows_stay(konsol):
    awal = _janjang(konsol, 1, "2026-10-06T02:30:00+07:00")

    assert konsol.hari_kerja.atur("05:00") == {"cutoff": "05:00"}

    assert _janjang(konsol, 2, "2026-10-06T02:40:00+07:00") == "2026-10-05"
    simpan = {r["event_id"]: r["work_date"] for r in konsol.store.inspections("2026-10-06", limit=10)}
    assert awal == "2026-10-06" and simpan == {"ev-1": "2026-10-06"}, "the first bunch did not move"


def test_today_follows_the_cutoff(konsol):
    konsol.hari_kerja.atur("05:00")
    assert konsol.hari_kerja.kini(datetime(2026, 10, 6, 3, 0, tzinfo=WIB)) == "2026-10-05"


def test_a_weighing_lands_on_the_working_day_of_its_weigh_in(konsol):
    konsol.hari_kerja.atur("05:00")
    konsol.register_manual_truck("BE 1 AA")
    tiket = asyncio.run(konsol.record_weighing({
        "plate_number": "BE 1 AA", "gross_kg": 12000, "entered_at": "2026-10-06T00:30:00+07:00"}))
    assert tiket["work_date"] == "2026-10-05"


def test_a_cutoff_outside_the_range_is_refused_and_not_saved(konsol):
    with pytest.raises(OperatorError) as e:
        konsol.hari_kerja.atur("24:00")
    assert e.value.code == CUTOFF_TIDAK_SAH
    assert konsol.store.get_state(KUNCI_CUTOFF) is None


def test_a_stored_value_that_is_not_a_cutoff_runs_as_midnight(konsol, caplog):
    konsol.store.set_state(KUNCI_CUTOFF, "rusak")
    assert konsol.hari_kerja.cutoff().strftime("%H:%M") == "00:00"
    assert _janjang(konsol, 1, "2026-10-06T02:30:00+07:00") == "2026-10-06"
    assert "cutoff" in caplog.text.lower()


def test_the_gate_uses_the_same_working_day(tmp_path):
    from palmgrade.services.gate_service import GateService

    store = ConsoleStore(tmp_path / "console.db")
    hari = HariKerja(store, WIB)
    hari.atur("05:00")
    assert GateService(store, WIB, hari).hari_kerja is hari
    # Built without one, it reads the same setting from the same store.
    assert GateService(store, WIB).hari_kerja.untuk("2026-10-06T02:30:00+07:00") == "2026-10-05"
