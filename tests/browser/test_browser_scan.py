"""Weighbridge gate scan: a known plate fills the form, an unknown one asks for registration,
anything that is not a plate is refused in the screen's words (rule 20).

The QR field ships `hidden` until the mill buys a scanner (the comment above `#scan-keluar`
in `console.html`); today the operator picks the plate from the list, which
`test_browser_timbangan.py` drives. These tests un-hide the field the way that day will, so
the scan path is already proven in both engines when it arrives.
"""

from __future__ import annotations

import re

from langkah import OPERATOR, buka_tab, kamus, masuk, plat
from playwright.sync_api import expect


def _scan(halaman, teks: str) -> None:
    halaman.locator("#scan-plat").evaluate("(el) => { el.hidden = false; }")
    halaman.fill("#scan-plat", teks)
    halaman.press("#scan-plat", "Enter")


def test_a_registered_plate_fills_the_weigh_in(halaman, konsol, browser_name):
    nomor = plat(browser_name, 1002)
    masuk(halaman, OPERATOR)
    daftar = halaman.request.post(konsol.url + "/api/console/trucks", data={"plate_number": nomor})
    assert daftar.status == 201, daftar.text()
    buka_tab(halaman, "timbangan")
    _scan(halaman, nomor)
    expect(halaman.locator("#toasts")).to_contain_text(kamus(halaman, "sukScan"))
    expect(halaman.locator("#plat-timbang")).to_have_attribute("data-nilai", nomor)
    expect(halaman.locator("#bruto")).to_be_focused()


def test_an_unregistered_plate_asks_for_registration(halaman, browser_name):
    nomor = plat(browser_name, 9999)
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")
    _scan(halaman, nomor)
    expect(halaman.locator("#scan-pesan")).to_contain_text(kamus(halaman, "scanBelumAda"))


def test_something_that_is_not_a_plate_is_refused(halaman):
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")
    _scan(halaman, "https://promo.example/qr")
    expect(halaman.locator("#scan-pesan")).to_have_text(kamus(halaman, "err_bukan_plat"))
    expect(halaman.locator("#scan-pesan")).to_have_class(re.compile(r"\bsalah\b"))
