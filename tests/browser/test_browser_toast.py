"""Success answers with a toast (user 2026-10-02: "Tolong di cek semua action button pastikan
kalo berhasil munculnya toast ya"), and the toast's words sit in the middle of the box
("kata2 di toast juga dibuat align vertical").

The actions that only had a box of text, a banner wiped by the 2 s poll, or nothing at all:
Setelan Simpan, the PLC coil test, the AutoERP resend, video recording start, and the piston.
The fake lines in this harness answer neither the PLC, the recorder nor the piston, so those
three answers are stubbed on the console's own API with `page.route`: the screen under test is
the same, only the line behind the console is pretended.
"""

from __future__ import annotations

import json
import re

import pytest
from langkah import OPERATOR, SUPPORT, buka_tab, kamus, masuk
from playwright.sync_api import expect

_SEJAJAR_PX = 2
_TENGAH = """() => [...document.querySelectorAll('#toasts .toast')].map((el) => {
  const tengah = (x) => { const r = x.getBoundingClientRect(); return r.top + r.height / 2; };
  return [tengah(el.querySelector('.pesan')), tengah(el.querySelector('.tutup')),
          el.querySelector('.pesan').getBoundingClientRect().height];
})"""


def _toast(halaman, kelas: str):
    return halaman.locator(f"#toasts .toast.{kelas}")


@pytest.mark.parametrize("teks", ["Truk terdaftar", "Kalimat panjang " * 12])
def test_a_toast_message_is_centred_on_its_close_button(halaman, teks):
    masuk(halaman, OPERATOR)
    halaman.evaluate("() => document.querySelectorAll('#toasts .toast').forEach((el) => el.remove())")
    halaman.evaluate("(t) => toastSukses(t)", teks)
    expect(_toast(halaman, "sukses")).to_have_count(1)
    (pesan, tutup, tinggi), = halaman.evaluate(_TENGAH)
    assert abs(pesan - tutup) <= _SEJAJAR_PX, (pesan, tutup, tinggi)


def _setelan_lewat(halaman, semua_sampai: bool) -> None:
    """The real save, with the answer's `lines` rewritten when every line should be reached:
    line-3 of this harness is offline on purpose."""
    def jawab(route):
        asli = route.fetch()
        isi = asli.json()
        if semua_sampai:
            isi["lines"] = [{**baris, "terkirim": True} for baris in isi.get("lines", [])]
        route.fulfill(response=asli, body=json.dumps(isi))

    halaman.route("**/api/console/dev/setelan", lambda route: jawab(route) if route.request.method == "POST"
                  else route.fallback())


@pytest.mark.parametrize("semua_sampai", [True, False])
def test_setelan_saved_is_a_toast_not_a_yellow_box(halaman, lines, semua_sampai):
    masuk(halaman, SUPPORT)
    buka_tab(halaman, "setelan")
    expect(halaman.locator("#set-conf")).not_to_have_value("")
    _setelan_lewat(halaman, semua_sampai)
    halaman.fill("#set-conf", "0.6")
    halaman.click("#set-simpan")
    if semua_sampai:
        expect(_toast(halaman, "sukses")).to_contain_text(kamus(halaman, "setelanTersimpan"))
        expect(_toast(halaman, "peringatan")).to_have_count(0)
    else:
        harap = kamus(halaman, "setelanTersimpanSebagian").replace("{lines}", "line-3")
        expect(_toast(halaman, "peringatan")).to_have_text(re.compile(re.escape(harap)))
        expect(_toast(halaman, "sukses")).to_have_count(0)
    # Nothing stays behind under the button: the box only ever carries a refusal now.
    expect(halaman.locator("#set-pesan")).to_have_text("")
    expect(halaman.locator("#set-lines")).to_have_count(0)


def test_erp_resend_answers_with_a_toast(halaman):
    masuk(halaman, SUPPORT)
    buka_tab(halaman, "status")
    halaman.click("#antrean-kirim-ulang")
    expect(_toast(halaman, "sukses")).to_contain_text(
        kamus(halaman, "antreanDikirimUlang").replace("{n}", "0"))


_PLC = {"enabled": True, "coil_base": 1000, "testable_coils": [1000, 1001], "device_prefix": "M"}


def test_plc_coil_test_answers_with_a_toast_that_outlives_the_poll(halaman):
    """The result used to go to the `#err` banner, which `refresh()` empties within 2 s."""
    jawaban = iter([{"fired": True}, {"fired": False}])
    halaman.route(re.compile(r".*/api/console/dev/plc/line-[0-9]+$"),
                  lambda route: route.fulfill(json=_PLC))
    halaman.route(re.compile(r".*/api/console/dev/plc/line-[0-9]+/coil$"),
                  lambda route: route.fulfill(json=next(jawaban)))
    masuk(halaman, SUPPORT)
    buka_tab(halaman, "line")
    halaman.click('[data-sub="plc"]')
    coil = halaman.locator('#plc-kartu button.uji-coil[data-line="line-1"][data-coil="1001"]')
    for kelas, kunci in (("sukses", "ujiPlcBerhasil"), ("peringatan", "ujiPlcDijatuhkan")):
        coil.click()
        halaman.click("#plc-konfirmasi-jalankan")
        expect(_toast(halaman, kelas)).to_contain_text(kamus(halaman, kunci).replace("{coil}", "1001"))
    # Still there after a poll has run: a toast is not the banner `refresh()` wipes.
    halaman.evaluate("() => refresh()")
    expect(_toast(halaman, "sukses")).to_have_count(1)


def test_recording_start_answers_with_a_toast(halaman):
    keadaan = {"merekam": False}

    def baris() -> dict:
        return {"line_code": "line-1", "terbaca": True, "merekam": keadaan["merekam"],
                "mulai_epoch": None, "frame_ditulis": 0, "bytes": 0}

    def status(route):
        if route.request.method != "GET":
            return route.fallback()
        return route.fulfill(json={"lines": [baris()], "setelan": {}, "folder": "videos", "disk_bebas_gb": 100})

    def mulai(route):
        keadaan["merekam"] = True
        route.fulfill(json=baris())

    halaman.route("**/api/console/dev/rekam", status)
    halaman.route("**/api/console/dev/rekam/line-1/mulai", mulai)
    masuk(halaman, SUPPORT)
    buka_tab(halaman, "line")
    halaman.click('[data-sub="rekam"]')
    halaman.click('[data-rekam-mulai="line-1"]')
    expect(_toast(halaman, "sukses")).to_contain_text(kamus(halaman, "rekamDimulai").replace("{line}", "line-1"))


def test_piston_command_answers_with_a_toast(halaman):
    halaman.route("**/api/console/lines/line-1/piston", lambda route: route.fulfill(json={"ok": True}))
    masuk(halaman, OPERATOR)
    tombol = halaman.locator('.card[data-line="line-1"] button.piston')
    expect(tombol).to_be_enabled()
    nama = halaman.locator('.card[data-line="line-1"] .nama').inner_text().strip()
    kunci = "sukPistonBuka" if tombol.get_attribute("data-buka") == "1" else "sukPistonTutup"
    halaman.once("dialog", lambda dialog: dialog.accept())
    tombol.click()
    expect(_toast(halaman, "sukses")).to_contain_text(kamus(halaman, kunci).replace("{line}", nama))
