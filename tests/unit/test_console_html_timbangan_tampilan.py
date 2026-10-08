"""Timbangan in the new look (spec 2026-10-07 §5.3, PR 5): the same structure, restyled. Today's
neto and tickets are two tiles in a title row instead of one "Hari ini - ..." line; the arrows
between the four steps sit in the gap, never on a step's text."""
from __future__ import annotations

import re

from konsol_js import HTML


def _kepala() -> str:
    return HTML.split('<div class="timbang-kepala">', 1)[1].split("<!-- /timbang-kepala -->", 1)[0]


def test_today_is_a_title_and_two_tiles_with_the_same_ids():
    kepala = _kepala()
    assert 'id="tot-neto"' in kepala and 'id="tot-tiket"' in kepala
    assert kepala.count('class="timbang-ubin"') == 2
    assert 'data-t="judulTimbangan"' in kepala and 'data-t="timbangAlur"' in kepala
    assert "timbang-hari-ini" not in HTML


def test_the_tiles_sit_before_the_tools():
    sec = HTML.split('<section id="sec-timbangan"', 1)[1]
    assert sec.index('class="timbang-kepala"') < sec.index('class="tools timbang-alat berdiri"')


def test_forms_are_cards_on_the_band():
    aturan = re.search(r"\n  \.timbang-form \{([^}]*)\}", HTML).group(1)
    assert "background:var(--card)" in aturan and "var(--zebra)" not in aturan
