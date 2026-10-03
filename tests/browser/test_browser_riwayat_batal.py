"""Riwayat Batal datang under the Timbangan table (round 4, user 2026-10-03).

A cancel through the UI shows up in a collapsible "Kedatangan dibatalkan (n)" panel with
the plate, the arrival and cancel times and the operator's email; the panel is hidden while
the day has none; its open state survives the poll.

The console lives for the whole session and other tests cancel arrivals too, so these tests
assert on their own rows, never on the count. The empty and open-state cases replace only
the `dibatalkan` list of the real answer, so they do not depend on what else ran.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from langkah import OPERATOR, buka_tab, kamus, masuk, plat
from playwright.sync_api import Route, expect

# One definition of the cancel click flow (two clicks today), shared with the round 3 tests.
from test_browser_batal_datang import _batal_dua_klik

_RUTE_TIMBANGAN = re.compile(r".*/api/console/weighings(\?.*)?$")


def _judul_pola(halaman) -> re.Pattern[str]:
    return re.compile(re.escape(kamus(halaman, "riwayatBatalJudul")).replace(r"\{n\}", r"\d+"))


def _ganti_daftar_batal(halaman, wadah: dict) -> None:
    """Serve the real /weighings answer with `dibatalkan` replaced by `wadah["daftar"]`."""

    def ganti(route: Route) -> None:
        if route.request.method != "GET":
            route.fallback()
            return
        jawaban = route.fetch()
        isi = jawaban.json()
        isi["dibatalkan"] = wadah["daftar"]
        route.fulfill(response=jawaban, json=isi)

    halaman.route(_RUTE_TIMBANGAN, ganti)


def _baris_palsu(nomor: str, oleh: str = "op@pks.test") -> dict:
    jam = datetime.now(UTC).replace(microsecond=0).isoformat()
    return {"plate_number": nomor, "arrived_at": jam, "cancelled_at": jam, "cancelled_by": oleh}


def test_cancel_through_the_ui_lists_plate_times_and_operator(halaman, konsol, browser_name, penugasan_bersih):
    nomor = plat(browser_name, 1401)
    masuk(halaman, OPERATOR)
    r = halaman.request.post(konsol.url + "/api/console/trucks", data={"plate_number": nomor})
    assert r.status == 201, r.text()
    r = halaman.request.post(konsol.url + "/api/console/arrivals",
                             data={"qr": nomor, "at": datetime.now(UTC).isoformat()})
    assert r.json()["hasil"] == "tercatat", r.text()
    buka_tab(halaman, "timbangan")
    halaman.evaluate("() => muatTimbangan()")

    _batal_dua_klik(halaman, nomor)

    panel = halaman.locator("#riwayat-batal")
    expect(panel).to_be_visible()
    expect(panel.locator("summary")).to_have_text(_judul_pola(halaman))
    panel.locator("summary").click()
    baris = halaman.locator("#riwayat-batal-isi tr", has_text=nomor)
    expect(baris).to_have_count(1)

    [simpan] = [b for b in halaman.request.get(konsol.url + "/api/console/weighings").json()["dibatalkan"]
                if b["plate_number"] == nomor]
    sel = baris.locator("td")
    expect(sel.nth(0)).to_have_text(nomor)
    expect(sel.nth(1)).to_have_text(halaman.evaluate("(iso) => waktu(iso)", simpan["arrived_at"]))
    expect(sel.nth(2)).to_have_text(halaman.evaluate("(iso) => waktu(iso)", simpan["cancelled_at"]))
    expect(sel.nth(3)).to_have_text(OPERATOR[0])
    # Not the pinned row-button column of the table above (round 3 trap: global rules on cells).
    assert sel.nth(3).evaluate("(el) => getComputedStyle(el).position") == "static"


def test_panel_is_hidden_while_the_day_has_no_cancelled_arrival(halaman, browser_name):
    wadah = {"daftar": [_baris_palsu(plat(browser_name, 1402))]}
    _ganti_daftar_batal(halaman, wadah)
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")
    halaman.evaluate("() => muatTimbangan()")
    expect(halaman.locator("#riwayat-batal")).to_be_visible()

    wadah["daftar"] = []
    halaman.evaluate("() => muatTimbangan()")
    expect(halaman.locator("#riwayat-batal")).to_be_hidden()


def test_open_panel_stays_open_across_polls_and_escapes_server_text(halaman, browser_name):
    satu = _baris_palsu(plat(browser_name, 1403), oleh='<img src=x onerror="window.kena=1">')
    wadah = {"daftar": [satu]}
    _ganti_daftar_batal(halaman, wadah)
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")
    halaman.evaluate("() => muatTimbangan()")
    panel = halaman.locator("#riwayat-batal")
    panel.locator("summary").click()
    expect(panel).to_have_attribute("open", "")

    # The same answer again, then a changed one: the panel stays open both times.
    halaman.evaluate("() => muatTimbangan()")
    expect(panel).to_have_attribute("open", "")
    wadah["daftar"] = [_baris_palsu(plat(browser_name, 1404)), satu]
    halaman.evaluate("() => muatTimbangan()")
    expect(halaman.locator("#riwayat-batal-isi tr")).to_have_count(2)
    expect(panel).to_have_attribute("open", "")
    expect(panel.locator("summary")).to_have_text(kamus(halaman, "riwayatBatalJudul").replace("{n}", "2"))

    oleh = halaman.locator("#riwayat-batal-isi tr", has_text=satu["plate_number"]).locator("td").nth(3)
    expect(oleh).to_have_text(satu["cancelled_by"])
    assert halaman.evaluate("() => window.kena") is None
