"""Setelan tab: a saved threshold is kept by the console and sent to every line that answers;
the one that does not is named in a warning toast (its value is still saved)."""

from __future__ import annotations

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
    expect(halaman.locator("#toasts .toast.peringatan")).to_contain_text(
        kamus(halaman, "setelanTersimpanSebagian").replace("{lines}", "line-3")
    )
    expect(halaman.locator("#set-pesan")).to_have_text("")
    for kode in _HIDUP:
        terkirim = [isi for jalur, isi in lines[kode].diterima if jalur == "/internal/setelan"]
        assert terkirim and terkirim[-1]["conf_threshold"] == 0.6, (kode, terkirim)
