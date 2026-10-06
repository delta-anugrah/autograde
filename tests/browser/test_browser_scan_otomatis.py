"""The one scan field on the real screen (user 2026-10-06): scan only, and the console records
the next step of the visit from the truck's state.

The test console has no scale (`SCALE_PLC_REGISTER` empty), so both weight steps open the
typed box, the fallback the mill uses until the PLC register is known; saving the live
weight is pinned in `tests/unit/test_scan_otomatis_service.py`. Every scan here comes within
3 minutes of the previous step, so steps 1 to 3 ask the double-read question first.

The console lives for the whole session: every test runs inside `scanner_nyala` (switch
back OFF after) and `penugasan_bersih`, and every truck it weighs in is weighed out and leaves.
"""

from __future__ import annotations

import re

import pytest
from langkah import JEDA_HALAMAN_MS, OPERATOR, SUPPORT, buka_tab, kamus, masuk, plat
from playwright.sync_api import expect

pytestmark = pytest.mark.usefixtures("scanner_nyala", "penugasan_bersih")

_SALAH = re.compile(r"\bsalah\b")
_BUKAN_PLAT = "https://promo.example/qr"


def _daftar(halaman, nomor: str) -> None:
    """On the Truk tab, which redraws every plate picker at once."""
    buka_tab(halaman, "truk")
    halaman.fill("#plat", nomor)
    halaman.click("#daftar")
    expect(halaman.locator("#trucks")).to_contain_text(nomor)
    buka_tab(halaman, "timbangan")


def _scan(halaman, teks: str, *, baca_ulang: bool = False) -> None:
    """What the scanner does: type into the focused field, then Enter. The screen drops the
    same QR read again within 2 s; a test scans faster than a person, so it forgets the last
    read unless the test is about that drop."""
    kolom = halaman.locator("#scan-otomatis")
    expect(kolom).to_be_focused()
    if not baca_ulang:
        halaman.evaluate("() => { scanTerakhir = { qr: '', pada: 0 }; }")
    halaman.keyboard.type(teks)
    halaman.keyboard.press("Enter")


def _jawab(halaman, ya: bool) -> None:
    dialog = halaman.locator("#konfirmasi-modal")
    expect(dialog).to_be_visible()
    halaman.click("#konfirmasi-ya" if ya else "#konfirmasi-tidak")
    expect(dialog).to_be_hidden()


def _toast(halaman, kunci: str, nomor: str) -> None:
    expect(halaman.locator("#toasts")).to_contain_text(f"{kamus(halaman, kunci)} {nomor}".strip())


def _tiket(halaman, konsol, nomor: str) -> list[dict]:
    items = halaman.request.get(konsol.url + "/api/console/weighings").json()["items"]
    return [w for w in items if w["plate_number"] == nomor]


def test_four_scans_make_one_visit(halaman, konsol, browser_name):
    nomor = plat(browser_name, 1401)
    masuk(halaman, OPERATOR)
    _daftar(halaman, nomor)
    pesan = halaman.locator("#scan-otomatis-pesan")

    _scan(halaman, nomor.lower())
    _toast(halaman, "sukDatang", nomor)

    _scan(halaman, nomor)
    _jawab(halaman, ya=True)
    # No scale: the plate is picked and the cursor waits in Bruto.
    expect(halaman.locator("#plat-timbang")).to_have_attribute("data-nilai", nomor)
    expect(halaman.locator("#bruto")).to_be_focused()
    expect(pesan).to_contain_text(nomor)
    halaman.keyboard.type("14000")
    halaman.keyboard.press("Enter")
    _toast(halaman, "sukMasuk", "")
    expect(halaman.locator("#scan-otomatis")).to_be_focused()
    expect(pesan).to_have_text("")

    _scan(halaman, nomor)
    _jawab(halaman, ya=True)
    expect(halaman.locator("#tara-plat")).to_have_text(nomor)
    expect(halaman.locator("#tara-nilai")).to_be_focused()
    halaman.keyboard.type("6000")
    halaman.keyboard.press("Enter")
    _toast(halaman, "sukTara", "")
    expect(halaman.locator("#scan-otomatis")).to_be_focused()

    # Keluar never asks: an early leave time is harmless.
    _scan(halaman, nomor)
    _toast(halaman, "sukPergi", nomor)
    expect(halaman.locator("#konfirmasi-modal")).to_be_hidden()
    [tiket] = _tiket(halaman, konsol, nomor)
    assert (tiket["gross_kg"], tiket["tare_kg"], tiket["net_kg"]) == (14000, 6000, 8000), tiket
    assert tiket["left_at"] and tiket["arrived_at"], tiket


def test_a_double_read_is_dropped_or_asked_and_writes_nothing(halaman, konsol, browser_name):
    nomor = plat(browser_name, 1402)
    masuk(halaman, OPERATOR)
    _daftar(halaman, nomor)
    _scan(halaman, nomor)
    _toast(halaman, "sukDatang", nomor)

    # The same QR again at once: dropped by the screen, nothing asked, nothing sent.
    _scan(halaman, nomor, baca_ulang=True)
    halaman.wait_for_timeout(JEDA_HALAMAN_MS)
    expect(halaman.locator("#konfirmasi-modal")).to_be_hidden()

    # Later than 2 s but within 3 min: the server asks; Batal records nothing.
    _scan(halaman, nomor)
    _jawab(halaman, ya=False)
    expect(halaman.locator("#bruto")).not_to_be_focused()
    assert _tiket(halaman, konsol, nomor) == []
    waiting = halaman.request.get(konsol.url + "/api/console/weighings").json()["waiting"]
    datang = [w for w in waiting if w["plate_number"] == nomor]
    assert len(datang) == 1, datang
    halaman.request.post(konsol.url + f"/api/console/arrivals/{datang[0]['id']}/cancel")


def test_not_a_plate_is_refused_and_the_field_is_cleared(halaman):
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")
    _scan(halaman, _BUKAN_PLAT)
    pesan = halaman.locator("#scan-otomatis-pesan")
    expect(pesan).to_have_text(kamus(halaman, "err_bukan_plat"))
    expect(pesan).to_have_class(_SALAH)
    expect(halaman.locator("#scan-otomatis")).to_have_value("")


def test_an_unregistered_truck_may_arrive_but_is_not_weighed(halaman, konsol, browser_name):
    nomor = plat(browser_name, 1403)
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")
    _scan(halaman, nomor)
    _toast(halaman, "sukDatang", nomor)
    _scan(halaman, nomor)
    _jawab(halaman, ya=True)
    pesan = halaman.locator("#scan-otomatis-pesan")
    expect(pesan).to_contain_text(kamus(halaman, "scanBelumAda"))
    expect(pesan).to_have_class(_SALAH)
    assert _tiket(halaman, konsol, nomor) == []
    waiting = halaman.request.get(konsol.url + "/api/console/weighings").json()["waiting"]
    for w in waiting:
        if w["plate_number"] == nomor:
            halaman.request.post(konsol.url + f"/api/console/arrivals/{w['id']}/cancel")


def test_the_field_keeps_the_focus_but_never_takes_it_from_a_typed_box(halaman, browser_name):
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")
    kolom = halaman.locator("#scan-otomatis")
    expect(kolom).to_be_focused()
    # A click on empty page space gives it back.
    halaman.click("#sec-timbangan .tabel")
    expect(kolom).to_be_focused()
    # The bruto box keeps the focus across polls while the operator types.
    halaman.click("#bruto")
    halaman.keyboard.type("12")
    halaman.wait_for_timeout(2_500)
    expect(halaman.locator("#bruto")).to_be_focused()
    halaman.fill("#bruto", "")
    # Another tab: the hidden field takes nothing.
    buka_tab(halaman, "truk")
    expect(kolom).not_to_be_focused()
    buka_tab(halaman, "timbangan")
    expect(kolom).to_be_focused()


def test_a_card_picker_follows_an_automatic_assignment(halaman, konsol, lines, browser_name):
    nomor = plat(browser_name, 1404)
    masuk(halaman, SUPPORT)  # the auto-assign switch is support's
    _daftar(halaman, nomor)
    r = halaman.request.post(konsol.url + "/api/console/dev/auto-assign",
                             data={"aktif": True, "lines": ["line-1"]})
    assert r.status == 200, r.text()
    truk = next(t for t in halaman.request.get(konsol.url + "/api/console/trucks").json()["items"]
                if t["plate_number"] == nomor)
    pilih = halaman.locator('#lines .card[data-line="line-1"] .assign .pilih')

    _scan(halaman, nomor)
    _toast(halaman, "sukDatang", nomor)
    _scan(halaman, nomor)
    _jawab(halaman, ya=True)
    expect(halaman.locator("#bruto")).to_be_focused()
    halaman.keyboard.type("14000")
    halaman.keyboard.press("Enter")
    _toast(halaman, "sukMasuk", "")
    # Put on line-1 by the weigh-in, not by a pick on the card: the card's picker follows.
    expect(pilih).to_have_attribute("data-nilai", truk["id"], timeout=10_000)

    _scan(halaman, nomor)
    _jawab(halaman, ya=True)
    expect(halaman.locator("#tara-nilai")).to_be_focused()
    halaman.keyboard.type("6000")
    halaman.keyboard.press("Enter")
    _toast(halaman, "sukTara", "")
    _scan(halaman, nomor)
    _toast(halaman, "sukPergi", nomor)
