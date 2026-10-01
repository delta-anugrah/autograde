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
    # The sentence names the plate (the operator registers exactly that one), and the form
    # stays empty: a borrowed truck is weighed only after it is registered.
    expect(halaman.locator("#scan-pesan")).to_have_text(f"{kamus(halaman, 'scanBelumAda')} {nomor}")
    expect(halaman.locator("#plat-timbang")).to_have_attribute("data-nilai", "")


def test_something_that_is_not_a_plate_is_refused(halaman):
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")
    _scan(halaman, "https://promo.example/qr")
    expect(halaman.locator("#scan-pesan")).to_have_text(kamus(halaman, "err_bukan_plat"))
    expect(halaman.locator("#scan-pesan")).to_have_class(re.compile(r"\bsalah\b"))


def test_a_truck_missing_from_a_list_that_will_not_load_is_not_reported_as_scanned(halaman, konsol, browser_name):
    # The truck list answers without the plate (a list that failed to refresh), staged by
    # Playwright: the screen must say so instead of "scanned" over an empty plate field.
    nomor = plat(browser_name, 1005)
    masuk(halaman, OPERATOR)
    daftar = halaman.request.post(konsol.url + "/api/console/trucks", data={"plate_number": nomor})
    assert daftar.status == 201, daftar.text()
    halaman.route(
        konsol.url + "/api/console/trucks",
        lambda route: route.fulfill(json={"items": []}) if route.request.method == "GET" else route.fallback(),
    )
    buka_tab(halaman, "timbangan")
    _scan(halaman, nomor)
    expect(halaman.locator("#scan-pesan")).to_have_text(kamus(halaman, "scanDaftarBelumMuat"))
    expect(halaman.locator("#plat-timbang")).to_have_attribute("data-nilai", "")


def test_an_inactive_truck_is_named_inactive(halaman, konsol, browser_name):
    # The server marks a retired truck (`truck.status`, tests/unit/test_scan_plat.py); the
    # answer is staged here because no screen can retire a truck.
    nomor = plat(browser_name, 1006)
    jawaban = {
        "ditemukan": True,
        "plate_number": nomor,
        "truck": {"id": "x", "plate_number": nomor, "status": "inactive"},
    }
    masuk(halaman, OPERATOR)
    halaman.route(konsol.url + "/api/console/scan", lambda route: route.fulfill(json=jawaban))
    buka_tab(halaman, "timbangan")
    _scan(halaman, nomor)
    expect(halaman.locator("#scan-pesan")).to_contain_text(kamus(halaman, "scanTrukNonaktif"))
    expect(halaman.locator("#plat-timbang")).to_have_attribute("data-nilai", "")
