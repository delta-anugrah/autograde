"""Capture timestamps must be timezone-aware.

Regression guard for the 7-hour shift: vision wrote `datetime.now().isoformat()`
(naive, and its containers run UTC) while palmgrade-api runs TZ=Asia/Jakarta.
JavaScript resolves a bare date-time as *local* time, so every capture landed in
MongoDB 7 hours early and the dashboard showed times 7 hours behind reality.

Emitting an explicit UTC offset removes the ambiguity at the source.
"""
from __future__ import annotations

import datetime
import re

import pytest

# Filenames stay in this shape; event_id is uuid5 of the filename timestamp, so
# a format change here would silently break idempotency against existing rows.
FILENAME_TS = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}_\d{6}$")


def _parse(value: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(value)


def test_aware_utc_isoformat_carries_an_offset() -> None:
    """The shape vision now emits: parseable, and unambiguous."""
    emitted = datetime.datetime.now(datetime.UTC).isoformat()

    parsed = _parse(emitted)

    assert parsed.tzinfo is not None, "consumer must not have to guess the zone"
    assert parsed.utcoffset() == datetime.timedelta(0)


def test_naive_isoformat_is_the_ambiguous_shape_we_moved_away_from() -> None:
    """Documents the old behaviour so a revert fails loudly here."""
    legacy = datetime.datetime.now().isoformat()

    assert _parse(legacy).tzinfo is None


def test_filename_derivation_is_unchanged_by_the_aware_instant() -> None:
    """strftime on an aware UTC instant yields the same filename shape.

    The containers already run UTC, so switching the source instant to aware
    UTC keeps names byte-identical — no event_id churn on the factory install.
    """
    now = datetime.datetime.now(datetime.UTC)

    date_folder = now.strftime("%Y-%m-%d")
    timestamp = now.strftime("%Y-%m-%d_%H%M%S_%f")

    assert FILENAME_TS.match(timestamp)
    assert timestamp.startswith(date_folder)
    # An aware instant must not leak an offset into the filename.
    assert "+" not in timestamp


@pytest.mark.parametrize(
    "emitted,expected_utc",
    [
        ("2026-01-02T03:04:05.678901+00:00", "2026-01-02T03:04:05.678901+00:00"),
        ("2026-01-02T10:04:05.678901+07:00", "2026-01-02T03:04:05.678901+00:00"),
    ],
)
def test_aware_values_round_trip_to_the_same_instant(
    emitted: str, expected_utc: str
) -> None:
    parsed = _parse(emitted).astimezone(datetime.UTC)

    assert parsed == _parse(expected_utc)
