"""What the console screen must keep saying after the model went to four classes.

Text invariants over `console.html`, like `test_console_html.py`: there is no JS
runner here and no DOM, so these assert on the source. They exist because the
four figures are read from several metres away outdoors, and two of the ways they
can break are silent — a colspan left at the old width, and count cells matched
by DOM position instead of by name.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

KONSOL = Path(__file__).resolve().parents[2] / "src" / "palmgrade" / "static" / "console.html"


@pytest.fixture(scope="module")
def html() -> str:
    return KONSOL.read_text(encoding="utf-8")


@pytest.mark.parametrize("tid", ["tot-ripe", "tot-unripe", "tot-jk", "tot-tp", "tot-all"])
def test_the_tally_strip_has_a_cell_for_every_class(html, tid):
    assert f'id="{tid}"' in html


def test_the_tally_no_longer_carries_the_old_binary_cells(html):
    """`isiTally` writes by id; an id left behind here is a figure that silently
    stops updating while still showing a number from the last render."""
    assert 'id="tot-acc"' not in html
    assert 'id="tot-rej"' not in html


def test_line_cards_update_by_name_not_by_position(html):
    """The 2 s poll patches the live cards in place to keep the MJPEG stream
    alive. It used to index `.counts b` as b[0]/b[1]/b[2], so reordering the
    markup swapped the numbers on screen with nothing failing."""
    assert 'querySelectorAll(".counts b[data-k]")' in html
    assert "b[0].textContent" not in html
    for key in ("ripe", "unripe", "jk", "tp", "total"):
        assert f'data-k="{key}"' in html


def test_every_count_cell_has_a_matching_grid_column(html):
    """Five figures in a three-column grid overflows the card silently."""
    assert "grid-template-columns:repeat(5,1fr)" in html


def test_the_recap_empty_row_spans_the_widened_table(html):
    """Ripe/Unripe/JK/TP replaced ACC/REJ, so the table gained two columns. A
    colspan left at 8 stops the "no data yet" row halfway across."""
    assert 'barisKosong(10, "kosongRekap")' in html


def test_the_result_badge_prefers_the_class_but_survives_rows_without_one(html):
    """Rows written before `grade_class` existed must still read as ACC/REJ
    rather than collapsing to an empty cell."""
    assert "tagHasil(r.ripeness_status, r.grade_class)" in html
    assert "esc(kelas || s)" in html


def test_the_badge_colour_follows_the_verdict_not_the_class(html):
    """Green means the bunch passed. JK and Unripe are both discarded, so both
    must be red — the operator reads colour before words at distance."""
    tag = re.search(r"const tagHasil = .*?\n};", html, re.S)
    assert tag, "tagHasil not found"
    assert 'toUpperCase() === "ACC"' in tag.group(0)


def test_the_screen_has_no_hardcoded_https_reference(html):
    """Unchanged rule: the console must work with the internet cut."""
    assert "https://" not in html
