"""Timbangan board (owner 2026-10-08): a truck walks the four columns, and every button on its
card runs the table's own flow (bruto form, tara bar, Keluar)."""

from __future__ import annotations

from langkah import OPERATOR, buka_tab, masuk, plat
from playwright.sync_api import expect


def _pilih(halaman, form: str, nomor: str) -> None:
    f = halaman.locator(form)
    f.locator(".pilih-tombol").click()
    f.locator('[role="option"]', has_text=nomor).first.click()


def _kartu(halaman, kolom: str, nomor: str):
    return halaman.locator(f"#papan-isi-{kolom} .papan-kartu", has_text=nomor)


def test_a_truck_walks_the_board_through_its_buttons(halaman, browser_name):
    nomor = plat(browser_name, 2101)
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "truk")
    halaman.fill("#plat", nomor)
    halaman.click("#daftar")
    expect(halaman.locator("#trucks")).to_contain_text(nomor)
    buka_tab(halaman, "timbangan")

    # 1. Datang: the card offers Timbang isi, which fills the bruto form and waits for the weight.
    _pilih(halaman, ".timbang-form.ruas-datang", nomor)
    halaman.locator(".timbang-form.ruas-datang button.utama").click()
    datang = _kartu(halaman, "datang", nomor)
    expect(datang).to_be_visible(timeout=20_000)
    datang.locator('button[data-papan="timbang-isi"]').click()
    expect(halaman.locator("#plat-timbang")).to_have_attribute("data-nilai", nomor)
    expect(halaman.locator("#bruto")).to_be_focused()
    halaman.fill("#bruto", "21500")
    halaman.locator(".timbang-form.timbang-isi button.utama").click()

    # 2. Bongkar: Timbang kosong on the card opens the tara bar for this truck.
    bongkar = _kartu(halaman, "bongkar", nomor)
    expect(bongkar).to_be_visible(timeout=20_000)
    expect(bongkar).to_contain_text("21.500")
    bongkar.locator('button[data-papan="timbang-kosong"]').click()
    expect(halaman.locator("#tara-grup")).to_be_visible()
    expect(halaman.locator("#tara-plat")).to_have_text(nomor)
    halaman.fill("#tara-nilai", "6000")
    halaman.click("#tara-simpan")

    # 3. Timbang kosong: neto on the card, then Keluar.
    kosong = _kartu(halaman, "kosong", nomor)
    expect(kosong).to_be_visible(timeout=20_000)
    expect(kosong).to_contain_text("15.500")
    kosong.locator('button[data-papan="pergi"]').click()

    # 4. Selesai, newest first.
    expect(halaman.locator("#papan-isi-selesai .papan-kartu").first).to_contain_text(nomor, timeout=20_000)
    expect(_kartu(halaman, "selesai", nomor).locator("button")).to_have_count(0)


def test_the_board_counts_and_the_full_table_stays_under_it(halaman):
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")
    for kolom in ("datang", "bongkar", "kosong", "selesai"):
        jumlah = halaman.locator(f"#papan-jumlah-{kolom}")
        isi = halaman.locator(f"#papan-isi-{kolom} .papan-kartu")
        expect(jumlah).to_be_visible()
        if kolom != "selesai":
            expect(jumlah).to_have_text(str(isi.count()))
    papan = halaman.locator("#papan-timbang").bounding_box()
    tabel = halaman.locator("#timbangan").bounding_box()
    assert papan["y"] + papan["height"] <= tabel["y"]
