"""One in-page confirm dialog instead of the browser's own box (user 2026-10-03).

`tanyaKonfirmasi()` resolves to true only from its confirm button (click or Enter); Batal,
Esc and a click on the backdrop answer false, and the focus comes back to the button that
opened it. The piston and Lewati (unloading queue, `test_browser_penugasan.py`) ask through
it. The fake lines answer no piston command, so that answer is stubbed with `page.route`,
as `test_browser_toast.py` does.
"""

from __future__ import annotations

import re

from langkah import OPERATOR, kamus, masuk
from playwright.sync_api import expect

_BUKA = """(opsi) => { window.__jawaban = undefined;
  tanyaKonfirmasi(opsi).then((j) => { window.__jawaban = j; }); }"""


def _jawaban(halaman):
    halaman.wait_for_function("() => window.__jawaban !== undefined")
    return halaman.evaluate("() => window.__jawaban")


def _buka_dari(halaman, pemicu: str, **opsi) -> None:
    """Open the dialog the way a button does: the trigger holds the focus first."""
    halaman.focus(pemicu)
    halaman.evaluate(_BUKA, {"judul": "Judul uji", "pesan": "Pesan uji", **opsi})
    expect(halaman.locator("#konfirmasi-modal")).to_be_visible()


def test_batal_esc_and_backdrop_answer_no_and_focus_comes_back(halaman):
    bawaan: list[str] = []
    halaman.on("dialog", lambda d: (bawaan.append(d.message), d.dismiss()))
    masuk(halaman, OPERATOR)
    dialog = halaman.locator("#konfirmasi-modal")

    _buka_dari(halaman, "#bahasa")
    expect(dialog.locator("#konfirmasi-judul")).to_have_text("Judul uji")
    expect(dialog.locator("#konfirmasi-pesan")).to_have_text("Pesan uji")
    # The safe choice holds the focus, so an accidental Enter cancels.
    expect(dialog.locator("#konfirmasi-tidak")).to_be_focused()
    expect(dialog.locator("#konfirmasi-tidak")).to_have_text(kamus(halaman, "konfirmasiTidak"))
    expect(dialog.locator("#konfirmasi-ya")).to_have_text(kamus(halaman, "konfirmasiYa"))
    halaman.click("#konfirmasi-tidak")
    assert _jawaban(halaman) is False
    expect(dialog).to_be_hidden()
    expect(halaman.locator("#bahasa")).to_be_focused()

    _buka_dari(halaman, "#bahasa")
    halaman.keyboard.press("Escape")
    assert _jawaban(halaman) is False
    expect(dialog).to_be_hidden()
    expect(halaman.locator("#bahasa")).to_be_focused()

    _buka_dari(halaman, "#bahasa")
    kotak = dialog.bounding_box()
    # Outside the box, on the backdrop.
    halaman.mouse.click(kotak["x"] / 2, kotak["y"] / 2)
    assert _jawaban(halaman) is False
    expect(dialog).to_be_hidden()
    assert not bawaan, bawaan


def test_enter_on_the_confirm_button_answers_yes(halaman):
    masuk(halaman, OPERATOR)
    _buka_dari(halaman, "#bahasa", ya="Ya, uji")
    tombol = halaman.locator("#konfirmasi-ya")
    expect(tombol).to_have_text("Ya, uji")
    expect(tombol).to_have_class("utama")
    tombol.focus()
    halaman.keyboard.press("Enter")
    assert _jawaban(halaman) is True
    expect(halaman.locator("#konfirmasi-modal")).to_be_hidden()
    expect(halaman.locator("#bahasa")).to_be_focused()


def test_danger_makes_the_confirm_red_and_leaves_cancel_plain(halaman):
    masuk(halaman, OPERATOR)
    _buka_dari(halaman, "#bahasa", bahaya=True)
    expect(halaman.locator("#konfirmasi-ya")).to_have_class(re.compile(r"^bahaya pekat$"))
    assert halaman.locator("#konfirmasi-tidak").evaluate("(el) => el.classList.length") == 0
    halaman.click("#konfirmasi-ya")
    assert _jawaban(halaman) is True


def test_a_second_question_answers_the_first_with_no(halaman):
    masuk(halaman, OPERATOR)
    _buka_dari(halaman, "#bahasa")
    halaman.evaluate("() => { window.__kedua = tanyaKonfirmasi({judul: 'Kedua'}); }")
    assert _jawaban(halaman) is False
    expect(halaman.locator("#konfirmasi-modal")).to_be_visible()
    expect(halaman.locator("#konfirmasi-judul")).to_have_text("Kedua")
    halaman.click("#konfirmasi-ya")
    assert halaman.evaluate("() => window.__kedua") is True


def test_piston_open_asks_in_the_page_and_cancel_sends_nothing(halaman):
    terkirim: list[str] = []

    def piston(route):
        terkirim.append(route.request.post_data or "")
        route.fulfill(json={"ok": True})

    halaman.route("**/api/console/lines/line-1/piston", piston)
    bawaan: list[str] = []
    halaman.on("dialog", lambda d: (bawaan.append(d.message), d.dismiss()))
    masuk(halaman, OPERATOR)
    kartu = halaman.locator('.card[data-line="line-1"]')
    tombol = kartu.locator("button.piston")
    expect(tombol).to_have_attribute("data-buka", "1")
    nama = kartu.locator(".nama").inner_text().strip()
    dialog = halaman.locator("#konfirmasi-modal")

    tombol.click()
    expect(dialog).to_be_visible()
    expect(dialog.locator("#konfirmasi-judul")).to_have_text(kamus(halaman, "konfirmasiBukaJudul").replace("{line}", nama))
    expect(dialog.locator("#konfirmasi-pesan")).to_have_text(kamus(halaman, "konfirmasiBuka"))
    expect(dialog.locator("#konfirmasi-ya")).to_have_text(kamus(halaman, "btnPistonBuka"))
    halaman.click("#konfirmasi-tidak")
    expect(dialog).to_be_hidden()
    halaman.evaluate("() => refresh()")
    assert terkirim == [], terkirim

    kartu.locator("button.piston").click()
    halaman.click("#konfirmasi-ya")
    expect(halaman.locator("#toasts .toast.sukses",
                           has_text=kamus(halaman, "sukPistonBuka").replace("{line}", nama))).to_have_count(1)
    assert len(terkirim) == 1 and '"open":true' in terkirim[0].replace(" ", ""), terkirim
    assert not bawaan, bawaan
