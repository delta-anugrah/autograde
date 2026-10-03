"""Weighbridge exit scan: the plate finds today's open ticket and opens its tare box; no open
ticket is said, and two open tickets are refused, never guessed (rule 20, operator's
decision 2026-09-15: a guess can put the tare on the wrong visit).

`#scan-keluar` ships `hidden` until the mill buys a scanner, like `#scan-plat` in
`test_browser_scan.py`; these tests un-hide it the way that day will.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from langkah import OPERATOR, buka_tab, kamus, masuk, plat
from playwright.sync_api import expect

# The row's number cells, in order: gross, tare, net (`barisTimbangan` in console.html).
_NETO = 2


def _daftar(halaman, konsol, nomor: str) -> None:
    r = halaman.request.post(konsol.url + "/api/console/trucks", data={"plate_number": nomor})
    assert r.status == 201, r.text()


def _timbang_masuk(halaman, konsol, nomor: str, *, menit_lalu: int = 0) -> None:
    """A weigh-in the way the screen sends it; a ticket is keyed by plate and entry time."""
    masuk_pada = (datetime.now(UTC) - timedelta(minutes=menit_lalu)).isoformat()
    r = halaman.request.post(
        konsol.url + "/api/console/weighings",
        data={"plate_number": nomor, "gross_kg": "14000", "entered_at": masuk_pada},
    )
    assert r.status == 201, r.text()


def _scan_keluar(halaman, teks: str) -> None:
    halaman.locator("#scan-keluar").evaluate("(el) => { el.hidden = false; }")
    halaman.fill("#scan-keluar", teks)
    halaman.press("#scan-keluar", "Enter")


def test_an_exit_scan_opens_the_tare_box_of_the_open_ticket(halaman, konsol, browser_name):
    nomor = plat(browser_name, 1007)
    masuk(halaman, OPERATOR)
    _daftar(halaman, konsol, nomor)
    _timbang_masuk(halaman, konsol, nomor)
    buka_tab(halaman, "timbangan")
    _scan_keluar(halaman, nomor)
    expect(halaman.locator("#tara-grup")).to_be_visible()
    expect(halaman.locator("#tara-plat")).to_have_text(nomor)
    halaman.fill("#tara-nilai", "6000")
    halaman.click("#tara-simpan")
    expect(halaman.locator("#toasts")).to_contain_text(kamus(halaman, "sukTara"))
    baris = halaman.locator("#timbangan tr", has_text=nomor)
    expect(baris.locator("td.num").nth(_NETO)).to_have_text(halaman.evaluate("() => kg(8000)"))


def test_an_exit_scan_without_an_open_ticket_says_so(halaman, konsol, browser_name):
    nomor = plat(browser_name, 1008)
    masuk(halaman, OPERATOR)
    _daftar(halaman, konsol, nomor)
    buka_tab(halaman, "timbangan")
    _scan_keluar(halaman, nomor)
    expect(halaman.locator("#scan-keluar-pesan")).to_have_text(f"{kamus(halaman, 'scanTakAdaTiket')} {nomor}")
    expect(halaman.locator("#tara-grup")).to_be_hidden()


def test_two_open_tickets_are_refused_not_guessed(halaman, konsol, browser_name):
    nomor = plat(browser_name, 1009)
    masuk(halaman, OPERATOR)
    _daftar(halaman, konsol, nomor)
    _timbang_masuk(halaman, konsol, nomor, menit_lalu=30)
    _timbang_masuk(halaman, konsol, nomor)
    buka_tab(halaman, "timbangan")
    _scan_keluar(halaman, nomor)
    expect(halaman.locator("#scan-keluar-pesan")).to_have_text(f"{kamus(halaman, 'scanGanda')} {nomor}")
    expect(halaman.locator("#tara-grup")).to_be_hidden()
