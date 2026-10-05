"""Sliding session (batch 5.7): a touch keeps the operator in, a ribbon warns 15 minutes
before the end, and the screen's own polls never renew anything.

The end is moved on the page (`aturSisaSesi`), not by waiting 12 hours; every renew is the
real `POST /api/console/session/renew` against the real console.
"""

from __future__ import annotations

import re

from langkah import JEDA_HALAMAN_MS, OPERATOR, kamus, masuk
from playwright.sync_api import expect

_RENEW = "/api/console/session/renew"
DETIK_SESI = 12 * 60 * 60
# The watch runs every second.
PANTAU_MAKS_MS = 5_000


def _catat_renew(halaman) -> list[str]:
    dikirim: list[str] = []
    halaman.on("request", lambda r: dikirim.append(r.method) if r.url.endswith(_RENEW) else None)
    return dikirim


def test_ten_minutes_left_shows_the_ribbon_and_the_button_renews(halaman):
    masuk(halaman, OPERATOR)
    pita = halaman.locator("#pita-sesi")
    expect(pita).to_be_hidden()

    halaman.evaluate("() => aturSisaSesi(600)")

    expect(pita).to_be_visible()
    expect(halaman.locator("#pita-sesi-teks")).to_have_text(kamus(halaman, "sesiAkanHabis").replace("{menit}", "10"))
    expect(halaman.locator("#pita-sesi-perpanjang")).to_have_text(kamus(halaman, "btnPerpanjangSesi"))
    with halaman.expect_response(lambda r: r.url.endswith(_RENEW)) as jawab:
        halaman.click("#pita-sesi-perpanjang")
    assert jawab.value.status == 200 and jawab.value.json()["sisa_detik"] == DETIK_SESI

    expect(halaman.locator("#toasts .toast.sukses", has_text=kamus(halaman, "sukPerpanjangSesi"))).to_be_visible()
    expect(pita).to_be_hidden()
    sisa = halaman.evaluate("() => (sesiBerakhirPada - Date.now()) / 1000")
    assert DETIK_SESI - 30 < sisa <= DETIK_SESI


def test_any_touch_near_the_end_renews_without_the_button(halaman):
    masuk(halaman, OPERATOR)
    halaman.evaluate("() => aturSisaSesi(600)")
    expect(halaman.locator("#pita-sesi")).to_be_visible()

    with halaman.expect_response(lambda r: r.url.endswith(_RENEW), timeout=PANTAU_MAKS_MS) as jawab:
        halaman.locator("#tally").click()

    assert jawab.value.status == 200
    expect(halaman.locator("#pita-sesi")).to_be_hidden()
    # The background renew says nothing: the operator did not ask for it.
    expect(halaman.locator("#toasts .toast", has_text=kamus(halaman, "sukPerpanjangSesi"))).to_have_count(0)


def test_polls_alone_never_renew(halaman):
    masuk(halaman, OPERATOR)
    dikirim = _catat_renew(halaman)
    halaman.evaluate("() => aturSisaSesi(600)")

    # Several 2 s polls and several 1 s watches go by, nobody touches the screen.
    halaman.evaluate("async () => { await refresh(); await refresh(); await muatTrucks(); await muatTimbangan(); }")
    halaman.wait_for_timeout(3 * 1000 + JEDA_HALAMAN_MS)

    assert dikirim == []
    expect(halaman.locator("#pita-sesi")).to_be_visible()


def test_a_touch_right_after_sign_in_does_not_renew_again(halaman):
    masuk(halaman, OPERATOR)
    dikirim = _catat_renew(halaman)

    halaman.locator("#tally").click()
    halaman.keyboard.press("Shift")
    halaman.wait_for_timeout(2 * 1000 + JEDA_HALAMAN_MS)

    assert dikirim == [], "a sign-in counts as a renew"


def test_the_end_asks_the_server_first_and_keeps_a_session_that_is_still_live(halaman):
    masuk(halaman, OPERATOR)

    halaman.evaluate("() => aturSisaSesi(0)")

    halaman.wait_for_function(
        f"() => sesiBerakhirPada !== null && sesiBerakhirPada - Date.now() > {DETIK_SESI - 120} * 1000",
        timeout=PANTAU_MAKS_MS,
    )
    expect(halaman.locator("#gerbang")).to_be_hidden()


def test_an_ended_session_brings_the_gate_back(halaman, konsol):
    masuk(halaman, OPERATOR)
    # The polls go quiet first, so the gate can only come from the end-of-session check, and
    # the pulls the sign-in started are let finish before the session goes.
    expect(halaman.locator("#segar")).to_be_visible(timeout=PANTAU_MAKS_MS)
    for jalur in ("state", "trucks", "weighings", "history*"):
        halaman.route(f"**/api/console/{jalur}", lambda route: route.abort())
    halaman.wait_for_load_state("networkidle")
    # The server forgets the session (as 12 idle hours would); the page still counts down.
    halaman.request.post(konsol.url + "/api/console/logout")
    expect(halaman.locator("#gerbang")).to_be_hidden()

    halaman.evaluate("() => aturSisaSesi(0)")

    expect(halaman.locator("#gerbang")).to_be_visible(timeout=PANTAU_MAKS_MS)
    expect(halaman.locator("#pita-sesi")).to_be_hidden()
    assert halaman.evaluate("() => sesiBerakhirPada") is None


def test_the_ribbon_reads_in_english_too(halaman):
    masuk(halaman, OPERATOR)
    halaman.click("#bahasa")
    try:
        halaman.evaluate("() => aturSisaSesi(14 * 60 + 5)")
        expect(halaman.locator("#pita-sesi-teks")).to_have_text(re.compile(r"\b15 min\b"))
        expect(halaman.locator("#pita-sesi-perpanjang")).to_have_text("Extend")
    finally:
        halaman.click("#bahasa")
