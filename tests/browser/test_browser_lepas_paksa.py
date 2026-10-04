"""Lepas paksa on a line card (2026-10-04): a line that stops answering while it holds a truck.

The fake line-1 is told to stop answering. The card swaps Lepas for Lepas paksa, the press
asks in red, the console clears the truck on its own and says so with a warning toast. The
line was only cut off and still holds the truck in memory: once it answers again, the
console sends the release once more, by itself.
"""

from __future__ import annotations

import time

import httpx
from langkah import OPERATOR, kamus, masuk, plat
from playwright.sync_api import expect

# LineStatusWorker reads every line each second and the screen polls every 2 s: a silent
# line shows within a few seconds; generous for a slow CI runner.
KARTU_BERUBAH_MS = 15_000
LINE_MENDENGAR_S = 15.0


def _tugaskan(konsol, nomor: str) -> str:
    """A truck on line-1 through the API, the line still answering (rule 13)."""
    with httpx.Client(base_url=konsol.url, timeout=10) as c:
        c.post("/api/console/login", json={"email": OPERATOR[0], "sandi": OPERATOR[1]}).raise_for_status()
        truk = c.post("/api/console/trucks", json={"plate_number": nomor})
        truk.raise_for_status()
        truck_id = truk.json()["id"]
        c.post("/api/console/lines/line-1/assign-truck", json={"truck_id": truck_id}).raise_for_status()
    return truck_id


def _tunggu(syarat, batas_s: float) -> bool:
    akhir = time.monotonic() + batas_s
    while time.monotonic() < akhir:
        if syarat():
            return True
        time.sleep(0.2)
    return syarat()


def test_a_silent_line_is_released_on_the_console_then_told_when_it_answers(
    halaman, lines, konsol, penugasan_bersih, browser_name
):
    line = lines["line-1"]
    nomor = plat(browser_name, 1501)
    truck_id = _tugaskan(konsol, nomor)
    assert line.truk == truck_id
    masuk(halaman, OPERATOR)
    kartu = halaman.locator('#lines .card[data-line="line-1"]')
    expect(kartu.locator(".truk")).to_contain_text(nomor)
    expect(kartu.locator('button[data-aksi="lepas"]')).to_be_enabled()

    line.atur_diam(True)
    try:
        tombol = kartu.locator('button[data-aksi="lepas-paksa"]')
        expect(tombol).to_be_visible(timeout=KARTU_BERUBAH_MS)
        expect(tombol).to_have_text(kamus(halaman, "btnLepasPaksa"))
        expect(tombol).to_have_class("bahaya pekat")
        expect(kartu.locator('button[data-aksi="lepas"]')).to_have_count(0)

        tombol.click()
        nama_line = kartu.locator(".nama").inner_text().strip()
        expect(halaman.locator("#konfirmasi-modal")).to_be_visible()
        expect(halaman.locator("#konfirmasi-judul")).to_have_text(
            kamus(halaman, "konfirmasiLepasPaksaJudul").replace("{line}", nama_line)
        )
        expect(halaman.locator("#konfirmasi-pesan")).to_contain_text(nomor)
        expect(halaman.locator("#konfirmasi-ya")).to_have_class("bahaya pekat")
        halaman.click("#konfirmasi-ya")

        # By its text: signing in also announces older automatic releases as warnings.
        pesan = kamus(halaman, "sukLepasPaksa").replace("{line}", nama_line)
        expect(halaman.locator("#toasts .toast.peringatan", has_text=pesan)).to_be_visible()
        expect(kartu.locator(".truk .truk-kosong")).to_be_visible()
        expect(kartu.locator('button[data-aksi="lepas"]')).to_be_disabled()
        assert line.truk == truck_id, "cut off, the line still holds the departed truck"
    finally:
        line.atur_diam(False)

    # Back on the wire: the console notices the truck in the line's status and releases it.
    assert _tunggu(lambda: line.truk is None, LINE_MENDENGAR_S), "the release was never sent again"
    terkirim = [isi for jalur, isi in line.diterima if jalur == "/internal/assignment"]
    assert terkirim[-1]["truck_id"] == "", terkirim[-1]


def test_cancel_keeps_the_truck_on_the_card(halaman, lines, konsol, penugasan_bersih, browser_name):
    line = lines["line-1"]
    nomor = plat(browser_name, 1502)
    truck_id = _tugaskan(konsol, nomor)
    masuk(halaman, OPERATOR)
    kartu = halaman.locator('#lines .card[data-line="line-1"]')

    line.atur_diam(True)
    try:
        tombol = kartu.locator('button[data-aksi="lepas-paksa"]')
        expect(tombol).to_be_visible(timeout=KARTU_BERUBAH_MS)
        tombol.click()
        halaman.click("#konfirmasi-tidak")
        expect(halaman.locator("#konfirmasi-modal")).to_be_hidden()
        expect(kartu.locator(".truk")).to_contain_text(nomor)
    finally:
        line.atur_diam(False)

    # Answering again, the card offers the normal Lepas and the line kept its truck.
    expect(kartu.locator('button[data-aksi="lepas"]')).to_be_enabled(timeout=KARTU_BERUBAH_MS)
    assert line.truk == truck_id
