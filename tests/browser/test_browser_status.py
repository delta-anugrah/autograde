"""Status tab, Diagnostics card: the camera temperature and camera health a line reports reach
the support screen, and a line that does not answer shows no number for them."""

from __future__ import annotations

from langkah import SUPPORT, buka_tab, kamus, masuk
from playwright.sync_api import expect


def _baris(halaman, line: str, label: str):
    kartu = halaman.locator(f'#diagnostik-kartu .card[data-line="{line}"]')
    return kartu.locator("dt", has_text=label).locator("xpath=following-sibling::dd[1]")


def test_camera_temperature_on_the_diagnostics_card(halaman):
    masuk(halaman, SUPPORT)
    buka_tab(halaman, "status")
    label = kamus(halaman, "thSuhuKamera")
    expect(_baris(halaman, "line-1", label)).to_have_text("47,3 °C")
    # line-3 is offline: its card says unreachable and has no temperature row at all.
    expect(halaman.locator('#diagnostik-kartu .card.tidak-terjangkau[data-line="line-3"]')).to_be_visible()
    expect(halaman.locator('#diagnostik-kartu .card[data-line="line-3"] dt', has_text=label)).to_have_count(0)


def test_diagnostics_groups_start_closed_and_an_opened_one_stays_open(halaman):
    """The cards are redrawn every 5 s; a group the reader opened must not snap shut."""
    masuk(halaman, SUPPORT)
    buka_tab(halaman, "status")
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
    buka_tab(halaman, "status")
    grup = halaman.locator('#diagnostik-kartu .card[data-line="line-1"] details[data-grup="kamera"]')
    expect(grup).not_to_have_attribute("open", "")
    expect(grup.locator("summary .tanda-waspada")).to_have_text(kamus(halaman, "diagKameraPerluDicek"))
    grup.locator("summary").click()
    hilang = _baris(halaman, "line-1", kamus(halaman, "thFrameHilang"))
    expect(hilang).to_have_text("12 (0,1%)")
    expect(hilang.locator(".tanda-waspada")).to_have_count(1)
    expect(_baris(halaman, "line-1", kamus(halaman, "thPutusKamera"))).to_have_text("0")
