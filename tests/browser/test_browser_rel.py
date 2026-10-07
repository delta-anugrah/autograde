"""Left rail (spec 2026-10-07 §5.1): the hide button is kept per browser, the cameras belong
to the Grading view, and keyboard reject still works from any other view."""

from __future__ import annotations

from langkah import OPERATOR, buka_menu_line, buka_tab, kamus, masuk, plat
from playwright.sync_api import expect


def test_hiding_the_side_menu_survives_a_reload(halaman):
    masuk(halaman, OPERATOR)
    expect(halaman.locator("#tabs")).to_be_visible()
    halaman.click("#menu-samping")
    expect(halaman.locator("body")).to_have_class("menu-tutup")
    expect(halaman.locator("#menu-samping")).to_have_attribute("aria-expanded", "false")
    halaman.reload()
    expect(halaman.locator("body")).to_have_class("menu-tutup")
    halaman.click("#menu-samping")
    expect(halaman.locator("#menu-samping")).to_have_attribute("aria-expanded", "true")
    expect(halaman.locator('#tabs [data-tab="grading"]')).to_be_in_viewport()


def test_cameras_only_on_the_grading_view(halaman):
    masuk(halaman, OPERATOR)
    expect(halaman.locator("#lines")).to_be_visible()
    expect(halaman.locator("#judul-tampilan")).to_have_text("AutoGrade")
    expect(halaman.locator('#tabs [data-tab="grading"]')).to_have_class("aktif")
    buka_tab(halaman, "truk")
    expect(halaman.locator("#lines")).to_be_hidden()
    expect(halaman.locator("#lines .card")).not_to_have_count(0)
    expect(halaman.locator('#tabs [data-tab="truk"]')).to_have_class("aktif")


def test_space_and_line_number_rejects_from_the_truck_view(halaman, lines, browser_name, penugasan_bersih):
    nomor = plat(browser_name, 1031)
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "truk")
    halaman.fill("#plat", nomor)
    halaman.click("#daftar")
    expect(halaman.locator("#trucks")).to_contain_text(nomor)
    buka_tab(halaman, "grading")
    kartu = halaman.locator('#lines .card[data-line="line-1"]')
    buka_menu_line(kartu)
    kartu.locator(".pilih-tombol").click()
    kartu.locator('[role="option"]', has_text=nomor).click()
    kartu.locator('[data-aksi="tugaskan"]').click()
    expect(kartu.locator("button.reject")).to_be_enabled()

    nama_line = kartu.locator(".nama").text_content().strip()
    sebelum = len([1 for jalur, _ in lines["line-1"].diterima if jalur == "/internal/manual-reject"])
    buka_tab(halaman, "truk")
    halaman.locator("#judul-tampilan").click()
    halaman.keyboard.down("Space")
    halaman.keyboard.press("1")
    halaman.keyboard.up("Space")
    # The hidden card still took the shortcut: the line got the command.
    expect(halaman.locator("#toasts")).to_contain_text(kamus(halaman, "sukReject").replace("{line}", nama_line))
    sesudah = len([1 for jalur, _ in lines["line-1"].diterima if jalur == "/internal/manual-reject"])
    assert sesudah == sebelum + 1
