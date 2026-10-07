"""Small findings from the #256 review (2026-10-08): the hidden rail and the keyboard, the
more menu and Esc."""

from __future__ import annotations

import re

from langkah import OPERATOR, buka_menu_line, masuk
from playwright.sync_api import expect


def test_tab_never_lands_on_the_hidden_rail(halaman):
    masuk(halaman, OPERATOR)
    halaman.click("#menu-samping")
    expect(halaman.locator("body")).to_have_class(re.compile(r"\bmenu-tutup\b"))
    halaman.wait_for_timeout(500)  # the slide is .28 s; visibility flips at its end
    for _ in range(14):
        halaman.keyboard.press("Tab")
        assert not halaman.evaluate("() => !!document.activeElement.closest('#tabs')")
    # Shown again: the rail is reachable again.
    halaman.click("#menu-samping")
    expect(halaman.locator('#tabs button[data-tab="truk"]')).to_be_visible()


def test_escape_closes_the_more_menu(halaman):
    masuk(halaman, OPERATOR)
    kartu = halaman.locator('#lines .card[data-line="line-1"]')
    buka_menu_line(kartu)
    menu = kartu.locator("details.lagi")
    expect(menu).to_have_attribute("open", "")
    halaman.keyboard.press("Escape")
    expect(menu).not_to_have_attribute("open", "")
