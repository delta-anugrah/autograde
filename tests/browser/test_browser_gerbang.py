"""The four gate steps on the Timbangan tab (user's decision 2026-09-30): 1 Datang, 2 Timbang
isi, 3 Timbang kosong, 4 Keluar, each its own labelled side, because the console never guesses
which step a scan is (scan 1 may be skipped).

Without a scanner (the four QR fields ship `hidden`), step 1 is the truck picker plus "Catat
datang" and step 4 is the Keluar button on the ticket row. The scan tests un-hide a field the
way the day the scanner arrives will, as `test_browser_scan.py` does.

The console lives for the whole session, so every truck weighed in here is weighed out and
leaves, and every arrival is claimed by a weigh-in: an open ticket stays in the table and in
the unloading queue, and an unclaimed arrival stays in the waiting list of step 1.
"""

from __future__ import annotations

import re

import pytest
from langkah import OPERATOR, buka_tab, kamus, masuk, plat
from playwright.sync_api import expect

# Cells of a ticket row (`barisTimbangan` in console.html).
_ANTRE, _TOTAL = 2, 4
_SALAH = re.compile(r"\bsalah\b")
_BUKAN_PLAT = "https://promo.example/qr"
_LANGKAH = ("lbDatang", "lbGerbangMasuk", "lbGerbangKeluar", "lbPergi")
_KOLOM_SCAN = ("#scan-datang", "#scan-plat", "#scan-keluar", "#scan-pergi")


def _daftar(halaman, nomor: str) -> None:
    """On the Truk tab, which redraws both plate pickers at once."""
    buka_tab(halaman, "truk")
    halaman.fill("#plat", nomor)
    halaman.click("#daftar")
    expect(halaman.locator("#trucks")).to_contain_text(nomor)
    buka_tab(halaman, "timbangan")


def _pilih(halaman, id_pilih: str, nomor: str) -> None:
    pilih = halaman.locator(id_pilih)
    pilih.locator(".pilih-tombol").click()
    pilih.locator('[role="option"]', has_text=nomor).click()
    expect(pilih).to_have_attribute("data-nilai", nomor)


def _isi(halaman, nomor: str) -> None:
    _pilih(halaman, "#plat-timbang", nomor)
    halaman.fill("#bruto", "14000")
    halaman.click("#masuk")
    expect(halaman.locator("#toasts")).to_contain_text(kamus(halaman, "sukMasuk"))


def _baris(halaman, nomor: str):
    return halaman.locator("#timbangan tr", has_text=nomor)


def _kosong(halaman, nomor: str) -> None:
    _baris(halaman, nomor).locator('button[data-aksi="keluar"]').click()
    expect(halaman.locator("#tara-plat")).to_have_text(nomor)
    halaman.fill("#tara-nilai", "6000")
    halaman.click("#tara-simpan")
    expect(halaman.locator("#toasts")).to_contain_text(kamus(halaman, "sukTara"))


def _pergi(halaman, nomor: str) -> None:
    baris = _baris(halaman, nomor)
    tombol = baris.locator('button[data-aksi="pergi"]')
    expect(tombol).to_have_text(kamus(halaman, "btnPergi"))
    tombol.click()
    expect(halaman.locator("#toasts")).to_contain_text(f"{kamus(halaman, 'sukPergi')} {nomor}")
    expect(baris.locator("button[data-aksi]")).to_have_count(0)


def _scan(halaman, kolom: str, teks: str) -> None:
    halaman.locator(kolom).evaluate("(el) => { el.hidden = false; }")
    halaman.fill(kolom, teks)
    halaman.press(kolom, "Enter")


def test_four_labelled_steps_and_two_new_columns(halaman):
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")
    for kunci in _LANGKAH:
        expect(halaman.locator(f'#sec-timbangan [data-t="{kunci}"]')).to_have_text(kamus(halaman, kunci))
    for kolom in _KOLOM_SCAN:
        expect(halaman.locator(kolom)).to_be_hidden()
    expect(halaman.locator("#sec-timbangan thead th")).to_have_count(11)
    for kunci in ("thAntre", "thTotal"):
        expect(halaman.locator(f'#sec-timbangan th[data-t="{kunci}"]')).to_have_text(kamus(halaman, kunci))
    expect(halaman.locator("#petunjuk-pergi")).to_have_text(kamus(halaman, "hintPergi"))


def test_arrival_by_picker_then_weigh_in_shows_queue_minutes(halaman, browser_name, penugasan_bersih):
    nomor = plat(browser_name, 1201)
    masuk(halaman, OPERATOR)
    _daftar(halaman, nomor)
    expect(halaman.locator("#datang")).to_be_disabled()
    _pilih(halaman, "#plat-datang", nomor)
    expect(halaman.locator("#datang")).to_be_enabled()
    halaman.click("#datang")
    expect(halaman.locator("#toasts")).to_contain_text(f"{kamus(halaman, 'sukDatang')} {nomor}")
    expect(halaman.locator("#antre")).to_contain_text(nomor)
    # The picker empties once the arrival is recorded, so a second press cannot repeat it.
    expect(halaman.locator("#plat-datang")).to_have_attribute("data-nilai", "")
    expect(halaman.locator("#datang")).to_be_disabled()

    _isi(halaman, nomor)
    expect(halaman.locator("#antre")).not_to_contain_text(nomor)
    sel = _baris(halaman, nomor).locator("td")
    expect(sel.nth(_ANTRE)).to_have_text(halaman.evaluate("() => teksMenit(0)"))
    expect(sel.nth(_ANTRE)).to_have_attribute("title", re.compile("^" + re.escape(kamus(halaman, "jamDatang"))))
    expect(sel.nth(_TOTAL)).to_have_text("-")

    _kosong(halaman, nomor)
    _pergi(halaman, nomor)


def test_weigh_out_then_leave_fills_the_total(halaman, browser_name, penugasan_bersih):
    nomor = plat(browser_name, 1202)
    masuk(halaman, OPERATOR)
    _daftar(halaman, nomor)
    _isi(halaman, nomor)
    baris = _baris(halaman, nomor)
    sel = baris.locator("td")
    # No scan 1: marked, never "0 mnt" (D4).
    tanda = sel.nth(_ANTRE).locator(".tag")
    expect(tanda).to_have_text(kamus(halaman, "antreKelewat"))
    expect(tanda).to_have_attribute("title", kamus(halaman, "antreKelewatJudul"))
    expect(baris.locator('button[data-aksi="keluar"]')).to_have_text(kamus(halaman, "btnTimbangKosong"))
    expect(sel.nth(_TOTAL)).to_have_text("-")

    _kosong(halaman, nomor)
    expect(baris.locator('button[data-aksi="keluar"]')).to_have_count(0)
    _pergi(halaman, nomor)
    expect(sel.nth(_TOTAL)).to_have_text(re.compile(r"^\d+ mnt$"))
    expect(sel.nth(_TOTAL)).to_have_attribute("title", re.compile("^" + re.escape(kamus(halaman, "jamPergi"))))


def test_leaving_before_weigh_out_is_refused_and_nothing_is_written(halaman, konsol, browser_name, penugasan_bersih):
    nomor = plat(browser_name, 1203)
    masuk(halaman, OPERATOR)
    _daftar(halaman, nomor)
    _isi(halaman, nomor)

    _scan(halaman, "#scan-pergi", nomor)
    pesan = halaman.locator("#scan-pergi-pesan")
    expect(pesan).to_contain_text(kamus(halaman, "pergiBelumKosong"))
    expect(pesan).to_have_class(_SALAH)
    tiket = [w for w in halaman.request.get(konsol.url + "/api/console/weighings").json()["items"]
             if w["plate_number"] == nomor]
    assert len(tiket) == 1 and tiket[0]["left_at"] is None, tiket
    expect(_baris(halaman, nomor).locator('button[data-aksi="keluar"]')).to_have_count(1)

    _kosong(halaman, nomor)
    _pergi(halaman, nomor)
    # A fresh scan 4 after the truck left is a warning, not a second leave.
    _scan(halaman, "#scan-pergi", nomor)
    expect(pesan).to_contain_text(kamus(halaman, "pergiSudah"))


def test_arrival_scanned_twice_then_while_inside(halaman, browser_name, penugasan_bersih):
    nomor = plat(browser_name, 1204)
    masuk(halaman, OPERATOR)
    _daftar(halaman, nomor)
    pesan = halaman.locator("#scan-datang-pesan")

    _scan(halaman, "#scan-datang", nomor)
    expect(halaman.locator("#toasts")).to_contain_text(f"{kamus(halaman, 'sukDatang')} {nomor}")
    expect(pesan).to_have_text("")
    _scan(halaman, "#scan-datang", nomor)
    expect(pesan).to_contain_text(kamus(halaman, "datangSudah").split("{jam}")[0].strip())
    expect(pesan).to_have_class(_SALAH)

    _isi(halaman, nomor)
    _scan(halaman, "#scan-datang", nomor)
    expect(pesan).to_contain_text(kamus(halaman, "datangMasihDiDalam"))
    expect(_baris(halaman, nomor).locator("td").nth(_ANTRE)).to_have_text(halaman.evaluate("() => teksMenit(0)"))

    _kosong(halaman, nomor)
    _pergi(halaman, nomor)


def test_not_a_plate_is_refused_on_both_gate_fields(halaman):
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")
    for kolom, pesan in (("#scan-datang", "#scan-datang-pesan"), ("#scan-pergi", "#scan-pergi-pesan")):
        _scan(halaman, kolom, _BUKAN_PLAT)
        expect(halaman.locator(pesan)).to_have_text(kamus(halaman, "err_bukan_plat"))
        expect(halaman.locator(pesan)).to_have_class(_SALAH)
        expect(halaman.locator(kolom)).to_have_value("")


def _tiket_terbuka(halaman, konsol, nomor: str) -> dict:
    """A truck registered and weighed in through the API, the way the screen sends it."""
    r = halaman.request.post(konsol.url + "/api/console/trucks", data={"plate_number": nomor})
    assert r.status == 201, r.text()
    masuk_pada = halaman.evaluate("() => new Date().toISOString()")
    r = halaman.request.post(
        konsol.url + "/api/console/weighings",
        data={"plate_number": nomor, "gross_kg": "14000", "entered_at": masuk_pada},
    )
    assert r.status == 201, r.text()
    return next(w for w in halaman.request.get(konsol.url + "/api/console/weighings").json()["items"]
                if w["plate_number"] == nomor)


def _tutup_tiket(halaman, konsol, tiket: dict) -> None:
    """Weigh out and leave through the API: the session-scoped console keeps every ticket."""
    sekarang = halaman.evaluate("() => new Date().toISOString()")
    r = halaman.request.post(konsol.url + "/api/console/weighings", data={
        "plate_number": tiket["plate_number"], "entered_at": tiket["entered_at"],
        "tare_kg": "6000", "exited_at": sekarang})
    assert r.status == 201, r.text()
    r = halaman.request.post(konsol.url + "/api/console/departures", data={"weighing_id": tiket["id"], "at": sekarang})
    assert r.status == 200 and r.json()["hasil"] == "tercatat", r.text()


_LEBAR = (1024, 1280, 1440, 1920)


@pytest.mark.parametrize("lebar", _LEBAR)
def test_the_four_steps_never_scroll_sideways(halaman, konsol, browser_name, lebar, penugasan_bersih):
    halaman.set_viewport_size({"width": lebar, "height": 900})
    masuk(halaman, OPERATOR)
    tiket = _tiket_terbuka(halaman, konsol, plat(browser_name, 1205 + _LEBAR.index(lebar)))
    buka_tab(halaman, "timbangan")
    halaman.evaluate("() => muatTimbangan()")
    # The row button is the operator's only per-row action without a scanner: on screen
    # without scrolling the table sideways (11 columns are wider than 1280 and 1440 px).
    tombol = _baris(halaman, tiket["plate_number"]).locator('button[data-aksi="keluar"]')
    expect(tombol).to_have_count(1)
    tombol.evaluate("(el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 200)")
    assert halaman.evaluate("() => document.querySelector('#sec-timbangan .tabel').scrollLeft") == 0
    expect(tombol).to_be_in_viewport(ratio=1)
    _tutup_tiket(halaman, konsol, tiket)
    ukuran = halaman.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
    assert ukuran[0] <= ukuran[1], f"Timbangan is {ukuran[0]} px wide on a {ukuran[1]} px screen"
    pemisah = halaman.evaluate(
        "() => [...document.querySelectorAll('#sec-timbangan .timbang-pisah')]"
        ".map((el) => [getComputedStyle(el).borderTopWidth, getComputedStyle(el).borderLeftWidth])"
    )
    assert len(pemisah) == 2, pemisah
    if lebar <= 1330:
        # Stacked: the separator moves to the top, a left line would point at nothing.
        assert all(atas != "0px" and kiri == "0px" for atas, kiri in pemisah), pemisah
    else:
        assert all(atas == "0px" and kiri != "0px" for atas, kiri in pemisah), pemisah
