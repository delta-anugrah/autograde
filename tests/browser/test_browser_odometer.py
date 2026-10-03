"""Tally numbers roll like an odometer (user 2026-10-03, NumberFlow style).

The RIPE count of the shared console is pinned through `page.route` on `/api/console/state`
(the real answer with line-1's `ripe` rewritten and the other lines' set to 0), so the test
decides when the number changes and to what.
"""

from __future__ import annotations

import json

from langkah import OPERATOR, masuk
from playwright.sync_api import expect

_RIPE = "#tot-ripe"
_KARTU = '.card[data-line="line-1"] .counts b[data-k="ripe"]'
# Counts every rolling element put into the two numbers from now on.
_AWASI = """(kartu) => { window.__gulir = 0;
  const o = new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) => {
    if (n.classList && n.classList.contains('odo')) window.__gulir += 1; })));
  [document.querySelector('#tot-ripe'), document.querySelector(kartu)]
    .forEach((el) => o.observe(el, {childList: true})); }"""


def _patok_ripe(halaman) -> dict:
    nilai = {"ripe": 5}

    def jawab(route):
        asli = route.fetch()
        isi = asli.json()
        for baris in isi.get("lines", []):
            baris["ripe"] = nilai["ripe"] if baris.get("line_code") == "line-1" else 0
        route.fulfill(response=asli, body=json.dumps(isi))

    halaman.route("**/api/console/state", jawab)
    return nilai


def test_a_change_rolls_and_ends_on_the_new_value(halaman):
    nilai = _patok_ripe(halaman)
    masuk(halaman, OPERATOR)
    expect(halaman.locator(_RIPE)).to_have_text("5")
    # First write: the plain number, never a roll from the markup's 0.
    expect(halaman.locator(f"{_RIPE} .odo")).to_have_count(0)
    halaman.evaluate(_AWASI, _KARTU)

    nilai["ripe"] = 12
    halaman.evaluate("() => refresh()")
    halaman.wait_for_selector(f"{_RIPE} .odo", state="attached")
    # Mid-roll the text is already the new number (tests and screen readers read it).
    assert halaman.locator(_RIPE).text_content() == "12"
    assert halaman.locator(f"{_RIPE} .odo-d").count() == 2
    expect(halaman.locator(f"{_RIPE} .odo-d[data-masuk]")).to_have_count(1)
    # Then the element is plain text again.
    expect(halaman.locator(f"{_RIPE} .odo")).to_have_count(0)
    expect(halaman.locator(_RIPE)).to_have_text("12")
    expect(halaman.locator(_KARTU)).to_have_text("12")
    expect(halaman.locator(f"{_KARTU} .odo")).to_have_count(0)
    assert halaman.evaluate("() => window.__gulir") == 2

    # Same value on the next polls: nothing rolls again.
    halaman.evaluate("async () => { await refresh(); await refresh(); }")
    assert halaman.evaluate("() => window.__gulir") == 2
    expect(halaman.locator(_RIPE)).to_have_text("12")


def test_reduced_motion_shows_the_new_value_at_once(halaman):
    halaman.emulate_media(reduced_motion="reduce")
    nilai = _patok_ripe(halaman)
    masuk(halaman, OPERATOR)
    expect(halaman.locator(_RIPE)).to_have_text("5")
    halaman.evaluate(_AWASI, _KARTU)
    nilai["ripe"] = 103
    hasil = halaman.evaluate("async () => { await refresh();"
                             " return [document.querySelector('#tot-ripe').innerHTML, window.__gulir]; }")
    assert hasil == ["103", 0], hasil
    expect(halaman.locator(_KARTU)).to_have_text("103")
