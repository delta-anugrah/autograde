"""Status tab, Diagnostics card: the camera temperature a line reports reaches the support
screen, and a line that does not answer shows no number for it."""

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
