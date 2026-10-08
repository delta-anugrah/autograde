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


def test_the_photo_keeps_its_ratio_on_a_half_screen_window(halaman):
    """Review PR 4+5: at 960 x 1080 the frame's width was clamped while its height stayed, and
    the photo was squashed about 20 % (spec §6: never stretched)."""
    halaman.set_viewport_size({"width": 960, "height": 1080})
    foto = halaman.locator("#gerbang-foto")
    expect(foto).to_be_visible()
    kotak = foto.bounding_box()
    assert abs(kotak["width"] / kotak["height"] - 1.2) < 0.02, kotak


def test_many_accounts_keep_masuk_on_the_first_screen(halaman):
    """Review PR 4+5: one chip per row pushed Masuk below 768 px from seven accounts on."""
    akun = [{"email": f"op{i}@pks.test", "full_name": f"Operator {i}", "role": "operator"} for i in range(1, 10)]
    halaman.route("**/api/console/operators", lambda r: r.fulfill(json={"items": akun}))
    halaman.set_viewport_size({"width": 1366, "height": 768})
    halaman.reload()
    expect(halaman.locator("#gerbang-nama .gerbang-op")).to_have_count(9)
    expect(halaman.locator("#gerbang-masuk")).to_be_in_viewport()


def test_a_brand_new_browser_signs_in_in_english(halaman, konsol):
    """Owner 2026-10-08: the sign-in a prospect sees is English; a used browser keeps its language."""
    baru = halaman.context.browser.new_context()
    try:
        pg = baru.new_page()
        pg.goto(konsol.url + "/console")
        expect(pg.locator("#gerbang-judul")).to_have_text("Sign in to the console")
        expect(pg.locator('#gerbang-bahasa [data-bahasa="en"]')).to_have_attribute("aria-pressed", "true")
        pg.click('#gerbang-bahasa [data-bahasa="id"]')
        pg.reload()
        expect(pg.locator("#gerbang-judul")).to_have_text("Masuk ke konsol")
    finally:
        baru.close()


def test_the_sign_in_photo_turns_to_the_next_class(halaman):
    bingkai = halaman.locator(".gerbang-bingkai")
    expect(bingkai).to_have_attribute("data-kelas", "ripe")
    expect(bingkai).to_have_attribute("data-kelas", "unripe", timeout=6_000)
    expect(halaman.locator(".gerbang-deteksi span")).to_have_text(kamus(halaman, "clsUnripe"))


def test_a_hovered_chip_is_not_cut_by_its_list(halaman):
    chip = halaman.locator("#gerbang-nama .gerbang-op").first
    chip.hover()
    halaman.wait_for_timeout(300)
    daftar = halaman.locator("#gerbang-nama").evaluate(
        "(el) => { const r = el.getBoundingClientRect(); const c = el.firstElementChild.getBoundingClientRect();"
        " return { atas: c.top - r.top, padding: parseFloat(getComputedStyle(el).paddingTop) }; }"
    )
    assert daftar["atas"] >= 2, daftar
