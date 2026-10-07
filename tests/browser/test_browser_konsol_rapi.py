"""Small findings from the #256 review (2026-10-08): the hidden rail and the keyboard, the
more menu and Esc."""

from __future__ import annotations

import re

from langkah import OPERATOR, buka_menu_line, masuk
from playwright.sync_api import expect


def test_tab_never_lands_on_the_hidden_rail(halaman):
    masuk(halaman, OPERATOR)
    halaman.click("#menu-samping")
    expect(halaman.locator("body")).to_have_class(re.compile(r"\bmenu-tutup\b"))
    halaman.wait_for_timeout(500)  # the slide is .28 s; visibility flips at its end
    for _ in range(14):
        halaman.keyboard.press("Tab")
        assert not halaman.evaluate("() => !!document.activeElement.closest('#tabs')")
    # Shown again: the rail is reachable again.
    halaman.click("#menu-samping")
    expect(halaman.locator('#tabs button[data-tab="truk"]')).to_be_visible()


def test_escape_closes_the_more_menu(halaman):
    masuk(halaman, OPERATOR)
    kartu = halaman.locator('#lines .card[data-line="line-1"]')
    buka_menu_line(kartu)
    menu = kartu.locator("details.lagi")
    expect(menu).to_have_attribute("open", "")
    halaman.keyboard.press("Escape")
    expect(menu).not_to_have_attribute("open", "")




def _mode_otomatis(halaman) -> None:
    """`/api/console/state` as the floor sees it with automatic assignment on: one truck on every
    line and one truck waiting. Only the screen is fooled; nothing is assigned on the server."""
    truk = {"truck_id": "t-uji", "plate_number": "BE 5585 TSE", "supplier_name": "PT Sawit Lestari",
            "source_label": "External"}

    def jawab(route):
        r = route.fetch()
        isi = r.json()
        for line in isi.get("lines", []):
            line["assignment"] = dict(truk)
        isi["penugasan_otomatis"] = {**(isi.get("penugasan_otomatis") or {}), "aktif": True}
        isi["antrean_bongkar"] = [{"weighing_id": "w-uji", "plate_number": "BG 7742 ZB", "menit": 3}]
        route.fulfill(response=r, json=isi)

    halaman.route("**/api/console/state", jawab)


def test_truck_card_buttons_fit_their_card_at_1366(halaman):
    """At 1366 x 768 the truck card is a third of the row and, with automatic assignment on,
    half of it is the queue: Lepas and the queue buttons must stay whole and 44 px (review #256),
    not be cut by the card's edge."""
    halaman.set_viewport_size({"width": 1366, "height": 768})
    _mode_otomatis(halaman)
    masuk(halaman, OPERATOR)
    pasangan = [("#truk-di-line", "#truk-di-line .truk-grup button"),
                ("#antrean-bongkar", "#antrean-bongkar .antrean-aksi button")]
    for wadah, pemilih in pasangan:
        kotak = halaman.locator(wadah).bounding_box()
        tombol = halaman.locator(pemilih)
        expect(tombol.first).to_be_visible()
        for i in range(tombol.count()):
            b = tombol.nth(i).bounding_box()
            assert b["height"] >= 44, (pemilih, i)
            assert b["x"] >= kotak["x"] - 0.5 and b["x"] + b["width"] <= kotak["x"] + kotak["width"] + 0.5, (pemilih, b, kotak)
            # One line of text: a label broken over two lines reads as two buttons.
            assert b["height"] < 60, (pemilih, b)
