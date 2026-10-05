"""One dropdown for the whole console (batch 5.6): type to filter, trucks on site first,
never replaced under the finger, and the support forms use it too.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from langkah import OPERATOR, SUPPORT, buka_tab, kamus, masuk, plat
from playwright.sync_api import expect

_KARTU = '#lines .card[data-line="line-2"] .assign .pilih'
_OPSI_TAMPAK = '[role="option"]:not([hidden])'


def _daftar(konsol, nomor: str, *, timbang_isi: bool = False) -> None:
    with httpx.Client(base_url=konsol.url, timeout=10) as c:
        c.post("/api/console/login", json={"email": OPERATOR[0], "sandi": OPERATOR[1]}).raise_for_status()
        c.post("/api/console/trucks", json={"plate_number": nomor}).raise_for_status()
        if timbang_isi:
            c.post("/api/console/weighings", json={
                "plate_number": nomor, "gross_kg": "14000",
                "entered_at": datetime.now(ZoneInfo("Asia/Jakarta")).isoformat(),
            }).raise_for_status()


def test_typing_part_of_a_plate_leaves_its_row_and_enter_picks_it(halaman, konsol, browser_name):
    nomor = plat(browser_name, 5601)
    _daftar(konsol, nomor)
    masuk(halaman, OPERATOR)
    halaman.evaluate("() => muatTrucks()")
    pemilih = halaman.locator(_KARTU)
    semua = pemilih.locator('[role="option"]').count()
    assert semua >= 8, "the seeded truck list is long enough to need a search"

    pemilih.locator(".pilih-tombol").click()
    cari = pemilih.locator(".pilih-cari")
    expect(cari).to_be_focused()
    expect(cari).to_have_attribute("placeholder", kamus(halaman, "pilihCari"))

    # Lower case and no spaces: neither decides a match.
    halaman.keyboard.type(nomor.lower()[2:])
    expect(pemilih.locator(_OPSI_TAMPAK)).to_have_count(1)
    expect(pemilih.locator(_OPSI_TAMPAK)).to_have_text(nomor)
    expect(pemilih.locator(".pilih-panel")).to_be_visible()

    halaman.keyboard.press("Enter")

    expect(pemilih.locator(".pilih-panel")).to_be_hidden()
    expect(pemilih.locator(".pilih-teks")).to_have_text(nomor)
    expect(pemilih.locator(".pilih-cari")).to_have_count(0)
    # Opened again it starts whole: the search is gone with the last opening.
    pemilih.locator(".pilih-tombol").click()
    expect(pemilih.locator(".pilih-cari")).to_have_value("")
    expect(pemilih.locator(_OPSI_TAMPAK)).to_have_count(semua + 0)
    halaman.keyboard.press("Escape")


def test_a_search_with_no_match_says_so_and_a_click_in_the_field_keeps_the_list_open(halaman):
    masuk(halaman, OPERATOR)
    pemilih = halaman.locator(_KARTU)
    pemilih.locator(".pilih-tombol").click()
    pemilih.locator(".pilih-cari").click()
    expect(pemilih.locator(".pilih-panel")).to_be_visible()

    halaman.keyboard.type("zzzz tidak ada")

    expect(pemilih.locator(_OPSI_TAMPAK)).to_have_count(0)
    expect(pemilih.locator(".pilih-kosong")).to_be_visible()
    expect(pemilih.locator(".pilih-kosong")).to_have_text(kamus(halaman, "pilihTakCocok"))
    halaman.keyboard.press("Enter")
    expect(pemilih.locator(".pilih-panel")).to_be_visible()
    expect(pemilih).to_have_attribute("data-nilai", "")
    halaman.keyboard.press("Escape")
    expect(pemilih.locator(".pilih-panel")).to_be_hidden()


def test_arrow_keys_walk_the_rows_that_are_left_and_a_letter_returns_to_the_field(halaman, konsol, browser_name):
    nomor = plat(browser_name, 5602)
    _daftar(konsol, nomor)
    masuk(halaman, OPERATOR)
    halaman.evaluate("() => muatTrucks()")
    pemilih = halaman.locator(_KARTU)
    pemilih.locator(".pilih-tombol").click()
    halaman.keyboard.type(nomor.lower()[2:6])
    tampak = pemilih.locator(_OPSI_TAMPAK)
    expect(tampak.first).to_be_visible()

    halaman.keyboard.press("ArrowDown")
    expect(tampak.first).to_be_focused()
    halaman.keyboard.press("ArrowUp")
    expect(pemilih.locator(".pilih-cari")).to_be_focused()
    halaman.keyboard.press("ArrowDown")
    halaman.keyboard.type(nomor.lower()[6:])
    expect(pemilih.locator(".pilih-cari")).to_be_focused()
    expect(pemilih.locator(".pilih-cari")).to_have_value(nomor.lower()[2:])
    halaman.keyboard.press("Escape")


def test_a_short_list_has_no_search_field(halaman):
    masuk(halaman, OPERATOR)
    per = halaman.locator("#grading-per")
    per.locator(".pilih-tombol").click()
    expect(per.locator(".pilih-panel")).to_be_visible()
    expect(per.locator(".pilih-cari")).to_have_count(0)
    halaman.keyboard.press("Escape")


def test_a_weighed_in_truck_leads_the_card_list_in_its_own_section(halaman, konsol, browser_name, penugasan_bersih):
    nomor = plat(browser_name, 5603)
    _daftar(konsol, nomor, timbang_isi=True)
    masuk(halaman, OPERATOR)
    halaman.evaluate("() => muatTrucks()")
    pemilih = halaman.locator(_KARTU)

    pemilih.locator(".pilih-tombol").click()

    expect(pemilih.locator(".pilih-grup").first).to_have_text(kamus(halaman, "grupDiLokasi"))
    di_lokasi = pemilih.evaluate(
        """(root) => { const hasil = []; let grup = "";
          for (const el of root.querySelectorAll(".pilih-panel > .pilih-grup, .pilih-panel > [role=option]")) {
            if (el.classList.contains("pilih-grup")) grup = el.textContent;
            else if (el.dataset.nilai) hasil.push([grup, el.textContent]);
          }
          return hasil; }"""
    )
    judul = kamus(halaman, "grupDiLokasi")
    assert [nomor in teks for grup, teks in di_lokasi if grup == judul].count(True) == 1
    assert di_lokasi[0][0] == judul, "the on-site section comes first"
    assert kamus(halaman, "grupTrukLain") in {grup for grup, _ in di_lokasi}
    halaman.keyboard.press("Escape")


def test_the_weighbridge_pickers_are_refilled_in_place_and_stay_open(halaman, konsol, browser_name):
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")
    for id_ in ("plat-datang", "plat-timbang"):
        pemilih = halaman.locator(f"#{id_}")
        pemilih.locator(".pilih-tombol").click()
        expect(pemilih.locator(".pilih-panel")).to_be_visible()
        halaman.evaluate("(id) => { window.__pemilih = document.getElementById(id); }", id_)
        _daftar(konsol, plat(browser_name, 5604 if id_ == "plat-datang" else 5605))

        halaman.evaluate("async () => { await muatTrucks(); await muatTimbangan(); }")

        assert halaman.evaluate("(id) => document.getElementById(id) === window.__pemilih", id_), id_
        expect(pemilih.locator(".pilih-panel")).to_be_visible()
        halaman.keyboard.press("Escape")
        expect(pemilih.locator(".pilih-panel")).to_be_hidden()


def test_conveyor_direction_is_the_console_dropdown_and_moves_the_hint(halaman):
    masuk(halaman, SUPPORT)
    buka_tab(halaman, "setelan")
    halaman.evaluate("() => MUAT_TAB.setelan()")
    halaman.locator('details[data-setelan-grup="kamera"] > summary').click()
    sumbu = halaman.locator("#set-sumbu")
    awal = sumbu.get_attribute("data-nilai")
    lain = "mendatar" if awal == "tegak" else "tegak"
    try:
        sumbu.locator(".pilih-tombol").click()
        sumbu.locator(f'[role="option"][data-nilai="{lain}"]').click()

        expect(sumbu).to_have_attribute("data-nilai", lain)
        expect(sumbu.locator(".pilih-panel")).to_be_hidden()
        expect(halaman.locator("#set-garis-bantu")).to_have_text(
            kamus(halaman, "bantuGarisMendatar" if lain == "mendatar" else "bantuGarisTegak")
        )
    finally:
        # Nothing was saved; the form is put back as the server has it.
        halaman.evaluate("() => MUAT_TAB.setelan()")
        expect(sumbu).to_have_attribute("data-nilai", awal)
