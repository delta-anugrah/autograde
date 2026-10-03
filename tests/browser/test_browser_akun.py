"""Akun tab: support adds a local operator account, and that account can sign in."""

from __future__ import annotations

from langkah import SUPPORT, buka_tab, kamus, keluar, masuk
from playwright.sync_api import expect

SANDI = "sandiuji123"  # PASSWORD_MIN_LENGTH is 8


def test_a_new_account_can_sign_in(halaman, browser_name):
    email = f"uji-{browser_name}@pks.test"
    masuk(halaman, SUPPORT)
    buka_tab(halaman, "akun")
    halaman.click("#akun-tambah-buka")
    halaman.fill("#akun-nama", "Uji Browser")
    halaman.fill("#akun-email", email)
    halaman.select_option("#akun-role", "operator")
    halaman.fill("#akun-sandi", SANDI)
    halaman.fill("#akun-sandi-ulang", SANDI)
    halaman.click("#akun-tambah-simpan")
    expect(halaman.locator("#toasts")).to_contain_text(kamus(halaman, "akunDibuat").replace("{email}", email))
    expect(halaman.locator("#akun-baris")).to_contain_text(email)

    keluar(halaman)
    masuk(halaman, (email, SANDI))
