"""A cutoff changed while trucks are in the yard (batch 5.11 review): rows stored under the old
cutoff keep their date (rule 10), so every read by work date must still find them."""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from palmgrade.core.config import Settings
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService

WIB = ZoneInfo("Asia/Jakarta")


@pytest.fixture
def konsol(tmp_path):
    settings = replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta")
    return ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), line_client=None)


def _datang(konsol, id_, jam, hari, truck="t1"):
    konsol.store.record_arrival({"id": id_, "plate_number": "BE 1 AA", "plate_norm": "BE1AA",
                                 "truck_id": truck, "work_date": hari, "arrived_at": jam})


def _tiket(konsol, id_, hari, masuk, *, tara=None, keluar=None, truck="t1"):
    konsol.store.upsert_weighing({
        "id": id_, "ref": None, "plate_number": "BE 1 AA", "plate_norm": "BE1AA",
        "truck_id": truck, "work_date": hari, "gross_kg": 12000.0, "tare_kg": tara,
        "net_kg": None if tara is None else 12000.0 - tara, "entered_at": masuk, "exited_at": keluar,
    })


def test_a_truck_still_waiting_after_the_cutoff_is_lowered(konsol):
    # Arrived 6 Oct 03:00 under 05:00: filed under 5 Oct. Support goes back to 00:00.
    _datang(konsol, "a1", "2026-10-06T03:00:00+07:00", "2026-10-05")
    konsol.hari_kerja.atur("00:00")

    menunggu = konsol.waiting_arrivals(datetime(2026, 10, 6, 14, 0, tzinfo=WIB))

    assert [a["id"] for a in menunggu] == ["a1"], "11 h waiting, inside the 12 h window"


def test_a_return_filed_under_the_day_before_still_finishes_the_old_ticket(konsol):
    # Weighed out 6 Oct 01:30 under 00:00 (filed 6 Oct), no scan 4. Cutoff raised to 05:00;
    # the truck comes back at 03:00 and that arrival is filed under 5 Oct.
    _tiket(konsol, "w1", "2026-10-06", "2026-10-06T01:00:00+07:00", tara=8000.0, keluar="2026-10-06T01:30:00+07:00")
    konsol.hari_kerja.atur("05:00")
    _datang(konsol, "a2", "2026-10-06T03:00:00+07:00", "2026-10-05")

    baris = konsol.tandai_tanpa_scan_4(konsol.store.weighings("2026-10-06"), datetime(2026, 10, 6, 4, 0, tzinfo=WIB))

    assert baris[0]["tanpa_scan_4"] is True


def test_raising_the_cutoff_at_night_keeps_the_truck_on_the_scale_in_the_table(konsol):
    # Weighed in 6 Oct 00:30 under 00:00 (filed 6 Oct). At 02:00 support saves 05:00, so "today"
    # is 5 Oct until 05:00: the ticket must stay on today's table with its buttons.
    _tiket(konsol, "w1", "2026-10-06", "2026-10-06T00:30:00+07:00")
    konsol.hari_kerja.atur("05:00")
    konsol.sekarang = lambda: datetime(2026, 10, 6, 2, 0, tzinfo=WIB)

    assert konsol.today() == "2026-10-05"
    assert [r["id"] for r in konsol.weighings("2026-10-05")] == ["w1"]


def test_the_state_poll_at_three_with_a_five_oclock_cutoff_is_yesterday(konsol):
    konsol.hari_kerja.atur("05:00")
    konsol.sekarang = lambda: datetime(2026, 10, 6, 3, 0, tzinfo=WIB)

    keadaan = konsol.state()

    assert (keadaan["work_date"], keadaan["cutoff_shift"]) == ("2026-10-05", "05:00")


def test_a_bad_stored_cutoff_is_warned_once_not_per_bunch(konsol, caplog):
    konsol.store.set_state("setelan_cutoff_shift", "rusak")
    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            konsol.hari_kerja.cutoff()
    assert len([r for r in caplog.records if "cutoff" in r.getMessage().lower()]) == 1


def test_a_change_is_logged_with_old_new_and_who(konsol, caplog):
    konsol.hari_kerja.atur("05:00")
    with caplog.at_level(logging.INFO):
        konsol.hari_kerja.atur("06:30", oleh="support@pks.test")
    pesan = " ".join(r.getMessage() for r in caplog.records)
    assert "05:00" in pesan and "06:30" in pesan and "support@pks.test" in pesan
