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
