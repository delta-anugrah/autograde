"""Steps every browser test repeats, written once.

Every browser test module imports this first, so this is where a missing Playwright is
decided: skipped on a laptop that never ran `make browser-siap`, a failure when
`WAJIB_BROWSER=1` (CI), because a required suite must not turn green by skipping itself.
A module-level skip only works from a test module's import, not from `conftest.py`.
"""

from __future__ import annotations

import os

import pytest

if os.environ.get("WAJIB_BROWSER") != "1":
    pytest.importorskip("playwright", reason="Playwright belum terpasang: make browser-siap")

from playwright.sync_api import Page, expect  # noqa: E402

# Playwright's own default; written down so a slow CI runner is never "fixed" by a sleep.
EXPECT_MAKS_MS = 5_000
# How long a test lets the page's own clock run a timer it just set (no Python sleep).
JEDA_HALAMAN_MS = 300

expect.set_options(timeout=EXPECT_MAKS_MS)

OPERATOR = ("operator@demo.autoerp.test", "sawit2026")
SUPPORT = ("support@demo.autoerp.test", "sawit2026")


def plat(browser_name: str, angka: int) -> str:
    """A plate unique per browser (`BE1003CX` in Chromium, `BE1003FX` in Firefox), written the
    way `normalisasi_plat` stores it, so both browsers can run in one local session."""
    return f"BE{angka}{browser_name[0].upper()}X"


def kamus(page: Page, kunci: str) -> str:
    """The sentence the screen shows for `kunci`, in its current language."""
    return page.evaluate("(k) => t(k)", kunci)


def masuk(page: Page, akun: tuple[str, str]) -> None:
    email, sandi = akun
    page.fill("#gerbang-email", email)
    page.fill("#gerbang-sandi", sandi)
    page.click("#gerbang-masuk")
    expect(page.locator("#keluar")).to_be_visible()
    expect(page.locator("#gerbang")).to_be_hidden()


def keluar(page: Page) -> None:
    page.click("#keluar")
    expect(page.locator("#gerbang")).to_be_visible()


def buka_tab(page: Page, nama: str) -> None:
    page.click(f'#tabs [data-tab="{nama}"]')
    expect(page.locator(f"#sec-{nama}")).to_be_visible()
