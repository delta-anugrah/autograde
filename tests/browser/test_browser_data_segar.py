"""Fresh data without a manual refresh, taps never lost (batch 5.3, 5.4, 5.8, 6.4).

A kiosk runs for days and nobody reloads it. The poll must leave what did not change alone
(a tap that lands during a rewrite is lost), run one pull at a time, say when its numbers
are old, take new trucks into lists that are already on screen, and load the page again by
itself after an update.
"""

from __future__ import annotations

import json
import re

import httpx
import pytest
from langkah import OPERATOR, SUPPORT, buka_tab, kamus, masuk, plat
from playwright.sync_api import expect

# The screen polls every 2 s; generous for a slow CI runner.
POLL_MAKS_MS = 15_000


def _patok_grading(halaman) -> None:
    """Two grading rows out of 60, whatever the clock says: just after midnight the seeded
    console has no bunch for the new working day yet, and an empty table has no row to keep."""
    baris = [
        {"timestamp": f"2026-10-04T08:0{n}:00+07:00", "line_code": "line-1", "plate_number": "BE 1 AA",
         "source_label": "Internal", "ripeness_status": "ACC", "grade_class": "Ripe", "image_url": None}
        for n in (1, 2)
    ]
    halaman.route(
        "**/api/console/history*",
        lambda route: route.fulfill(json={"work_date": "2026-10-04", "items": baris, "total": 60}),
    )


def test_two_polls_leave_the_card_buttons_and_the_grading_rows_in_place(halaman):
    """The element a finger is on must still be the same element after the poll."""
    _patok_grading(halaman)
    masuk(halaman, OPERATOR)
    expect(halaman.locator("#recent tr td.no").first).to_be_visible()

    sama = halaman.evaluate(
        """async () => {
          await refresh();
          const kartu = document.querySelector('#lines .card[data-line="line-1"]');
          const lama = {
            baris: document.querySelector("#recent tr"),
            piston: kartu.querySelector("button.piston"),
            lepas: kartu.querySelector(".slot-lepas button"),
            truk: kartu.querySelector(".truk > span"),
            nomor: document.querySelector("#grading-nomor button"),
          };
          await refresh(); await refresh();
          return {
            baris: document.querySelector("#recent tr") === lama.baris,
            piston: kartu.querySelector("button.piston") === lama.piston,
            lepas: kartu.querySelector(".slot-lepas button") === lama.lepas,
            truk: kartu.querySelector(".truk > span") === lama.truk,
            nomor: document.querySelector("#grading-nomor button") === lama.nomor,
            ada: Object.values(lama).every(Boolean),
          };
        }"""
    )

    assert sama == {"baris": True, "piston": True, "lepas": True, "truk": True, "nomor": True, "ada": True}


def test_the_piston_shortcut_hint_survives_the_slot(halaman):
    masuk(halaman, OPERATOR)
    kartu = halaman.locator('#lines .card[data-line="line-1"]')
    expect(kartu.locator("button.piston")).to_be_visible()
    urut = halaman.evaluate("() => urutan.indexOf('line-1') + 1")

    halaman.evaluate("async () => { await refresh(); await refresh(); }")

    expect(kartu.locator("button.piston .pintas")).to_have_text(f"P+{urut}")
    lebar = halaman.evaluate(
        """() => { const k = document.querySelector('#lines .card[data-line="line-1"] .aksi-line');
          return [...k.querySelectorAll("button")].map((b) => Math.round(b.getBoundingClientRect().width)); }"""
    )
    assert len(lebar) == 2 and abs(lebar[0] - lebar[1]) <= 1, lebar


def test_three_failed_polls_grey_the_numbers_and_one_good_poll_brings_them_back(halaman):
    masuk(halaman, OPERATOR)
    segar = halaman.locator("#segar")
    expect(segar).to_be_visible(timeout=POLL_MAKS_MS)
    pola = kamus(halaman, "segarPada").replace("{jam}", r"\d\d:\d\d:\d\d")
    expect(segar).to_have_text(re.compile(f"^{pola}$"))
    expect(halaman.locator("body")).not_to_have_attribute("data-basi", "1")

    halaman.route("**/api/console/state", lambda route: route.abort())
    try:
        expect(halaman.locator("body")).to_have_attribute("data-basi", "1", timeout=POLL_MAKS_MS)
        basi = kamus(halaman, "basiSejak").replace("{jam}", r"\d\d:\d\d:\d\d")
        expect(segar).to_have_text(re.compile(f"^{basi}$"))
        expect(segar).to_have_attribute("data-basi", "1")
        redup = halaman.evaluate(
            """() => [getComputedStyle(document.querySelector("#tally")).opacity,
                     getComputedStyle(document.querySelector("#lines .counts")).opacity,
                     getComputedStyle(document.querySelector("#lines .feed")).opacity]"""
        )
        assert float(redup[0]) < 1 and float(redup[1]) < 1, redup
        assert float(redup[2]) == 1, "the camera picture comes from the line and stays as it is"
    finally:
        halaman.unroute("**/api/console/state")

    expect(halaman.locator("body")).not_to_have_attribute("data-basi", "1", timeout=POLL_MAKS_MS)
    expect(segar).to_have_text(re.compile(f"^{pola}$"))


def test_timer_ticks_never_stack_a_second_request_on_a_slow_console(halaman):
    masuk(halaman, OPERATOR)

    selama, sesudah = halaman.evaluate(
        """async () => {
          await refresh();
          const asli = window.fetch;
          let n = 0, lepas;
          window.fetch = (u, o) => {
            if (!String(u).includes("/api/console/state")) return asli(u, o);
            n++;
            return new Promise((jawab) => { lepas = () => jawab(asli(u, o)); });
          };
          try {
            detakRefresh(); detakRefresh(); detakRefresh();
            await new Promise((r) => setTimeout(r, 100));
            const selama = n;
            lepas();
            await new Promise((r) => setTimeout(r, 100));
            return [selama, kunciRefresh.sibuk()];
          } finally { window.fetch = asli; }
        }"""
    )

    assert selama == 1, "three ticks while one pull is in flight are one request"
    assert sesudah is False


def test_a_truck_registered_elsewhere_reaches_the_card_list_without_a_reload(halaman, konsol, browser_name):
    masuk(halaman, OPERATOR)
    kartu = halaman.locator('#lines .card[data-line="line-2"]')
    pemilih = kartu.locator(".assign .pilih")
    expect(pemilih).to_be_visible()
    nomor = plat(browser_name, 5301)
    halaman.evaluate("() => { window.__halamanIni = true; }")

    with httpx.Client(base_url=konsol.url, timeout=10) as c:
        c.post("/api/console/login", json={"email": OPERATOR[0], "sandi": OPERATOR[1]}).raise_for_status()
        c.post("/api/console/trucks", json={"plate_number": nomor}).raise_for_status()

    # The 60 s truck poll, run now.
    halaman.evaluate("() => muatTrucks()")
    expect(pemilih.locator('[role="option"]', has_text=nomor)).to_have_count(1)
    assert halaman.evaluate("() => window.__halamanIni") is True, "no reload was needed"

    pemilih.locator(".pilih-tombol").click()
    pemilih.locator('[role="option"]', has_text=nomor).click()
    expect(pemilih.locator(".pilih-teks")).to_have_text(nomor)
    halaman.evaluate("async () => { await muatTrucks(); await refresh(); }")
    expect(pemilih.locator(".pilih-teks")).to_have_text(nomor)


def test_an_open_card_list_is_not_rebuilt_until_it_is_closed(halaman, konsol, browser_name):
    masuk(halaman, OPERATOR)
    pemilih = halaman.locator('#lines .card[data-line="line-2"] .assign .pilih')
    pemilih.locator(".pilih-tombol").click()
    expect(pemilih.locator(".pilih-panel")).to_be_visible()
    nomor = plat(browser_name, 5302)
    with httpx.Client(base_url=konsol.url, timeout=10) as c:
        c.post("/api/console/login", json={"email": OPERATOR[0], "sandi": OPERATOR[1]}).raise_for_status()
        c.post("/api/console/trucks", json={"plate_number": nomor}).raise_for_status()

    halaman.evaluate("async () => { await muatTrucks(); await refresh(); }")

    expect(pemilih.locator(".pilih-panel")).to_be_visible()
    expect(pemilih.locator('[role="option"]', has_text=nomor)).to_have_count(0)

    halaman.keyboard.press("Escape")
    expect(pemilih.locator(".pilih-panel")).to_be_hidden()
    # Closed: the next 2 s poll brings the list up to date.
    expect(pemilih.locator('[role="option"]', has_text=nomor)).to_have_count(1, timeout=POLL_MAKS_MS)


def _ganti_versi(halaman, versi: str) -> None:
    def jawab(route):
        asli = route.fetch()
        isi = asli.json()
        isi["versi"] = versi
        route.fulfill(response=asli, body=json.dumps(isi))

    halaman.route("**/api/console/state", jawab)


def test_the_page_loads_itself_again_when_the_console_version_changes(halaman):
    masuk(halaman, OPERATOR)
    expect(halaman.locator("#segar")).to_be_visible(timeout=POLL_MAKS_MS)
    halaman.evaluate("() => { window.__halamanLama = true; }")

    _ganti_versi(halaman, "v99.0.0-uji")
    try:
        halaman.wait_for_function("() => window.__halamanLama === undefined", timeout=POLL_MAKS_MS)
        # The new page starts from the new version: it does not reload a second time.
        expect(halaman.locator("#segar")).to_be_visible(timeout=POLL_MAKS_MS)
        halaman.evaluate("() => { window.__halamanBaru = true; }")
        halaman.evaluate("async () => { await refresh(); await refresh(); }")
        assert halaman.evaluate("() => window.__halamanBaru") is True
        expect(halaman.locator("#keluar")).to_be_visible()
    finally:
        halaman.unroute("**/api/console/state")


def test_the_reload_waits_until_an_open_dialog_is_closed(halaman):
    masuk(halaman, OPERATOR)
    expect(halaman.locator("#info-sistem")).to_be_visible(timeout=POLL_MAKS_MS)
    halaman.click("#info-sistem")
    expect(halaman.locator("#info-sistem-modal")).to_be_visible()
    halaman.evaluate("() => { window.__halamanLama = true; }")

    _ganti_versi(halaman, "v99.0.1-uji")
    try:
        halaman.evaluate("async () => { await refresh(); await refresh(); }")
        assert halaman.evaluate("() => window.__halamanLama") is True, "never under an open dialog"
        halaman.keyboard.press("Escape")
        halaman.wait_for_function("() => window.__halamanLama === undefined", timeout=POLL_MAKS_MS)
    finally:
        halaman.unroute("**/api/console/state")


def test_the_refresh_button_pulls_everything_and_says_so(halaman):
    masuk(halaman, OPERATOR)
    tombol = halaman.locator("#segarkan")
    expect(tombol).to_be_visible()
    expect(tombol).to_have_attribute("aria-label", kamus(halaman, "tombolSegarkan"))
    diminta: list[str] = []
    halaman.on("request", lambda r: diminta.append(r.url.split("/api/console/")[-1].split("?")[0]))

    tombol.click()

    expect(halaman.locator("#toasts .toast.sukses", has_text=kamus(halaman, "sukSegarkan"))).to_be_visible()
    assert {"state", "trucks", "weighings", "history"} <= set(diminta), diminta


def test_the_refresh_button_says_when_the_console_does_not_answer(halaman):
    masuk(halaman, OPERATOR)
    halaman.route("**/api/console/state", lambda route: route.abort())
    try:
        halaman.click("#segarkan")
        expect(halaman.locator("#toasts .toast.gagal", has_text=kamus(halaman, "gagalSegarkan"))).to_be_visible()
    finally:
        halaman.unroute("**/api/console/state")


_TEKS_TAB = "(s) => document.querySelector(s).innerText"


@pytest.mark.parametrize("tab", ["rekap", "akun"])
def test_a_language_flip_redraws_the_open_tab(halaman, tab):
    """The tab after a flip reads like the same tab loaded fresh in that language. Akun (like
    Log and Status) is drawn in JS and kept the old words until it was opened again."""
    masuk(halaman, SUPPORT)
    buka_tab(halaman, tab)
    bagian = f"#sec-{tab}"
    try:
        # What the tab looks like in English, loaded fresh.
        halaman.click("#bahasa")
        expect(halaman.locator("#bahasa-teks")).to_have_text("ID")
        halaman.evaluate("(t) => MUAT_TAB[t]()", tab)
        acuan = halaman.evaluate(_TEKS_TAB, bagian)
        halaman.click("#bahasa")
        expect(halaman.locator("#bahasa-teks")).to_have_text("EN")
        halaman.evaluate("(t) => MUAT_TAB[t]()", tab)
        assert halaman.evaluate(_TEKS_TAB, bagian) != acuan, "the tab reads differently in Indonesian"

        halaman.click("#bahasa")

        halaman.wait_for_function(
            "([s, a]) => document.querySelector(s).innerText === a", arg=[bagian, acuan], timeout=POLL_MAKS_MS
        )
    finally:
        if halaman.locator("#bahasa-teks").inner_text() == "ID":
            halaman.click("#bahasa")
        expect(halaman.locator("#bahasa-teks")).to_have_text("EN")
