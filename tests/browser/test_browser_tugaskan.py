"""Assigning a truck on a line card: the line accepts first (rule 13), then the card shows it.

The truck is registered through the Truk tab, not the API: only the screen's own register
re-renders the three card pickers at once (the 60 s truck poll would come later).
"""

from __future__ import annotations

from langkah import OPERATOR, buka_tab, kamus, masuk, plat
from playwright.sync_api import expect


def test_a_truck_assigned_on_line_1_reaches_the_line_and_the_card(halaman, lines, browser_name):
    nomor = plat(browser_name, 1004)
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "truk")
    halaman.fill("#plat", nomor)
    halaman.click("#daftar")
    expect(halaman.locator("#trucks")).to_contain_text(nomor)

    buka_tab(halaman, "grading")
    kartu = halaman.locator('#lines .card[data-line="line-1"]')
    kartu.locator(".pilih-tombol").click()
    kartu.locator('[role="option"]', has_text=nomor).click()
    kartu.locator('[data-aksi="tugaskan"]').click()

    nama_line = kartu.locator(".nama").inner_text().strip()
    expect(halaman.locator("#toasts")).to_contain_text(kamus(halaman, "sukTugaskan").replace("{line}", nama_line))
    expect(kartu.locator(".truk")).to_contain_text(nomor)
    # By plate: the fake lines live for the whole session, and a local two-browser run
    # would otherwise accept the other browser's assignment.
    terkirim = [isi for jalur, isi in lines["line-1"].diterima if jalur == "/internal/assignment"]
    assert any(isi.get("plate") == nomor for isi in terkirim), terkirim
