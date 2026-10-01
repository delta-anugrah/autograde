"""Grading tab: a line that answers shows its camera; a line that does not is marked offline.

`.card.putus` is what `console.html` sets when the feed image fails (`cekKamera`); line-3's
port has nobody listening, the fake line-1 serves one PNG frame.
"""

from __future__ import annotations

import re

from langkah import OPERATOR, masuk
from playwright.sync_api import expect

_PUTUS = re.compile(r"\bputus\b")


def test_three_line_cards_render(halaman):
    masuk(halaman, OPERATOR)
    expect(halaman.locator("#lines .card")).to_have_count(3)


def test_a_line_with_a_camera_is_connected_and_a_dead_one_is_offline(halaman):
    masuk(halaman, OPERATOR)
    expect(halaman.locator('#lines .card[data-line="line-3"]')).to_have_class(_PUTUS)
    expect(halaman.locator('#lines .card[data-line="line-1"]')).not_to_have_class(_PUTUS)
    expect(halaman.locator('#lines .card[data-line="line-3"] .sinyal .off')).to_be_visible()
