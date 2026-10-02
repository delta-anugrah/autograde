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


_LEBAR = (1024, 1280, 1440, 1920)


@pytest.mark.parametrize("lebar", _LEBAR)
def test_the_four_steps_never_scroll_sideways(halaman, konsol, browser_name, lebar, penugasan_bersih):
    halaman.set_viewport_size({"width": lebar, "height": 900})
    masuk(halaman, OPERATOR)
    tiket = _tiket_terbuka(halaman, konsol, plat(browser_name, 1205 + _LEBAR.index(lebar)))
    buka_tab(halaman, "timbangan")
    halaman.evaluate("() => muatTimbangan()")
    # The row button is the operator's only per-row action without a scanner: on screen
    # without scrolling the table sideways (12 columns are wider than 1280 and 1440 px).
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
        # One row from 1331 px (user 2026-10-02: at 1440 "4. Keluar" wrapped to a second row).
        atas = halaman.evaluate(_ATAS_LANGKAH)
        assert len(set(atas)) == 1, atas
    # The decimal hint sits inside step 2, right under the Bruto field (it used to float
    # at the end of the toolbar, next to "4. Keluar").
    letak = halaman.evaluate(_LETAK_PETUNJUK)
    assert letak["diLangkah2"], letak
    assert letak["petunjuk"]["top"] >= letak["bruto"]["bottom"] - 1, letak
    assert abs(letak["petunjuk"]["left"] - letak["bruto"]["left"]) <= 1, letak


_ATAS_LANGKAH = """() => ['lbDatang', 'lbGerbangMasuk', 'lbGerbangKeluar', 'lbPergi']
  .map((k) => Math.round(document.querySelector(`#sec-timbangan [data-t="${k}"]`).getBoundingClientRect().top))"""
_LETAK_PETUNJUK = """() => {
  const petunjuk = document.querySelector('#sec-timbangan [data-t="hintDesimal"]');
  const kotak = (el) => { const r = el.getBoundingClientRect(); return {top: r.top, bottom: r.bottom, left: r.left}; };
  return {diLangkah2: Boolean(petunjuk.closest('.timbang-sisi').querySelector('[data-t="lbGerbangMasuk"]')),
          petunjuk: kotak(petunjuk), bruto: kotak(document.querySelector('#bruto'))};
}"""


# Where each step starts inside the toolbar: label, picker, weight field and button of steps
# 2 to 4. Relative to the toolbar, because the page above it (line cards, the scroll) moves
# on its own between two polls.
_POSISI_LANGKAH = """() => {
  const alat = document.querySelector('#sec-timbangan .timbang-alat').getBoundingClientRect();
  return ['[data-t="lbGerbangMasuk"]', '#plat-timbang', '#bruto', '#masuk',
          '[data-t="lbGerbangKeluar"]', '[data-t="lbPergi"]']
    .map((sel) => { const r = document.querySelector('#sec-timbangan ' + sel).getBoundingClientRect();
                    return [sel, Math.round(r.left - alat.left), Math.round(r.top - alat.top)]; });
}"""


_LEBAR_ANTRE = (1024, 1440, 1920)


@pytest.mark.parametrize("lebar", _LEBAR_ANTRE)
def test_the_waiting_list_never_moves_the_other_steps(halaman, konsol, browser_name, lebar, penugasan_bersih):
    """`#antre` under step 1 changes on every 15 s poll ("Menunggu timbang (n): ..."). It never
    widens or heightens step 1 (a fixed two-line box, cut inside it), so steps 2 to 4 stay where
    the operator's hand is, side by side or stacked (Q6)."""
    halaman.set_viewport_size({"width": lebar, "height": 900})
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")
    halaman.evaluate("() => muatTimbangan()")
    expect(halaman.locator("#antre")).to_have_text("")
    sebelum = halaman.evaluate(_POSISI_LANGKAH)

    nomor = [plat(browser_name, 1221 + 3 * _LEBAR_ANTRE.index(lebar) + i) for i in range(3)]
    try:
        for n in nomor:
            r = halaman.request.post(konsol.url + "/api/console/trucks", data={"plate_number": n})
            assert r.status == 201, r.text()
            jam = halaman.evaluate("() => new Date().toISOString()")
            r = halaman.request.post(konsol.url + "/api/console/arrivals", data={"qr": n, "at": jam})
            assert r.status == 200 and r.json()["hasil"] == "tercatat", r.text()
        halaman.evaluate("() => muatTimbangan()")
        for n in nomor:
            expect(halaman.locator("#antre")).to_contain_text(n)
            # Two lines, cut when longer: the whole list is also in the tooltip.
            expect(halaman.locator("#antre")).to_have_attribute("title", re.compile(re.escape(n)))

        assert halaman.evaluate(_POSISI_LANGKAH) == sebelum
        lebar_antre, lebar_sisi = halaman.evaluate(
            "() => [document.querySelector('#antre').getBoundingClientRect().width,"
            " document.querySelector('#antre').parentElement.getBoundingClientRect().width]"
        )
        assert lebar_antre <= lebar_sisi, (lebar_antre, lebar_sisi)
        # Readable from a distance: two lines of text, never one, and the box never grows.
        tinggi, baris = halaman.evaluate(
            "() => { const el = document.querySelector('#antre'), g = getComputedStyle(el);"
            " return [el.getBoundingClientRect().height, parseFloat(g.lineHeight)]; }"
        )
        assert round(tinggi / baris) == 2, (tinggi, baris)
    finally:
        # Every arrival is claimed by a weigh-in, then weighed out and gone: the console is
        # shared by the whole session, a leftover would sit in the next test's waiting list.
        for n in nomor:
            masuk_pada = halaman.evaluate("() => new Date().toISOString()")
            halaman.request.post(konsol.url + "/api/console/trucks", data={"plate_number": n})
            r = halaman.request.post(konsol.url + "/api/console/weighings",
                                     data={"plate_number": n, "gross_kg": "14000", "entered_at": masuk_pada})
            assert r.status == 201, r.text()
            tiket = next(w for w in halaman.request.get(konsol.url + "/api/console/weighings").json()["items"]
                         if w["plate_number"] == n)
            _tutup_tiket(halaman, konsol, tiket)
    halaman.evaluate("() => muatTimbangan()")
    expect(halaman.locator("#antre")).to_have_text("")


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
        halaman.evaluate("() => muatTimbangan()")
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
    expect(atas.locator("button")).to_have_count(0)

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
