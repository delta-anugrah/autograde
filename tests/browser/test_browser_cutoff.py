"""Working day cutoff (batch 5.11): support sets it in Settings, the Rekap names it.

The setting lives for the whole session's console: it is put back to 00:00 after each test.
"""
from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from langkah import OPERATOR, SUPPORT, buka_setelan, buka_tab, kamus, keluar, masuk
from playwright.sync_api import expect


def _atur(konsol, cutoff: str) -> None:
    with httpx.Client(base_url=konsol.url, timeout=10) as c:
        c.post("/api/console/login", json={"email": SUPPORT[0], "sandi": SUPPORT[1]}).raise_for_status()
        c.post("/api/console/dev/shift", json={"cutoff": cutoff}).raise_for_status()


@pytest.fixture
def tengah_malam(konsol) -> Iterator[None]:
    _atur(konsol, "00:00")
    yield
    _atur(konsol, "00:00")


def test_support_sets_five_and_the_rekap_says_so(halaman, tengah_malam):
    masuk(halaman, SUPPORT)
    buka_setelan(halaman, "harikerja")
    halaman.evaluate("() => MUAT_TAB.setelan()")
    expect(halaman.locator("#set-cutoff")).to_have_value("00:00")
    halaman.fill("#set-cutoff", "05:00")
    halaman.click("#set-cutoff-simpan")
    expect(halaman.locator("#toasts .toast.sukses", has_text=kamus(halaman, "cutoffTersimpan"))).to_be_visible()
    keluar(halaman)

    masuk(halaman, OPERATOR)
    buka_tab(halaman, "rekap")
    expect(halaman.locator("#riwayat-cutoff")).to_have_text(kamus(halaman, "rekapCutoff").replace("{jam}", "05:00"))


def test_midnight_shows_no_label(halaman, tengah_malam):
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "rekap")
    expect(halaman.locator("#riwayat-cutoff")).to_be_hidden()


def test_a_time_after_noon_is_refused_in_words(halaman, tengah_malam):
    masuk(halaman, SUPPORT)
    buka_setelan(halaman, "harikerja")
    halaman.evaluate("() => MUAT_TAB.setelan()")
    halaman.evaluate("() => { const el = document.getElementById('set-cutoff'); el.removeAttribute('max'); el.value = '13:00'; }")
    halaman.click("#set-cutoff-simpan")
    expect(halaman.locator("#toasts .toast.gagal")).to_contain_text(kamus(halaman, "err_cutoff_tidak_sah"))
