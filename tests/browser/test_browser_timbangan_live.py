"""The scale tile: weight on the weighbridge now, read from the PLC (2026-10-06).

The browser console has no PLC, so the real server answers "not connected"; the other
states are played by routing `/api/console/scale/live`.
"""

from __future__ import annotations

from langkah import OPERATOR, kamus, masuk
from playwright.sync_api import expect

# The tile polls every second; generous for a slow CI runner.
POLL_MAKS_MS = 10_000


def test_without_a_plc_register_the_tile_says_not_connected(halaman):
    masuk(halaman, OPERATOR)
    kotak = halaman.locator("#timbang")
    expect(kotak).to_have_attribute("data-keadaan", "tidak_dipakai", timeout=POLL_MAKS_MS)
    expect(halaman.locator("#timbang-keadaan")).to_have_text(kamus(halaman, "timbangTidakDipakai"))
    expect(halaman.locator("#timbang-kg")).to_have_text("-")
    # Today's total stays on the small line.
    expect(halaman.locator("#tot-tiket")).not_to_be_empty()


def test_live_weight_then_a_cut_connection_shows_a_dash(halaman):
    jawaban = {"badan": {"keadaan": "stabil", "kg": 24310, "umur_detik": 0.2}}

    def layani(route):
        if jawaban["badan"] is None:
            route.abort()  # the console does not answer at all
        else:
            route.fulfill(json=jawaban["badan"])

    halaman.route("**/api/console/scale/live", layani)
    masuk(halaman, OPERATOR)

    expect(halaman.locator("#timbang")).to_have_attribute("data-keadaan", "stabil", timeout=POLL_MAKS_MS)
    expect(halaman.locator("#timbang-kg")).to_have_text(halaman.evaluate("() => kg(24310)") + " kg")
    expect(halaman.locator("#timbang-keadaan")).to_have_text(kamus(halaman, "timbangStabil"))

    jawaban["badan"] = {"keadaan": "bergerak", "kg": 24120, "umur_detik": 0.1}
    expect(halaman.locator("#timbang")).to_have_attribute("data-keadaan", "bergerak", timeout=POLL_MAKS_MS)

    # The console stops answering: never a frozen number, the tile says offline.
    jawaban["badan"] = None
    expect(halaman.locator("#timbang")).to_have_attribute("data-keadaan", "putus", timeout=POLL_MAKS_MS)
    expect(halaman.locator("#timbang-kg")).to_have_text("-")
    expect(halaman.locator("#timbang-keadaan")).to_have_text(kamus(halaman, "timbangPutus"))
