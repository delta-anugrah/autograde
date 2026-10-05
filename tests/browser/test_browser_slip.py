"""Printable grading slip (batch 5.9): support switches it on in Settings, every account's
Rekap truck rows then offer Print, and the slip prints alone.

The console and its data live for the whole session, so the switch is put back off after
every test. `window.print` is replaced by a recorder: a real print dialog would block.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from langkah import OPERATOR, SUPPORT, buka_tab, kamus, keluar, masuk
from playwright.sync_api import expect

_CETAK = '#riwayat-baris button[data-cetak]'


def _atur_slip(konsol, aktif: bool) -> None:
    with httpx.Client(base_url=konsol.url, timeout=10) as c:
        c.post("/api/console/login", json={"email": SUPPORT[0], "sandi": SUPPORT[1]}).raise_for_status()
        c.post("/api/console/dev/slip", json={"aktif": aktif}).raise_for_status()


@pytest.fixture
def slip_mati(konsol) -> Iterator[None]:
    _atur_slip(konsol, False)
    yield
    _atur_slip(konsol, False)


def _rekap_tujuh_hari(halaman) -> None:
    """"7 hari": the seeder keeps every visit in the past (see `test_browser_rekap.py`)."""
    buka_tab(halaman, "rekap")
    halaman.click('.riwayat-cepat button[data-cepat="7hari"]')
    expect(halaman.locator("#riwayat-baris td.key").first).to_be_visible()


def test_support_switches_it_on_and_an_operator_prints_one_truck(halaman, slip_mati):
    masuk(halaman, SUPPORT)
    buka_tab(halaman, "setelan")
    halaman.evaluate("() => MUAT_TAB.setelan()")
    expect(halaman.locator("#set-slip")).not_to_be_checked()
    halaman.check("#set-slip")
    halaman.click("#set-slip-simpan")
    expect(halaman.locator("#toasts .toast.sukses", has_text=kamus(halaman, "slipTersimpan"))).to_be_visible()
    keluar(halaman)

    masuk(halaman, OPERATOR)
    _rekap_tujuh_hari(halaman)
    tombol = halaman.locator(_CETAK).first
    expect(tombol).to_have_text(kamus(halaman, "btnCetakSlip"))
    plat = tombol.locator("xpath=ancestor::tr").locator("td.key").inner_text().strip()
    halaman.evaluate("() => { window.__dicetak = 0; window.print = () => { window.__dicetak++; }; }")

    tombol.click()

    halaman.wait_for_function("() => window.__dicetak === 1")
    slip = halaman.locator("#slip-cetak")
    expect(slip.locator("h1")).to_have_text(kamus(halaman, "slipJudul"))
    expect(slip).to_contain_text(plat)
    expect(slip).to_contain_text(kamus(halaman, "slipRasio"))
    expect(slip).to_be_hidden()

    # On paper the slip is alone: no cameras, no tabs, no table.
    halaman.emulate_media(media="print")
    try:
        expect(slip).to_be_visible()
        expect(halaman.locator("#lines")).to_be_hidden()
        expect(halaman.locator("#tabs")).to_be_hidden()
        expect(halaman.locator("#sec-rekap")).to_be_hidden()
    finally:
        halaman.emulate_media(media="screen")
    halaman.evaluate("() => window.dispatchEvent(new Event('afterprint'))")
    assert halaman.evaluate("() => document.body.dataset.cetak") is None


def test_no_print_button_while_the_switch_is_off(halaman, slip_mati):
    masuk(halaman, OPERATOR)
    _rekap_tujuh_hari(halaman)
    expect(halaman.locator("#riwayat-baris button[data-lihat]").first).to_be_visible()
    expect(halaman.locator(_CETAK)).to_have_count(0)


def test_the_button_follows_the_switch_without_a_reload(halaman, konsol, slip_mati):
    masuk(halaman, OPERATOR)
    _rekap_tujuh_hari(halaman)
    expect(halaman.locator(_CETAK)).to_have_count(0)

    _atur_slip(konsol, True)

    # The 2 s poll carries the switch; the open Rekap table is drawn again.
    expect(halaman.locator(_CETAK).first).to_be_visible(timeout=10_000)


def test_the_qr_card_print_still_works_after_a_slip(halaman, konsol, slip_mati):
    _atur_slip(konsol, True)
    masuk(halaman, OPERATOR)
    _rekap_tujuh_hari(halaman)
    halaman.evaluate("() => { window.print = () => {}; }")
    halaman.locator(_CETAK).first.click()
    halaman.wait_for_function("() => document.body.dataset.cetak === 'slip'")
    halaman.evaluate("() => window.dispatchEvent(new Event('afterprint'))")

    buka_tab(halaman, "truk")
    halaman.emulate_media(media="print")
    try:
        expect(halaman.locator("#sec-truk")).to_be_visible()
        expect(halaman.locator("#slip-cetak")).to_be_hidden()
    finally:
        halaman.emulate_media(media="screen")
