"""The gate: a wrong password is worded by the screen, a right one opens the console."""

from __future__ import annotations

from langkah import OPERATOR, kamus, keluar, masuk
from playwright.sync_api import expect


def test_a_wrong_password_shows_the_screens_sentence(halaman):
    halaman.fill("#gerbang-email", OPERATOR[0])
    halaman.fill("#gerbang-sandi", "bukan-sandinya")
    halaman.click("#gerbang-masuk")
    expect(halaman.locator("#gerbang-pesan")).to_have_text(kamus(halaman, "err_sandi_salah"))
    expect(halaman.locator("#keluar")).to_be_hidden()


def test_sign_in_then_out(halaman):
    masuk(halaman, OPERATOR)
    expect(halaman.locator("#tabs")).to_be_visible()
    keluar(halaman)
    expect(halaman.locator("#keluar")).to_be_hidden()


# --- New look (spec 2026-10-07 §5.4) ------------------------------------------------------


def test_the_gate_is_split_photo_and_form_side_by_side(halaman):
    halaman.set_viewport_size({"width": 1440, "height": 900})
    hero = halaman.locator(".gerbang-hero")
    form = halaman.locator(".gerbang-form")
    expect(hero).to_be_visible()
    expect(halaman.locator("#gerbang-foto")).to_be_visible()
    kiri, kanan = hero.bounding_box(), form.bounding_box()
    assert kiri["x"] + kiri["width"] <= kanan["x"] + 1
    # The photo keeps the camera's 6:5.
    foto = halaman.locator("#gerbang-foto").bounding_box()
    assert abs(foto["width"] / foto["height"] - 1.2) < 0.02


def test_a_narrow_window_keeps_only_the_form_in_view(halaman):
    halaman.set_viewport_size({"width": 800, "height": 700})
    expect(halaman.locator(".gerbang-hero")).to_be_hidden()
    expect(halaman.locator("#gerbang-masuk")).to_be_in_viewport()


def test_a_chip_fills_the_email_and_reads_as_chosen(halaman):
    chip = halaman.locator(f'#gerbang-nama .gerbang-op[data-email="{OPERATOR[0]}"]')
    chip.click()
    expect(halaman.locator("#gerbang-email")).to_have_value(OPERATOR[0])
    expect(chip).to_have_attribute("aria-pressed", "true")
    expect(halaman.locator("#gerbang-sandi")).to_be_focused()
    halaman.fill("#gerbang-email", "orang-lain@contoh.test")
    halaman.locator("#gerbang-email").dispatch_event("input")
    expect(chip).to_have_attribute("aria-pressed", "false")


def test_the_gates_language_switch_translates_and_keeps_the_gate(halaman):
    halaman.click('#gerbang-bahasa [data-bahasa="en"]')
    expect(halaman.locator("#gerbang-judul")).to_have_text("Sign in to the console")
    expect(halaman.locator('#gerbang-bahasa [data-bahasa="en"]')).to_have_attribute("aria-pressed", "true")
    expect(halaman.locator("#gerbang")).to_be_visible()
    halaman.click('#gerbang-bahasa [data-bahasa="id"]')
    expect(halaman.locator("#gerbang-judul")).to_have_text("Masuk ke konsol")
    # Still signs in after the switch.
    masuk(halaman, OPERATOR)
    expect(halaman.locator("#keluar")).to_be_visible()
