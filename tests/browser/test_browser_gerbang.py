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

# Cells of a ticket row (`barisTimbangan` in console.html); Status is the first since 2026-10-02.
_STATUS, _ANTRE, _TOTAL = 0, 3, 5
_SALAH = re.compile(r"\bsalah\b")
_BUKAN_PLAT = "https://promo.example/qr"
_LANGKAH = ("lbDatang", "lbGerbangMasuk", "lbGerbangKeluar", "lbPergi")
_KOLOM_SCAN = ("#scan-datang", "#scan-plat", "#scan-keluar", "#scan-pergi")
_WARNA = "(el) => [getComputedStyle(el).color, getComputedStyle(el).backgroundColor]"
# The theme's own warning pair, resolved by the browser the same way as the tag's.
_WARNA_PERINGATAN = """() => {
  const el = document.createElement("span");
  el.style.color = "var(--warn)"; el.style.backgroundColor = "var(--warn-bg)";
  document.body.append(el);
  const g = getComputedStyle(el), hasil = [g.color, g.backgroundColor];
  el.remove();
  return hasil;
}"""


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
    expect(halaman.locator("#sec-timbangan thead th")).to_have_count(12)
    expect(halaman.locator("#sec-timbangan thead th").first).to_have_text(kamus(halaman, "thStatus"))
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
    # The badge counts, the plates are in its title (user 2026-10-03: the long sentence went).
    expect(halaman.locator("#antre")).to_have_attribute("title", re.compile(re.escape(nomor)))
    # The picker empties once the arrival is recorded, so a second press cannot repeat it.
    expect(halaman.locator("#plat-datang")).to_have_attribute("data-nilai", "")
    expect(halaman.locator("#datang")).to_be_disabled()

    _isi(halaman, nomor)
    expect(halaman.locator("#antre")).not_to_have_attribute("title", re.compile(re.escape(nomor)))
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
    # In the warning colour of this theme (user 2026-10-02), not grey like plain text.
    expect(tanda).to_have_class(re.compile(r"\bperingatan\b"))
    assert tanda.evaluate(_WARNA) == halaman.evaluate(_WARNA_PERINGATAN)
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


_LEBAR = (390, 1024, 1280, 1331, 1440, 1680, 1920)
# From here the whole table, row button included, fits without scrolling sideways.
_LEBAR_TABEL_MUAT = 1440
_TABEL_MUAT = """() => {
  const t = document.querySelector('#sec-timbangan .tabel');
  const kepala = [...t.querySelectorAll('thead th')];
  return {lebar: t.scrollWidth, kotak: t.clientWidth,
          neto: Math.round(kepala[kepala.length - 2].getBoundingClientRect().right),
          tombol: Math.round(kepala[kepala.length - 1].getBoundingClientRect().left),
          kolom: kepala.map((h) => Math.round(h.getBoundingClientRect().width)),
          // Cells of every full row line up with their column head (a global rule on a cell
          // class once turned two time cells into one flex box and shifted the whole row).
          geser: [...t.querySelectorAll('tbody tr')].filter((tr) => tr.cells.length === kepala.length)
            .flatMap((tr) => [...tr.cells].map((c, i) => Math.abs(c.getBoundingClientRect().left
              - kepala[i].getBoundingClientRect().left))).filter((d) => d > 1).length};
}"""
# Below this the 12-column table scrolls sideways inside its own box (a phone).
_LEBAR_TABEL_PENUH = 1024


@pytest.mark.parametrize("lebar", _LEBAR)
def test_the_four_steps_never_scroll_sideways(halaman, konsol, browser_name, lebar, penugasan_bersih):
    halaman.set_viewport_size({"width": lebar, "height": 900})
    masuk(halaman, OPERATOR)
    tiket = _tiket_terbuka(halaman, konsol, plat(browser_name, 1205 + _LEBAR.index(lebar)))
    buka_tab(halaman, "timbangan")
    halaman.evaluate("() => muatTimbangan()")
    tombol = _baris(halaman, tiket["plate_number"]).locator('button[data-aksi="keluar"]')
    expect(tombol).to_have_count(1)
    if lebar >= _LEBAR_TABEL_PENUH:
        # The row button is the operator's only per-row action without a scanner: on screen
        # without scrolling the table sideways (12 columns are wider than 1280 and 1440 px).
        tombol.evaluate("(el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 200)")
        assert halaman.evaluate("() => document.querySelector('#sec-timbangan .tabel').scrollLeft") == 0
        expect(tombol).to_be_in_viewport(ratio=1)
    if lebar >= _LEBAR_TABEL_MUAT:
        # Every column fits with the row button pinned (user 2026-10-03: Neto, the paid figure,
        # hid under the pinned button column at 1680 px).
        muat = halaman.evaluate(_TABEL_MUAT)
        assert muat["lebar"] <= muat["kotak"], muat
        assert muat["neto"] <= muat["tombol"] + 1, muat
        assert muat["geser"] == 0, muat
    _tutup_tiket(halaman, konsol, tiket)
    ukuran = halaman.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
    assert ukuran[0] <= ukuran[1], f"Timbangan is {ukuran[0]} px wide on a {ukuran[1]} px screen"
    # Nothing in the step area pokes out of its own box (a pill wider than its segment).
    luber = halaman.evaluate(_LUBER)
    assert not luber, luber


# Every element of the step area whose right edge passes its segment, form or bar.
_LUBER = """() => {
  const keluar = [];
  document.querySelectorAll('#sec-timbangan .langkah-ruas, #sec-timbangan .timbang-form, #tara-grup')
    .forEach((kotak) => {
      const k = kotak.getBoundingClientRect();
      kotak.querySelectorAll('*').forEach((el) => {
        const r = el.getBoundingClientRect();
        if (r.width && r.right > k.right + 1) keluar.push([el.id || el.className, Math.round(r.right), Math.round(k.right)]);
      });
    });
  return keluar;
}"""

# Boxes of the step area: the four segments, the two forms, the controls of each form.
_KOTAK_LANGKAH = """() => {
  const kotak = (el) => { const r = el.getBoundingClientRect();
    return {left: Math.round(r.left), top: Math.round(r.top), width: Math.round(r.width),
            height: Math.round(r.height), bottom: Math.round(r.bottom)}; };
  const semua = (sel) => [...document.querySelectorAll(sel)].map(kotak);
  return {ruas: semua('#sec-timbangan .langkah-ruas'), form: semua('#sec-timbangan .timbang-form'),
          kontrol: semua('#sec-timbangan .timbang-kontrol > :not([hidden])'),
          tombol: semua('#datang, #masuk')};
}"""
_SELISIH_PX = 2


def _sama(nilai: list[int]) -> bool:
    return max(nilai) - min(nilai) <= _SELISIH_PX


@pytest.mark.parametrize("lebar", (1440, 1680))
def test_steps_and_forms_are_equal_width_and_height(halaman, lebar):
    """User 2026-10-03: "width beda2, height juga". Four segments of one width and height on
    one row, two forms of one width and height side by side, every control one height and the
    two main buttons one width."""
    halaman.set_viewport_size({"width": lebar, "height": 900})
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")
    k = halaman.evaluate(_KOTAK_LANGKAH)
    assert len(k["ruas"]) == 4 and len(k["form"]) == 2, k
    assert len({r["top"] for r in k["ruas"]}) == 1, k["ruas"]
    assert _sama([r["width"] for r in k["ruas"]]) and _sama([r["height"] for r in k["ruas"]]), k["ruas"]
    assert len({f["top"] for f in k["form"]}) == 1, k["form"]
    assert _sama([f["width"] for f in k["form"]]) and _sama([f["height"] for f in k["form"]]), k["form"]
    assert _sama([c["height"] for c in k["kontrol"]]), k["kontrol"]
    assert len({c["top"] for c in k["kontrol"]}) == 1, k["kontrol"]
    assert _sama([b["width"] for b in k["tombol"]]), k["tombol"]
    # The decimal hint is under form 2, where Bruto is, and nothing of it sits inside a form.
    petunjuk = halaman.locator("#bruto-petunjuk").bounding_box()
    assert petunjuk["y"] >= k["form"][1]["bottom"] - 1, (petunjuk, k["form"])
    assert abs(petunjuk["x"] - k["form"][1]["left"]) <= _SELISIH_PX, (petunjuk, k["form"])
    expect(halaman.locator("#bruto")).to_have_attribute("title", kamus(halaman, "hintDesimal"))


def test_steps_and_forms_stack_on_a_phone(halaman):
    halaman.set_viewport_size({"width": 390, "height": 900})
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")
    k = halaman.evaluate(_KOTAK_LANGKAH)
    for kelompok in ("ruas", "form"):
        atas = [r["top"] for r in k[kelompok]]
        assert atas == sorted(set(atas)), k[kelompok]
        assert _sama([r["width"] for r in k[kelompok]]), k[kelompok]
    assert k["ruas"][-1]["bottom"] <= k["form"][0]["top"], k


# Where each control of the step area sits inside the toolbar. Relative to the toolbar, because
# the page above it (line cards, the scroll) moves on its own between two polls.
_POSISI_LANGKAH = """() => {
  const alat = document.querySelector('#sec-timbangan .timbang-alat').getBoundingClientRect();
  return ['[data-t="lbDatang"]', '[data-t="lbGerbangMasuk"]', '[data-t="lbGerbangKeluar"]',
          '[data-t="lbPergi"]', '#plat-datang', '#datang', '#plat-timbang', '#bruto', '#masuk']
    .map((sel) => { const r = document.querySelector('#sec-timbangan ' + sel).getBoundingClientRect();
                    return [sel, Math.round(r.left - alat.left), Math.round(r.top - alat.top),
                            Math.round(r.width), Math.round(r.height)]; });
}"""


_LEBAR_ANTRE = (1024, 1440, 1920)


@pytest.mark.parametrize("lebar", _LEBAR_ANTRE)
def test_the_waiting_list_never_moves_the_other_steps(halaman, konsol, browser_name, lebar, penugasan_bersih):
    """The Menunggu badge in step 1 changes on every 15 s poll. It is one line that never
    wraps (cut inside its segment when narrow), so no segment, form or control moves (Q6)."""
    halaman.set_viewport_size({"width": lebar, "height": 900})
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")
    halaman.evaluate("() => muatTimbangan()")
    lencana = halaman.locator("#antre")
    expect(lencana).to_be_hidden()
    sebelum = halaman.evaluate(_POSISI_LANGKAH)

    nomor = [plat(browser_name, 1221 + 3 * _LEBAR_ANTRE.index(lebar) + i) for i in range(3)]
    try:
        for n in nomor:
            _datang_api(halaman, konsol, n)
        halaman.evaluate("() => muatTimbangan()")
        expect(lencana).to_be_visible()
        expect(lencana).to_have_text(kamus(halaman, "antreLencana").replace("{n}", "3"))
        for n in nomor:
            # Only the count on the badge; the plates are in its title.
            expect(lencana).to_have_attribute("title", re.compile(re.escape(n)))
        assert halaman.evaluate(_POSISI_LANGKAH) == sebelum
        ruas = lencana.evaluate("(el) => [el.getBoundingClientRect().right,"
                                " el.closest('.langkah-ruas').getBoundingClientRect().right]")
        assert ruas[0] <= ruas[1], ruas
    finally:
        # Every arrival is claimed by a weigh-in, then weighed out and gone: the console is
        # shared by the whole session, a leftover would sit in the next test's waiting list.
        for n in nomor:
            _selesaikan(halaman, konsol, n)
    halaman.evaluate("() => muatTimbangan()")
    expect(lencana).to_be_hidden()
    assert halaman.evaluate(_POSISI_LANGKAH) == sebelum


def _datang_api(halaman, konsol, nomor: str) -> None:
    r = halaman.request.post(konsol.url + "/api/console/trucks", data={"plate_number": nomor})
    assert r.status == 201, r.text()
    jam = halaman.evaluate("() => new Date().toISOString()")
    r = halaman.request.post(konsol.url + "/api/console/arrivals", data={"qr": nomor, "at": jam})
    assert r.status == 200 and r.json()["hasil"] == "tercatat", r.text()


def _selesaikan(halaman, konsol, nomor: str) -> None:
    """Weigh in (claims the arrival), weigh out and leave: nothing left for the next test."""
    masuk_pada = halaman.evaluate("() => new Date().toISOString()")
    r = halaman.request.post(konsol.url + "/api/console/weighings",
                             data={"plate_number": nomor, "gross_kg": "14000", "entered_at": masuk_pada})
    assert r.status == 201, r.text()
    tiket = next(w for w in halaman.request.get(konsol.url + "/api/console/weighings").json()["items"]
                 if w["plate_number"] == nomor)
    _tutup_tiket(halaman, konsol, tiket)


def test_waiting_trucks_lead_the_weigh_in_picker_and_a_poll_keeps_the_pick(halaman, konsol, browser_name,
                                                                           penugasan_bersih):
    """User 2026-10-02: the trucks that did "Catat datang" come first in "2. Timbang isi", in
    their own section, and the 15 s poll never resets what the operator picked."""
    lain, pertama, kedua = (plat(browser_name, n) for n in (1231, 1232, 1233))
    masuk(halaman, OPERATOR)
    try:
        r = halaman.request.post(konsol.url + "/api/console/trucks", data={"plate_number": lain})
        assert r.status == 201, r.text()
        _datang_api(halaman, konsol, pertama)
        buka_tab(halaman, "timbangan")
        halaman.evaluate("() => muatTrucks().then(() => muatTimbangan())")
        pilih = halaman.locator("#plat-timbang")
        pilih.locator(".pilih-tombol").click()
        kepala = pilih.locator(".pilih-grup")
        expect(kepala).to_have_count(2)
        expect(kepala.nth(0)).to_have_text(kamus(halaman, "grupMenungguTimbang"))
        expect(kepala.nth(1)).to_have_text(kamus(halaman, "grupTrukLain"))
        opsi = pilih.locator('[role="option"]')
        expect(opsi.nth(1)).to_have_attribute("data-nilai", pertama)
        expect(opsi.nth(1).locator(".pilih-catatan")).to_have_text(halaman.evaluate("() => teksMenit(0)"))
        expect(pilih.locator(f'[role="option"][data-nilai="{lain}"]')).to_have_count(1)
        expect(pilih.locator(f'[role="option"][data-nilai="{pertama}"]')).to_have_count(1)
        pilih.locator(f'[role="option"][data-nilai="{lain}"]').click()
        expect(pilih).to_have_attribute("data-nilai", lain)
        # The closed trigger shows the plate only, never a minute count going stale.
        expect(pilih.locator(".pilih-teks")).to_have_text(lain)

        _datang_api(halaman, konsol, kedua)
        # Registered just now: the truck list poll brings it in, only registered trucks are offered.
        halaman.evaluate("() => muatTrucks().then(() => muatTimbangan())")
        expect(halaman.locator(f'#plat-timbang [role="option"][data-nilai="{kedua}"]')).to_have_count(1)
        expect(halaman.locator("#plat-timbang")).to_have_attribute("data-nilai", lain)
        # Oldest arrival first.
        expect(halaman.locator('#plat-timbang [role="option"]').nth(1)).to_have_attribute("data-nilai", pertama)
        expect(halaman.locator('#plat-timbang [role="option"]').nth(2)).to_have_attribute("data-nilai", kedua)
    finally:
        for n in (pertama, kedua):
            _selesaikan(halaman, konsol, n)
    halaman.evaluate("() => muatTimbangan()")
    expect(halaman.locator("#plat-timbang .pilih-grup")).to_have_count(0)


def _lencana(baris):
    return baris.locator("td").nth(_STATUS).locator(".lencana")


def test_status_badge_follows_the_four_steps_and_the_newest_row_leads(halaman, konsol, browser_name,
                                                                      penugasan_bersih):
    """User 2026-10-02: a Status badge per row in its step's colour (Datang grey, Bongkar
    yellow, Timbang kosong blue, Selesai green), the arrival as the top row before its
    weigh-in, and the newest weigh-in on top after it."""
    nomor = plat(browser_name, 1241)
    masuk(halaman, OPERATOR)
    _datang_api(halaman, konsol, nomor)
    buka_tab(halaman, "timbangan")
    halaman.evaluate("() => muatTrucks().then(() => muatTimbangan())")
    atas = halaman.locator("#timbangan tr").first
    expect(atas).to_contain_text(nomor)
    expect(_lencana(atas)).to_have_text(kamus(halaman, "tahapDatang"))
    expect(_lencana(atas)).to_have_class(re.compile(r"\btahap-datang\b"))
    # No ticket yet, so no weighing button; its one button is Batal datang (2026-10-03).
    expect(atas.locator("button")).to_have_count(1)
    expect(atas.locator('button[data-aksi="batal-datang"]')).to_have_count(1)

    langkah = {"lbDatang": "tahap-datang", "lbGerbangMasuk": "tahap-bongkar",
               "lbGerbangKeluar": "tahap-kosong", "lbPergi": "tahap-selesai"}
    for kunci, kelas in langkah.items():
        judul = halaman.locator(f'#sec-timbangan label[data-t="{kunci}"]')
        expect(judul).to_have_class(re.compile(rf"\b{kelas}\b"))

    def _sama_warna(kunci: str) -> None:
        """The badge and its step header resolve to the same colours in this theme."""
        badge = _lencana(_baris(halaman, nomor))
        judul = halaman.locator(f'#sec-timbangan label[data-t="{kunci}"]')
        assert badge.evaluate(_WARNA) == judul.evaluate(_WARNA)

    _sama_warna("lbDatang")
    _isi(halaman, nomor)
    # Newest weigh-in first: the ticket just weighed in is the top row.
    expect(halaman.locator("#timbangan tr").first).to_contain_text(nomor)
    expect(_lencana(_baris(halaman, nomor))).to_have_text(kamus(halaman, "tahapBongkar"))
    _sama_warna("lbGerbangMasuk")
    _kosong(halaman, nomor)
    expect(_lencana(_baris(halaman, nomor))).to_have_text(kamus(halaman, "tahapTimbangKosong"))
    _sama_warna("lbGerbangKeluar")
    _pergi(halaman, nomor)
    expect(_lencana(_baris(halaman, nomor))).to_have_text(kamus(halaman, "tahapSelesai"))
    _sama_warna("lbPergi")


def test_a_poll_never_takes_the_weigh_in_picker_from_the_operator(halaman, konsol, browser_name, penugasan_bersih):
    """Review 2026-10-02: a poll with a changed waiting list keeps an open panel open, and after
    a keyboard pick the focus stays on the picker (an `outerHTML` redraw sent it to <body>)."""
    nomor = [plat(browser_name, n) for n in (1251, 1252, 1253)]
    masuk(halaman, OPERATOR)
    try:
        r = halaman.request.post(konsol.url + "/api/console/trucks", data={"plate_number": nomor[0]})
        assert r.status == 201, r.text()
        buka_tab(halaman, "timbangan")
        halaman.evaluate("() => muatTrucks().then(() => muatTimbangan())")
        pilih = halaman.locator("#plat-timbang")
        pilih.locator(".pilih-tombol").click()
        expect(pilih.locator(".pilih-panel")).to_be_visible()
        _datang_api(halaman, konsol, nomor[1])
        halaman.evaluate("() => muatTrucks().then(() => muatTimbangan())")
        expect(pilih.locator(".pilih-panel")).to_be_visible()

        halaman.keyboard.press("Escape")
        halaman.keyboard.press("ArrowDown")
        halaman.keyboard.press("ArrowDown")
        halaman.keyboard.press("Enter")
        expect(pilih.locator(".pilih-panel")).to_be_hidden()
        dipilih = pilih.get_attribute("data-nilai")
        assert dipilih, "the keyboard pick did not land"
        _datang_api(halaman, konsol, nomor[2])
        halaman.evaluate("() => muatTrucks().then(() => muatTimbangan())")
        expect(halaman.locator('#plat-timbang [role="option"]', has_text=nomor[2])).to_have_count(1)
        expect(halaman.locator("#plat-timbang")).to_have_attribute("data-nilai", dipilih)
        assert halaman.evaluate("() => Boolean(document.activeElement.closest('#plat-timbang'))")
    finally:
        for n in nomor[1:]:
            _selesaikan(halaman, konsol, n)


_LEBAR_TARA = (390, 1440, 1680)
_KOTAK = """(sel) => sel.map((s) => { const r = document.querySelector(s).getBoundingClientRect();
  return {top: Math.round(r.top), height: Math.round(r.height), width: Math.round(r.width)}; })"""
_TARA = ["#tara-nilai", "#tara-simpan", "#tara-batal"]


@pytest.mark.parametrize("lebar", _LEBAR_TARA)
def test_the_tara_bar_opens_under_the_forms_on_one_row(halaman, konsol, browser_name, lebar, penugasan_bersih):
    """User 2026-10-03: Timbang kosong on a row opens a full-width bar in the step 3 colour
    under the two forms: plate, Tara, Simpan, Batal on one row, as tall as the form controls.
    Step 3 lights up while it is open; Batal closes it and the stripe is plain again."""
    halaman.set_viewport_size({"width": lebar, "height": 900})
    masuk(halaman, OPERATOR)
    tiket = _tiket_terbuka(halaman, konsol, plat(browser_name, 1261 + _LEBAR_TARA.index(lebar)))
    try:
        buka_tab(halaman, "timbangan")
        halaman.evaluate("() => muatTimbangan()")
        utama, bahaya = re.compile(r"\butama\b"), re.compile(r"\bbahaya\b")
        aktif = re.compile(r"\baktif\b")
        expect(halaman.locator("#datang")).to_have_class(utama)
        expect(halaman.locator("#masuk")).to_have_class(utama)
        expect(halaman.locator("#ruas-kosong")).not_to_have_class(aktif)

        _baris(halaman, tiket["plate_number"]).locator('button[data-aksi="keluar"]').click()
        expect(halaman.locator("#tara-grup")).to_be_visible()
        expect(halaman.locator("#tara-plat")).to_have_text(tiket["plate_number"])
        expect(halaman.locator("#tara-nilai")).to_be_focused()
        expect(halaman.locator("#tara-simpan")).to_have_class(utama)
        expect(halaman.locator("#tara-batal")).to_have_class(bahaya)
        expect(halaman.locator("#ruas-kosong")).to_have_class(aktif)

        bar = halaman.locator("#tara-grup").bounding_box()
        form = halaman.locator("#sec-timbangan .timbang-form").last.bounding_box()
        assert bar["y"] >= form["y"] + form["height"], (bar, form)
        tara = halaman.evaluate(_KOTAK, [*_TARA, "#bruto", "#masuk"])
        assert max(k["height"] for k in tara) - min(k["height"] for k in tara) <= _SELISIH_PX, tara
        if lebar > _LEBAR_TABEL_PENUH:
            # One row, and the bar is as wide as the two forms together.
            assert max(k["top"] for k in tara[:3]) - min(k["top"] for k in tara[:3]) <= _SELISIH_PX, tara
            alat = halaman.locator("#sec-timbangan .timbang-aksi").bounding_box()
            assert abs(bar["width"] - alat["width"]) <= _SELISIH_PX, (bar, alat)
            assert tara[1]["width"] == tara[2]["width"] == tara[4]["width"], tara

        halaman.keyboard.press("Escape")
        expect(halaman.locator("#tara-grup")).to_be_hidden()
        _baris(halaman, tiket["plate_number"]).locator('button[data-aksi="keluar"]').click()
        halaman.click("#tara-batal")
        expect(halaman.locator("#tara-grup")).to_be_hidden()
        expect(halaman.locator("#tara-plat")).to_have_text("")
        expect(halaman.locator("#ruas-kosong")).not_to_have_class(aktif)
    finally:
        _tutup_tiket(halaman, konsol, tiket)


def test_a_tara_below_the_floor_is_worded_next_to_the_field(halaman, konsol, browser_name, penugasan_bersih):
    """The tare message sits in the bar, beside the field the operator is typing in."""
    halaman.set_viewport_size({"width": 1440, "height": 900})
    masuk(halaman, OPERATOR)
    tiket = _tiket_terbuka(halaman, konsol, plat(browser_name, 1264))
    try:
        buka_tab(halaman, "timbangan")
        halaman.evaluate("() => muatTimbangan()")
        _baris(halaman, tiket["plate_number"]).locator('button[data-aksi="keluar"]').click()
        halaman.fill("#tara-nilai", "12")
        halaman.click("#tara-simpan")
        pesan = halaman.locator("#tara-grup #scan-keluar-pesan")
        expect(pesan).to_have_text(kamus(halaman, "taraMinimum"))
        expect(pesan).to_have_class(_SALAH)
        # Beside the buttons, never over them (Firefox once laid it across Batal).
        batal = halaman.locator("#tara-batal").bounding_box()
        assert pesan.bounding_box()["x"] >= batal["x"] + batal["width"], (pesan.bounding_box(), batal)
        # A new tare starts clean: the old message does not follow the next truck.
        halaman.click("#tara-batal")
        _baris(halaman, tiket["plate_number"]).locator('button[data-aksi="keluar"]').click()
        expect(pesan).to_have_text("")
        halaman.click("#tara-batal")
    finally:
        _tutup_tiket(halaman, konsol, tiket)
