"""Truk tab: a plate typed by the operator becomes a truck in the list."""

from __future__ import annotations

from langkah import OPERATOR, buka_tab, kamus, masuk, plat
from playwright.sync_api import expect


def test_a_manual_truck_appears_in_the_list(halaman, browser_name):
    nomor = plat(browser_name, 1001)
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "truk")
    expect(halaman.locator("#daftar")).to_be_disabled()
    halaman.fill("#plat", nomor)
    halaman.click("#daftar")
    expect(halaman.locator("#toasts")).to_contain_text(kamus(halaman, "sukDaftar"))
    expect(halaman.locator("#trucks")).to_contain_text(nomor)
