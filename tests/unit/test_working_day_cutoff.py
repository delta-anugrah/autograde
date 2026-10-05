"""The working day may start at a cutoff hour instead of midnight (batch 5.11)."""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from palmgrade.domain.operator_error import CUTOFF_TIDAK_SAH, OperatorError
from palmgrade.domain.working_day import baca_cutoff, hari_kerja_kini, teks_cutoff, work_date_for

WIB = ZoneInfo("Asia/Jakarta")
LIMA = time(5, 0)


@pytest.mark.parametrize(
    ("ts", "cutoff", "hari"),
    [
        ("2026-10-06T10:00:00+07:00", time(18, 0), "2026-10-05"),  # after noon: the start's date
        ("2026-10-06T18:00:00+07:00", time(18, 0), "2026-10-06"),
        ("2026-10-05T23:59:59+07:00", time(0, 0), "2026-10-05"),
        ("2026-10-06T00:00:00+07:00", time(0, 0), "2026-10-06"),
        ("2026-10-06T02:30:00+07:00", LIMA, "2026-10-05"),
        ("2026-10-06T04:59:59+07:00", LIMA, "2026-10-05"),
        ("2026-10-06T05:00:00+07:00", LIMA, "2026-10-06"),
        ("2026-10-05T19:30:00+00:00", LIMA, "2026-10-05"),  # 02:30 WIB on the 6th
        ("2026-10-05T23:00:00", LIMA, "2026-10-06"),          # no offset = UTC = 06:00 WIB
    ],
)
def test_the_working_day_starts_at_the_cutoff(ts, cutoff, hari):
    assert work_date_for(ts, WIB, cutoff) == hari


def test_without_a_cutoff_nothing_changes():
    assert work_date_for("2026-10-06T00:10:00+07:00", WIB) == "2026-10-06"


def test_the_working_day_now_follows_the_same_rule():
    assert hari_kerja_kini(datetime(2026, 10, 6, 3, 0, tzinfo=WIB), WIB, LIMA) == "2026-10-05"
    assert hari_kerja_kini(datetime(2026, 10, 6, 6, 0, tzinfo=WIB), WIB, LIMA) == "2026-10-06"


@pytest.mark.parametrize(("teks", "nilai"), [("05:00", LIMA), ("5:00", LIMA), ("05.00", LIMA), ("", time(0)),
                                             (None, time(0)), ("12:00", time(12)), ("00:30", time(0, 30)),
                                             ("13:00", time(13)), ("18.30", time(18, 30)), ("23:59", time(23, 59))])
def test_the_cutoff_is_read_the_way_people_type_it(teks, nilai):
    assert baca_cutoff(teks) == nilai


@pytest.mark.parametrize("teks", ["24:00", "23:60", "5", "jam lima", "05:60", "-1:00"])
def test_a_cutoff_that_is_not_a_time_of_day_is_refused(teks):
    with pytest.raises(OperatorError) as e:
        baca_cutoff(teks)
    assert e.value.code == CUTOFF_TIDAK_SAH


def test_the_cutoff_is_written_back_as_hh_mm():
    assert teks_cutoff(LIMA) == "05:00" and teks_cutoff(time(0, 30)) == "00:30"
