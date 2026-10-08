"""Steps every browser test repeats, written once.

Every browser test module imports this first, so this is where a missing Playwright is
decided: skipped on a laptop that never ran `make browser-siap`, a failure when
`WAJIB_BROWSER=1` (CI), because a required suite must not turn green by skipping itself.
A module-level skip only works from a test module's import, not from `conftest.py`.
"""

from __future__ import annotations

import os

import httpx
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


def buka_menu_line(kartu) -> None:
    """Opens a line card's "more" menu (Tugaskan, Lepas, card order) when the card has one and
    it is closed (spec 2026-10-07 §5.2)."""
    # The first poll after signing in draws the cards again, which closes an open menu.
    kartu.page.wait_for_function("() => typeof dipasang !== 'undefined' && dipasang")
    lagi = kartu.locator("details.lagi")
    if lagi.count() and lagi.get_attribute("open") is None:
        lagi.locator("summary").click()
        expect(lagi.locator(".lagi-isi")).to_be_visible()


def buka_setelan(page: Page, sub: str) -> None:
    """The Settings tab, then one of its sub-tabs (2026-10-05). The open sub-tab is remembered
    in the browser, so a test names the one it needs rather than relying on the last test."""
    buka_tab(page, "setelan")
    page.click(f'#setelan-sub button[data-sub="{sub}"]')
    expect(page.locator(f'#setelan-sub button[data-sub="{sub}"]')).to_have_attribute("aria-pressed", "true")
    # Each category is a collapsible section since 2026-10-08: open every one of this sub-tab.
    page.evaluate(
        "(sub) => document.querySelectorAll(`#setform-utama [data-setelan-grup='${sub}'] details.setelan-bagian,"
        " .setelan-form:not([hidden]) details.setelan-bagian`).forEach((d) => { d.open = true; })",
        sub,
    )


def buka_status(page: Page, sub: str) -> None:
    """The Status tab, then one of its sub-tabs (2026-10-05), like `buka_setelan`: only the
    chosen section is visible, and the browser remembers the last one."""
    buka_tab(page, "status")
    page.click(f'#status-sub button[data-sub="{sub}"]')
    expect(page.locator(f'#status-sub button[data-sub="{sub}"]')).to_have_attribute("aria-pressed", "true")
    expect(page.locator(f'#sec-status [data-status-sub="{sub}"]')).to_be_visible()


def setel_scanner(url: str, aktif: bool) -> None:
    """The Scanner QR switch (support, 2026-10-05), set over HTTP like the other settings."""
    with httpx.Client(base_url=url, timeout=10) as c:
        c.post("/api/console/login", json={"email": SUPPORT[0], "sandi": SUPPORT[1]}).raise_for_status()
        c.post("/api/console/dev/scanner-qr", json={"aktif": aktif}).raise_for_status()


def setel_dummy(url: str, aktif: bool) -> None:
    """The Timbangan dummy switch (support, 2026-10-07), set over HTTP like setel_scanner."""
    with httpx.Client(base_url=url, timeout=10) as c:
        c.post("/api/console/login", json={"email": SUPPORT[0], "sandi": SUPPORT[1]}).raise_for_status()
        c.post("/api/console/dev/timbangan-dummy", json={"aktif": aktif}).raise_for_status()
