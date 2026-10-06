"""Status tab: its sub-tabs (2026-10-05), and the Diagnostics card, where the camera
temperature and camera health a line reports reach the support screen and a line that does not
answer shows no number for them. Also the shared sub-tab width and the Log filter colours."""

from __future__ import annotations

import re

import pytest
from langkah import SUPPORT, buka_status, kamus, masuk
from playwright.sync_api import expect


def _baris(halaman, line: str, label: str):
    kartu = halaman.locator(f'#diagnostik-kartu .card[data-line="{line}"]')
    return kartu.locator("dt", has_text=label).locator("xpath=following-sibling::dd[1]")


def test_camera_temperature_on_the_diagnostics_card(halaman):
    masuk(halaman, SUPPORT)
    buka_status(halaman, "diagnostik")
    label = kamus(halaman, "thSuhuKamera")
    expect(_baris(halaman, "line-1", label)).to_have_text("47,3 °C")
    # line-3 is offline: its card says unreachable and has no temperature row at all.
    expect(halaman.locator('#diagnostik-kartu .card.tidak-terjangkau[data-line="line-3"]')).to_be_visible()
    expect(halaman.locator('#diagnostik-kartu .card[data-line="line-3"] dt', has_text=label)).to_have_count(0)


def test_diagnostics_groups_start_closed_and_an_opened_one_stays_open(halaman):
    """The cards are redrawn every 5 s; a group the reader opened must not snap shut."""
    masuk(halaman, SUPPORT)
    buka_status(halaman, "diagnostik")
    grup = halaman.locator('#diagnostik-kartu .card[data-line="line-1"] details[data-grup="mesin"]')
    expect(grup).not_to_have_attribute("open", "")
    grup.locator("summary").click()
    expect(grup).to_have_attribute("open", "")
    halaman.evaluate("() => muatDiagnostik()")
    expect(grup).to_have_attribute("open", "")
    # Same group on the other card; a group nobody opened stays closed.
    expect(halaman.locator('#diagnostik-kartu .card[data-line="line-2"] details[data-grup="mesin"]')).to_have_attribute("open", "")
    expect(halaman.locator('#diagnostik-kartu .card[data-line="line-1"] details[data-grup="data"]')).not_to_have_attribute("open", "")
    grup.locator("summary").click()
    expect(grup).not_to_have_attribute("open", "")


def test_camera_health_rows_and_the_closed_group_flags_a_problem(halaman):
    """Lost frames are graded on the line; the screen colours the row and flags the group
    header, which stays visible while the group is closed."""
    masuk(halaman, SUPPORT)
    buka_status(halaman, "diagnostik")
    grup = halaman.locator('#diagnostik-kartu .card[data-line="line-1"] details[data-grup="kamera"]')
    expect(grup).not_to_have_attribute("open", "")
    expect(grup.locator("summary .tanda-waspada")).to_have_text(kamus(halaman, "diagKameraPerluDicek"))
    grup.locator("summary").click()
    hilang = _baris(halaman, "line-1", kamus(halaman, "thFrameHilang"))
    expect(hilang).to_have_text("12 (0,1%)")
    expect(hilang.locator(".tanda-waspada")).to_have_count(1)
    expect(_baris(halaman, "line-1", kamus(halaman, "thPutusKamera"))).to_have_text("0")


_BAGIAN = ("versi", "diagnostik", "antrean-line", "antrean-erp", "manifest")


def test_status_sub_tabs_show_one_section_and_remember_it(halaman):
    """Sub-tabs since 2026-10-05: one section visible at a time, the choice kept on reload."""
    masuk(halaman, SUPPORT)
    for sub in _BAGIAN:
        buka_status(halaman, sub)
        for lain in _BAGIAN:
            if lain != sub:
                expect(halaman.locator(f'#sec-status [data-status-sub="{lain}"]')).to_be_hidden()
    halaman.reload()
    expect(halaman.locator("#keluar")).to_be_visible()
    expect(halaman.locator("#sec-status")).to_be_visible()
    expect(halaman.locator('#status-sub button[data-sub="manifest"]')).to_have_attribute("aria-pressed", "true")
    expect(halaman.locator('#sec-status [data-status-sub="manifest"]')).to_be_visible()
    expect(halaman.locator('#sec-status [data-status-sub="versi"]')).to_be_hidden()


def test_sub_tab_bars_are_as_wide_as_the_main_tab_bar(halaman):
    """User 2026-10-05: every sub-tab bar spans the main tab bar's width exactly."""
    halaman.set_viewport_size({"width": 1600, "height": 1000})
    masuk(halaman, SUPPORT)
    utama = None
    for tab, bar in (("status", "#status-sub"), ("setelan", "#setelan-sub"), ("line", "#line-sub"),
                     ("rekap", ".riwayat-tampilan")):
        halaman.click(f'#tabs [data-tab="{tab}"]')
        expect(halaman.locator(bar)).to_be_visible()
        if utama is None:
            utama = halaman.locator("#tabs").evaluate(
                "(el) => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);"
                " return [r.left + parseFloat(s.paddingLeft), r.right - parseFloat(s.paddingRight)]; }")
        kotak = halaman.locator(bar).bounding_box()
        assert abs(kotak["x"] - utama[0]) <= 1, (tab, kotak, utama)
        assert abs(kotak["x"] + kotak["width"] - utama[1]) <= 1, (tab, kotak, utama)


@pytest.mark.parametrize("lebar", [1280, 1600, 1920])
def test_settings_sub_tabs_stay_on_one_row(halaman, lebar):
    """User 2026-10-06: with Scanner QR there are eight sub-tabs, all on one row, Danger Zone
    included, from 1280 px up."""
    halaman.set_viewport_size({"width": lebar, "height": 1000})
    masuk(halaman, SUPPORT)
    halaman.click('#tabs [data-tab="setelan"]')
    tombol = halaman.locator("#setelan-sub button")
    expect(tombol.first).to_be_visible()
    atas = {round(tombol.nth(i).bounding_box()["y"]) for i in range(tombol.count())}
    assert len(atas) == 1, (lebar, atas)


def test_log_filters_are_outlined_in_their_colour_when_chosen(halaman):
    """User 2026-10-05: outlined, never filled, each in its level's colour, no tick."""
    masuk(halaman, SUPPORT)
    halaman.click('#tabs [data-tab="log"]')
    warna = halaman.evaluate("""() => { const s = getComputedStyle(document.documentElement);
      const v = (n) => { const el = document.createElement('i'); el.style.color = s.getPropertyValue(n);
        document.body.append(el); const c = getComputedStyle(el).color; el.remove(); return c; };
      return {"": v('--fg'), WARNING: v('--warn'), ERROR: v('--rej')}; }""")
    for dipilih in ("WARNING", "ERROR", ""):
        halaman.click(f'#log-level button[data-nilai="{dipilih}"]')
        expect(halaman.locator(f'#log-level button[data-nilai="{dipilih}"]')).to_have_class(re.compile(r"\baktif\b"))
        for nilai, rgb in warna.items():
            tombol = halaman.locator(f'#log-level button[data-nilai="{nilai}"]')
            expect(tombol).to_have_css("background-color", "rgba(0, 0, 0, 0)")
            expect(tombol).to_have_css("border-top-color", rgb)
            expect(tombol).to_have_css("color", rgb)
            assert tombol.evaluate("(el) => getComputedStyle(el, '::before').content") in ("none", "normal")


def test_top_bar_buttons_show_a_tooltip_on_hover(halaman):
    """One tooltip component (2026-10-05): the sentence follows the language and shows on hover."""
    masuk(halaman, SUPPORT)
    tombol = halaman.locator("#segarkan")
    expect(tombol).to_have_attribute("data-tip", kamus(halaman, "tipSegarkan"))
    isi = "(el) => getComputedStyle(el, '::after').content"
    assert tombol.evaluate(isi) in ("none", "normal"), "nothing drawn before the hover"
    tombol.hover()
    halaman.wait_for_function("() => { const g = getComputedStyle(document.querySelector('#segarkan'), '::after');"
                              " return g.content.includes(document.querySelector('#segarkan').dataset.tip) && g.opacity === '1'; }")
    halaman.click("#bahasa")
    expect(halaman.locator("#keluar")).to_have_attribute("data-tip", kamus(halaman, "tipKeluar"))
