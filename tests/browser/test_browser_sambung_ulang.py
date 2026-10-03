"""Sambung ulang on a line card: ask, lock, reach the line, toast (user 2026-10-04).

Every account has the button. The fake line records the POST and can be told to answer
late (the busy lock must survive a full card redraw) or as a video line (409 with a code).
"""

from __future__ import annotations

from langkah import JEDA_HALAMAN_MS, OPERATOR, kamus, masuk
from playwright.sync_api import expect

_JALUR = "/internal/camera/reconnect"


def _diminta(line) -> list[dict]:
    return [isi for jalur, isi in line.diterima if jalur == _JALUR]


def _tekan(halaman, kode: str):
    kartu = halaman.locator(f'#lines .card[data-line="{kode}"]')
    tombol = kartu.locator('button[data-aksi="sambung-ulang"]')
    expect(tombol).to_be_visible()
    tombol.click()
    expect(halaman.locator("#konfirmasi-modal")).to_be_visible()
    return kartu


def test_yes_reaches_the_line_with_the_operator_name_and_toasts(halaman, lines):
    masuk(halaman, OPERATOR)
    sebelum = len(_diminta(lines["line-1"]))
    kartu = _tekan(halaman, "line-1")
    nama_line = kartu.locator(".nama").inner_text().strip()
    expect(halaman.locator("#konfirmasi-judul")).to_have_text(
        kamus(halaman, "konfirmasiSambungUlangJudul").replace("{line}", nama_line)
    )
    expect(halaman.locator("#konfirmasi-ya")).to_have_text(kamus(halaman, "btnSambungUlang"))
    halaman.click("#konfirmasi-ya")

    expect(halaman.locator("#toasts .toast.sukses")).to_contain_text(
        kamus(halaman, "sukSambungUlang").replace("{line}", nama_line)
    )
    diminta = _diminta(lines["line-1"])
    assert len(diminta) == sebelum + 1, diminta
    assert diminta[-1].get("requested_by") not in (None, "", "?"), diminta[-1]


def test_cancel_sends_nothing(halaman, lines):
    masuk(halaman, OPERATOR)
    sebelum = len(_diminta(lines["line-1"]))
    _tekan(halaman, "line-1")
    halaman.click("#konfirmasi-tidak")
    expect(halaman.locator("#konfirmasi-modal")).to_be_hidden()
    halaman.wait_for_timeout(JEDA_HALAMAN_MS)
    assert len(_diminta(lines["line-1"])) == sebelum


def test_the_busy_lock_survives_a_full_card_redraw(halaman, lines):
    """A language switch, login or truck list rebuilds every card while the line answers."""
    lines["line-1"].atur_sambung_ulang(jeda=2.0)
    try:
        masuk(halaman, OPERATOR)
        kartu = _tekan(halaman, "line-1")
        halaman.click("#konfirmasi-ya")
        tombol = kartu.locator('button[data-aksi="sambung-ulang"]')
        expect(tombol).to_have_class("sambung-ulang sibuk")
        halaman.evaluate("async () => { dipasang = false; await refresh(); }")
        expect(tombol).to_have_class("sambung-ulang sibuk")
        expect(halaman.locator("#toasts .toast.sukses")).to_be_visible()
        expect(tombol).to_have_class("sambung-ulang")
        expect(tombol).not_to_have_attribute("aria-busy", "true")
    finally:
        lines["line-1"].atur_sambung_ulang()


def test_a_video_line_is_worded_from_the_code(halaman, lines):
    lines["line-2"].atur_sambung_ulang(tanpa_kamera=True)
    try:
        masuk(halaman, OPERATOR)
        kartu = _tekan(halaman, "line-2")
        nama_line = kartu.locator(".nama").inner_text().strip()
        halaman.click("#konfirmasi-ya")
        sebab = kamus(halaman, "err_kamera_tanpa_sambung_ulang").replace("{line}", nama_line)
        expect(halaman.locator("#toasts .toast.gagal")).to_contain_text(sebab)
        expect(halaman.locator("#toasts .toast.gagal")).not_to_contain_text("409")
    finally:
        lines["line-2"].atur_sambung_ulang()
