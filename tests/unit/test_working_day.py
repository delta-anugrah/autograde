"""Mill working-day boundary (PalmOS plan §6.1).

The mill runs ~20 hours/day and ACROSS midnight WIB. 00:30 WIB is still the
same shift as 23:00 the previous day, but in UTC it has already crossed a
date — that is the trap. This test is the first thing to fail if anything
ever computes the date from UTC or from `now()` again.
"""
from __future__ import annotations

from datetime import UTC
from zoneinfo import ZoneInfo

import pytest

from palmgrade.domain.working_day import work_date_for

WIB = ZoneInfo("Asia/Jakarta")  # UTC+7


def test_past_midnight_wib_lands_on_the_wib_date_not_utc():
    # 2026-09-09 18:30 UTC = 2026-09-10 01:30 WIB — night shift, already a new
    # day at the mill even though UTC still reads the 9th.
    assert work_date_for("2026-09-09T18:30:00+00:00", WIB) == "2026-09-10"


def test_wib_evening_has_not_rolled_over_even_though_utc_is_still_yesterday():
    # 2026-09-09 16:00 UTC = 2026-09-09 23:00 WIB — still the same day.
    assert work_date_for("2026-09-09T16:00:00Z", WIB) == "2026-09-09"


def test_wib_morning_is_still_yesterday_by_utc():
    # 2026-09-08 22:00 UTC = 2026-09-09 05:00 WIB. Using UTC would pick the wrong day.
    ts = "2026-09-08T22:00:00+00:00"
    assert work_date_for(ts, WIB) == "2026-09-09"
    assert work_date_for(ts, UTC) == "2026-09-08"


def test_a_naive_timestamp_is_read_as_utc():
    assert work_date_for("2026-09-09T18:30:00", WIB) == "2026-09-10"


def test_a_non_utc_offset_is_honoured():
    # A line that sends +07:00 directly must not be shifted a second time.
    assert work_date_for("2026-09-10T01:30:00+07:00", WIB) == "2026-09-10"


def test_a_broken_timestamp_raises_instead_of_falling_back_to_today():
    # Silently using now() would land tonnage on the wrong date with nobody
    # the wiser. Raising → ingest answers 400 → the line's outbox marks it failed.
    with pytest.raises(ValueError):
        work_date_for("kemarin sore", WIB)
    with pytest.raises(ValueError):
        work_date_for("", WIB)
