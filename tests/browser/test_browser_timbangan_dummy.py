"""Dummy scale on the real screen (2026-10-07): support turns it on in Settings > Developer
Mode, the orange band shows on every tab, and a scan saves 30,000 kg gross with no typed box.

The console lives for the whole session, so the switch goes back OFF in a `finally`: later
tests must start from the shipped state.
"""

from __future__ import annotations

import pytest
from langkah import SUPPORT, buka_setelan, buka_tab, kamus, masuk, plat, setel_dummy
from playwright.sync_api import expect

pytestmark = pytest.mark.usefixtures("scanner_nyala", "penugasan_bersih")


def _simpan(halaman, nyala: bool) -> None:
    buka_setelan(halaman, "dev")
    saklar = halaman.locator("#set-dummy")
    expect(saklar).to_be_checked(checked=not nyala)
    saklar.set_checked(nyala)
    halaman.click("#set-dummy-simpan")
    expect(halaman.locator("#toasts")).to_contain_text(kamus(halaman, "dummyTersimpan"))


def _scan(halaman, teks: str) -> None:
    kolom = halaman.locator("#scan-otomatis")
    expect(kolom).to_be_focused()
    halaman.evaluate("() => { scanTerakhir = { qr: '', pada: 0 }; }")
    halaman.keyboard.type(teks)
    halaman.keyboard.press("Enter")


def _jawab(halaman, ya: bool) -> None:
    dialog = halaman.locator("#konfirmasi-modal")
    expect(dialog).to_be_visible()
    halaman.click("#konfirmasi-ya" if ya else "#konfirmasi-tidak")
    expect(dialog).to_be_hidden()


def test_support_turns_the_dummy_scale_on_and_a_scan_saves_30000(halaman, konsol, browser_name):
    nomor = plat(browser_name, 1501)
    try:
        masuk(halaman, SUPPORT)
        daftar = halaman.request.post(konsol.url + "/api/console/trucks", data={"plate_number": nomor})
        assert daftar.status == 201, daftar.text()
        pita = halaman.locator("#pita-dummy")
        expect(pita).to_be_hidden()

        _simpan(halaman, True)
        expect(pita).to_be_visible()
        expect(pita).to_have_text(kamus(halaman, "pitaTimbanganDummy"))
        buka_tab(halaman, "grading")
        expect(pita).to_be_visible()

        buka_tab(halaman, "timbangan")
        expect(halaman.locator("#timbang-keadaan")).to_have_text(kamus(halaman, "timbangDummy"))
        _scan(halaman, nomor)
        expect(halaman.locator("#toasts")).to_contain_text(f"{kamus(halaman, 'sukDatang')} {nomor}")
        _scan(halaman, nomor)
        _jawab(halaman, ya=True)
        # No typed box: the dummy gross is saved by the scan itself.
        expect(halaman.locator("#bruto")).not_to_be_focused()
        baris = halaman.locator("#sec-timbangan tr", has_text=nomor)
        expect(baris.first).to_contain_text("30.000")

        _simpan(halaman, False)
        expect(pita).to_be_hidden(timeout=3_000)
    finally:
        setel_dummy(konsol.url, False)
