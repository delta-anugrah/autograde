"""Scanner QR switch on the real screen: support turns it on in Setelan, the scan field
appears on the Timbangan tab, and a scan works in it without un-hiding it by hand.

The console lives for the whole session, so every test runs inside `scanner_mati`
(switch OFF before and after, from `conftest.py`): the other scan tests turn it on
themselves (`scanner_nyala`) and must keep starting from the shipped state. That an operator
never sees Setelan is pinned by `test_browser_peran.py`, the 403 by
`tests/e2e/test_scanner_qr_lane.py`.
"""

from __future__ import annotations

from langkah import OPERATOR, SUPPORT, buka_setelan, buka_tab, kamus, masuk, plat, setel_scanner
from playwright.sync_api import expect

_KOLOM = ("#scan-otomatis",)


def _simpan(halaman, nyala: bool) -> None:
    buka_setelan(halaman, "scanner")
    saklar = halaman.locator("#set-scanner")
    expect(saklar).to_be_checked(checked=not nyala)
    saklar.set_checked(nyala)
    halaman.click("#set-scanner-simpan")
    expect(halaman.locator("#toasts")).to_contain_text(kamus(halaman, "scannerTersimpan"))


def test_support_turns_the_switch_on_and_off(halaman, scanner_mati):
    masuk(halaman, SUPPORT)
    buka_tab(halaman, "timbangan")
    for k in _KOLOM:
        expect(halaman.locator(k)).to_be_hidden()

    _simpan(halaman, True)
    buka_tab(halaman, "timbangan")
    for k in _KOLOM:
        expect(halaman.locator(k)).to_be_visible()
    # The fallback stays (rule 20): broken scanner, cracked phone screen, card not printed.
    expect(halaman.locator("#plat-timbang")).to_be_visible()

    _simpan(halaman, False)
    buka_tab(halaman, "timbangan")
    for k in _KOLOM:
        expect(halaman.locator(k)).to_be_hidden()


def test_an_operator_scans_into_the_shown_field(halaman, konsol, scanner_mati, browser_name):
    nomor = plat(browser_name, 1311)
    setel_scanner(konsol.url, True)
    masuk(halaman, OPERATOR)
    daftar = halaman.request.post(konsol.url + "/api/console/trucks", data={"plate_number": nomor})
    assert daftar.status == 201, daftar.text()
    buka_tab(halaman, "timbangan")
    # Shown by the poll, not by the test, and focused: the scanner types without a click.
    expect(halaman.locator("#scan-otomatis")).to_be_focused()
    halaman.keyboard.type(nomor)
    halaman.keyboard.press("Enter")
    expect(halaman.locator("#scan-popup")).to_contain_text(nomor)
    # The arrival is not left waiting for the tests after this one.
    for w in halaman.request.get(konsol.url + "/api/console/weighings").json()["waiting"]:
        if w["plate_number"] == nomor:
            halaman.request.post(konsol.url + f"/api/console/arrivals/{w['id']}/cancel")


def test_another_open_screen_follows_without_a_reload(halaman, konsol, scanner_mati):
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")
    expect(halaman.locator("#scan-otomatis")).to_be_hidden()
    setel_scanner(konsol.url, True)
    # The 2 s state poll un-hides it on a screen nobody touched.
    expect(halaman.locator("#scan-otomatis")).to_be_visible(timeout=10_000)
    setel_scanner(konsol.url, False)
    expect(halaman.locator("#scan-otomatis")).to_be_hidden(timeout=10_000)
