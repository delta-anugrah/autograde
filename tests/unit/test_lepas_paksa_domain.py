"""Lepas paksa, the pure rules (2026-10-04): when the console may clear a line by itself,
and what it does once that line answers again.
"""
from __future__ import annotations

import json

import pytest

from palmgrade.domain.lepas_paksa import (
    baca_tertunda,
    boleh_paksa,
    perlu_kirim_ulang,
    teks_tertunda,
)
from palmgrade.domain.operator_error import LINE_MENOLAK, LINE_TIDAK_MENJAWAB


def test_only_a_line_that_gave_no_answer_at_all_may_be_forced():
    assert boleh_paksa(LINE_TIDAK_MENJAWAB, None) is True


@pytest.mark.parametrize(
    ("kode", "status"),
    [
        (LINE_MENOLAK, 409),  # the line answered and refused
        (LINE_MENOLAK, 401),  # INTERNAL_SECRET differs: alive, refusing the key
        (LINE_MENOLAK, 500),  # the line's own error: alive
        (LINE_TIDAK_MENJAWAB, 404),  # something answered at that address
        (None, None),
    ],
)
def test_a_line_that_answered_anything_is_never_forced(kode, status):
    assert boleh_paksa(kode, status) is False


def test_the_release_is_sent_again_when_the_line_still_holds_the_forced_truck():
    assert perlu_kirim_ulang("truk-a", truk_di_line="truk-a", truk_di_konsol=None) is True


@pytest.mark.parametrize(
    ("truk_di_line", "truk_di_konsol"),
    [
        (None, None),  # the line restarted and pulled the empty assignment itself
        ("truk-b", "truk-b"),  # a new truck went on after the line came back
        ("truk-a", "truk-a"),  # the operator put the same truck back on
        ("truk-b", None),  # some other truck: not ours to clear
    ],
)
def test_anything_else_closes_the_pending_release_without_a_send(truk_di_line, truk_di_konsol):
    assert perlu_kirim_ulang("truk-a", truk_di_line=truk_di_line, truk_di_konsol=truk_di_konsol) is False


@pytest.mark.parametrize("teks", [None, "", "bukan json", "[1, 2]", '{"line-1": 5}', '{"": "truk-a"}'])
def test_a_stored_value_that_is_not_a_clean_map_reads_as_nothing_pending(teks):
    assert baca_tertunda(teks) == {}


def test_pending_releases_round_trip_through_the_stored_text():
    isi = {"line-1": "truk-a", "line-3": "truk-b"}
    assert baca_tertunda(teks_tertunda(isi)) == isi
    assert json.loads(teks_tertunda(isi)) == isi


def test_a_partly_broken_map_keeps_the_clean_entries():
    assert baca_tertunda('{"line-1": "truk-a", "line-2": 7}') == {"line-1": "truk-a"}
