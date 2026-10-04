"""Setelan tab: a saved threshold is kept by the console and sent to every line that answers;
the one that does not is named in a warning toast (its value is still saved)."""

from __future__ import annotations

import re

from langkah import SUPPORT, buka_tab, kamus, masuk
from playwright.sync_api import expect

_HIDUP = ("line-1", "line-2")


def test_a_saved_threshold_reaches_the_lines_that_answer(halaman, lines):
    # The fake lines live for the whole session: start from nothing, so a local two-browser
    # run cannot pass on the other browser's save.
    for kode in _HIDUP:
        lines[kode].diterima.clear()
    masuk(halaman, SUPPORT)
    buka_tab(halaman, "setelan")
    expect(halaman.locator("#set-conf")).not_to_have_value("")
    halaman.fill("#set-conf", "0.6")
    halaman.click("#set-simpan")
    # One warning toast that says it is saved and names the line that did not answer
    # (user 2026-10-02: the yellow box under the button read like a failure).
    sebagian = kamus(halaman, "setelanTersimpanSebagian").replace("{lines}", "line-3")
    expect(halaman.locator("#toasts .toast.peringatan", has_text=sebagian)).to_have_count(1)
    expect(halaman.locator("#set-pesan")).to_have_text("")
    for kode in _HIDUP:
        terkirim = [isi for jalur, isi in lines[kode].diterima if jalur == "/internal/setelan"]
        assert terkirim and terkirim[-1]["conf_threshold"] == 0.6, (kode, terkirim)


def test_the_detection_box_and_the_two_show_switches_reach_the_lines(halaman, lines):
    """Camera & Conveyor (2026-10-04): the box goes out as four numbers, the two switches as
    booleans; four empty inputs go out as null, which leaves each line its own box."""
    for kode in _HIDUP:
        lines[kode].diterima.clear()
    masuk(halaman, SUPPORT)
    buka_tab(halaman, "setelan")
    expect(halaman.locator("#set-conf")).not_to_have_value("")
    halaman.locator('details[data-setelan-grup="kamera"] > summary').click()
    for sisi, nilai in (("x1", "100"), ("y1", "50"), ("x2", "1180"), ("y2", "620")):
        halaman.fill(f"#set-roi-{sisi}", nilai)
    halaman.uncheck("#set-tampil-garis")
    halaman.click("#set-simpan")
    expect(halaman.locator("#toasts .toast.peringatan")).to_have_count(1)
    for kode in _HIDUP:
        isi = [isi for jalur, isi in lines[kode].diterima if jalur == "/internal/setelan"][-1]
        assert (isi["roi_x1"], isi["roi_y1"], isi["roi_x2"], isi["roi_y2"]) == (100, 50, 1180, 620), isi
        assert (isi["tampil_garis"], isi["tampil_roi"]) == (False, True), isi

    # A box with no width is refused, its input is marked, nothing is sent.
    for kode in _HIDUP:
        lines[kode].diterima.clear()
    halaman.fill("#set-roi-x2", "100")
    halaman.click("#set-simpan")
    expect(halaman.locator("#set-roi-x2")).to_have_attribute("aria-invalid", "true")
    assert not any(jalur == "/internal/setelan" for kode in _HIDUP for jalur, _ in lines[kode].diterima)

    # Back to "not set here": all four empty, and the switch on again for the next test.
    for sisi in ("x1", "y1", "x2", "y2"):
        halaman.fill(f"#set-roi-{sisi}", "")
    halaman.check("#set-tampil-garis")
    halaman.click("#set-simpan")
    # Not a toast count: the first toast closes by itself and may be gone on a slow runner.
    # The button is busy for the whole save, so its release means the lines were told.
    expect(halaman.locator("#set-simpan")).not_to_have_class(re.compile(r"\bsibuk\b"))
    halaman.wait_for_function("() => document.querySelector('#set-pesan').textContent === ''")
    terkirim = [isi for jalur, isi in lines["line-1"].diterima if jalur == "/internal/setelan"]
    assert terkirim, "the save never reached line-1"
    assert terkirim[-1]["roi_x1"] is None and terkirim[-1]["tampil_garis"] is True, terkirim[-1]
