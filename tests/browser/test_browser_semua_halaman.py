"""Checks that hold on every tab. The `halaman` guard already fails a script error or a
request beyond this machine, so opening each tab as support is itself the test."""

from __future__ import annotations

import pytest
from langkah import SUPPORT, buka_tab, masuk
from playwright.sync_api import expect

TABS = ("grading", "truk", "timbangan", "rekap", "log", "status", "akun", "line", "setelan")

# A KAMUS key looks like code (`err_bukan_plat`, `sukScan`); a sentence never does.
_KUNCI_TERLIHAT = """() => {
  const teks = document.body.innerText;
  return Object.keys(KAMUS[bahasa])
    .filter((k) => /_|[a-z][A-Z]/.test(k))
    .filter((k) => new RegExp(`(^|\\\\W)${k}(\\\\W|$)`).test(teks));
}"""


_MUAT_TAB = "(tab) => MUAT_TAB[tab] ? MUAT_TAB[tab]() : null"


def test_every_tab_opens_for_support(halaman):
    masuk(halaman, SUPPORT)
    for tab in TABS:
        buka_tab(halaman, tab)


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_no_raw_key_on_any_tab(halaman, bahasa):
    masuk(halaman, SUPPORT)
    if bahasa == "en":
        halaman.click("#bahasa")
        expect(halaman.locator("#bahasa")).to_have_text("ID")
    for tab in TABS:
        buka_tab(halaman, tab)
        assert halaman.evaluate(_KUNCI_TERLIHAT) == [], f"raw KAMUS key on tab {tab} ({bahasa})"


def test_a_narrow_screen_never_scrolls_sideways(halaman):
    halaman.set_viewport_size({"width": 1024, "height": 768})
    masuk(halaman, SUPPORT)
    for tab in TABS:
        buka_tab(halaman, tab)
        # Measure the tab with its data: a tab's table is drawn after its fetch returns, and a
        # measurement taken before that passed on a fast laptop and failed on the CI runner.
        # Awaiting the screen's own loader (`MUAT_TAB`) is the one wait that fits every tab.
        halaman.evaluate(_MUAT_TAB, tab)
        lebar = halaman.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
        assert lebar[0] <= lebar[1], f"tab {tab} is {lebar[0]} px wide on a {lebar[1]} px screen"
