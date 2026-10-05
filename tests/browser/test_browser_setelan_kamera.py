"""Tab Line, Setelan Kamera: the values a line's camera reports reach the support screen; an offline line
says why instead of showing nothing."""

from __future__ import annotations

from langkah import SUPPORT, buka_tab, kamus, masuk
from playwright.sync_api import expect


def test_camera_settings_of_each_line(halaman):
    masuk(halaman, SUPPORT)
    buka_tab(halaman, "line")
    halaman.click('#line-sub [data-sub="setelan-kamera"]')
    kartu = halaman.locator('#setelan-kamera-kartu .card[data-line="line-1"]')
    label = kamus(halaman, "setelanKamera_exposure")
    expect(kartu.locator("dt", has_text=label).locator("xpath=following-sibling::dd[1]")).to_contain_text("4.000 µs")
    expect(kartu).to_contain_text(kamus(halaman, "setelanKameraBaku"))
    # line-3 is offline in the browser session: its card gives the reason, no rows.
    expect(halaman.locator('#setelan-kamera-kartu .card.tidak-terjangkau[data-line="line-3"]')).to_be_visible()
