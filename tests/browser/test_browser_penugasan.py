"""Automatic line assignment on the screen: the Setelan switch (support only), a weigh-in
that puts the truck on every chosen line that answers, the unloading queue strip above the
line cards with "Tugaskan sekarang" and "Lewati", and the toasts that say what happened.

The console and the fake lines live for the whole session, so every test runs inside
`penugasan_bersih` (switch OFF, lines 1-2 free, queue empty, before and after) and weighs
out every truck it weighed in. line-3 is the offline line: chosen, it is the line that
"did not answer". Trucks are registered on the Truk tab, which redraws the plate pickers at
once (one registered through the API would wait for the 60 s poll).
"""

from __future__ import annotations

import re

from langkah import OPERATOR, SUPPORT, buka_menu_line, buka_setelan, buka_tab, kamus, keluar, masuk, plat
from playwright.sync_api import expect

_DUA_LINE = ("line-1", "line-2")
_TIGA_LINE = ("line-1", "line-2", "line-3")
_PENUGASAN = "/api/console/dev/auto-assign"
_PERINTAH_LINE = "/internal/assignment"


def _nyalakan(halaman, konsol, lines) -> None:
    r = halaman.request.post(konsol.url + _PENUGASAN, data={"aktif": True, "lines": list(lines)})
    assert r.status == 200, r.text()


def _daftar(halaman, *nomor: str) -> None:
    buka_tab(halaman, "truk")
    for n in nomor:
        halaman.fill("#plat", n)
        halaman.click("#daftar")
        expect(halaman.locator("#trucks")).to_contain_text(n)


def _isi(halaman, nomor: str, bruto: str = "14000") -> None:
    """Weigh-in on the Timbangan tab, with the browser clock, the way the operator does it."""
    buka_tab(halaman, "timbangan")
    pilih = halaman.locator("#plat-timbang")
    pilih.locator(".pilih-tombol").click()
    pilih.locator('[role="option"]', has_text=nomor).click()
    expect(pilih).to_have_attribute("data-nilai", nomor)
    halaman.fill("#bruto", bruto)
    halaman.click("#masuk")
    expect(halaman.locator("#toasts")).to_contain_text(kamus(halaman, "sukMasuk"))
    # Back where the operator watches the cards and the queue (Grading only since 2026-10-07).
    buka_tab(halaman, "grading")


def _kosong(halaman, nomor: str, tara: str = "6000") -> None:
    """Weigh-out from the ticket row: the tare box, then the toast."""
    buka_tab(halaman, "timbangan")
    halaman.evaluate("() => muatTimbangan()")
    baris = halaman.locator("#timbangan tr", has_text=nomor)
    baris.locator('button[data-aksi="keluar"]').click()
    expect(halaman.locator("#tara-plat")).to_have_text(nomor)
    halaman.fill("#tara-nilai", tara)
    halaman.click("#tara-simpan")
    expect(halaman.locator("#toasts")).to_contain_text(kamus(halaman, "sukTara"))
    expect(baris.locator('button[data-aksi="keluar"]')).to_have_count(0)
    buka_tab(halaman, "grading")


def _kartu(halaman, kode: str):
    return halaman.locator(f'#lines .card[data-line="{kode}"]')


def _nama(halaman, kode: str) -> str:
    return _kartu(halaman, kode).locator(".nama").inner_text().strip()


def _ditugaskan(halaman, nomor: str, kode_lines) -> str:
    nama = ", ".join(_nama(halaman, k) for k in kode_lines)
    return kamus(halaman, "sukDitugaskanOtomatis").replace("{truk}", nomor).replace("{line}", nama)


def _antre(halaman, nomor: str):
    return halaman.locator(f'#antrean-bongkar .antrean-truk[data-plat="{nomor}"]')


def _terkirim(lines, kode: str) -> list[dict]:
    return [isi for jalur, isi in lines[kode].diterima if jalur == _PERINTAH_LINE]


def test_the_switch_keeps_what_support_saved(halaman, konsol, penugasan_bersih):
    masuk(halaman, SUPPORT)
    buka_setelan(halaman, "penugasan")
    expect(halaman.locator("#set-otomatis")).not_to_be_checked()
    pilihan = halaman.locator("#set-otomatis-lines input[data-line]")
    expect(pilihan).to_have_count(3)
    for i in range(3):
        expect(pilihan.nth(i)).to_be_checked()

    halaman.check("#set-otomatis")
    halaman.uncheck('#set-otomatis-lines input[data-line="line-3"]')
    halaman.click("#set-penugasan-simpan")
    expect(halaman.locator("#toasts .toast.sukses", has_text=kamus(halaman, "penugasanTersimpan"))).to_have_count(1)

    halaman.reload()
    expect(halaman.locator("#keluar")).to_be_visible()
    buka_setelan(halaman, "penugasan")
    expect(halaman.locator("#set-otomatis")).to_be_checked()
    expect(halaman.locator('#set-otomatis-lines input[data-line="line-3"]')).not_to_be_checked()
    expect(halaman.locator('#set-otomatis-lines input[data-line="line-1"]')).to_be_checked()
    simpanan = halaman.request.get(konsol.url + _PENUGASAN).json()
    assert simpanan["aktif"] is True and simpanan["lines"] == ["line-1", "line-2"], simpanan


def test_an_operator_cannot_reach_the_switch(halaman, konsol):
    masuk(halaman, OPERATOR)
    for r in (
        halaman.request.get(konsol.url + _PENUGASAN),
        halaman.request.post(konsol.url + _PENUGASAN, data={"aktif": True, "lines": ["line-1"]}),
    ):
        assert r.status == 403, r.text()
        assert r.json()["detail"]["code"] == "bukan_support"


def test_weigh_in_puts_the_truck_on_every_line_that_answers(halaman, konsol, lines, browser_name, penugasan_bersih):
    nomor = plat(browser_name, 1101)
    masuk(halaman, SUPPORT)
    _nyalakan(halaman, konsol, _TIGA_LINE)
    for kode in _DUA_LINE:
        lines[kode].diterima.clear()
    _daftar(halaman, nomor)
    _isi(halaman, nomor)

    toasts = halaman.locator("#toasts")
    expect(toasts).to_contain_text(_ditugaskan(halaman, nomor, _DUA_LINE))
    expect(toasts).to_contain_text(
        kamus(halaman, "tugaskanGagalLine").replace("{line}", _nama(halaman, "line-3")).replace("{truk}", nomor)
    )
    for kode in _DUA_LINE:
        expect(_kartu(halaman, kode).locator(".truk")).to_contain_text(nomor)
        assert any(isi.get("plate") == nomor for isi in _terkirim(lines, kode)), _terkirim(lines, kode)
    expect(_kartu(halaman, "line-3").locator(".truk")).not_to_contain_text(nomor)

    _kosong(halaman, nomor)
    for kode in _DUA_LINE:
        expect(_kartu(halaman, kode).locator(".truk")).not_to_contain_text(nomor)
        perintah = _terkirim(lines, kode)
        pasang = next(i for i, isi in enumerate(perintah) if isi.get("plate") == nomor)
        assert any(isi.get("assignment_id") == "" for isi in perintah[pasang + 1 :]), perintah


def _a_di_line_b_antre(halaman, konsol, browser_name, a: int, b: int) -> tuple[str, str]:
    """A weighed in and on lines 1-2, B weighed in after it and waiting in the strip."""
    pertama, kedua = plat(browser_name, a), plat(browser_name, b)
    masuk(halaman, SUPPORT)
    _nyalakan(halaman, konsol, _DUA_LINE)
    _daftar(halaman, pertama, kedua)
    _isi(halaman, pertama)
    expect(halaman.locator("#toasts")).to_contain_text(_ditugaskan(halaman, pertama, _DUA_LINE))
    _isi(halaman, kedua)
    expect(_antre(halaman, kedua)).to_be_visible()
    return pertama, kedua


def test_the_next_truck_waits_until_the_first_is_weighed_out(halaman, konsol, browser_name, penugasan_bersih):
    a, b = _a_di_line_b_antre(halaman, konsol, browser_name, 1102, 1103)
    strip = halaman.locator("#antrean-bongkar")
    expect(strip).to_contain_text(kamus(halaman, "antreanBongkarOtomatis"))
    expect(_antre(halaman, b).locator('button[data-aksi="pasang"]')).to_have_text(kamus(halaman, "btnTugaskanSekarang"))
    lewati = _antre(halaman, b).locator('button[data-aksi="lewati"]')
    expect(lewati).to_have_text(kamus(halaman, "btnLewati"))
    # Red danger button (user 2026-10-03): the truck leaves the queue, behind a confirm.
    expect(lewati).to_have_class(re.compile(r"\bbahaya\b"))
    expect(_antre(halaman, b).locator('button[data-aksi="pasang"]')).not_to_have_class(re.compile(r"\bbahaya\b"))
    for kode in _DUA_LINE:
        expect(_kartu(halaman, kode).locator(".truk")).to_contain_text(a)

    _kosong(halaman, a)
    expect(halaman.locator("#toasts")).to_contain_text(_ditugaskan(halaman, b, _DUA_LINE))
    expect(strip.locator(".antrean-truk")).to_have_count(0)
    for kode in _DUA_LINE:
        expect(_kartu(halaman, kode).locator(".truk")).to_contain_text(b)
    _kosong(halaman, b)


def test_assign_now_is_refused_while_the_lines_still_sort(halaman, konsol, browser_name, penugasan_bersih):
    # Lines 1-2 only: the offline line-3 never holds a truck, so chosen it would count as
    # free and the answer would be one failed line instead of a refusal.
    a, b = _a_di_line_b_antre(halaman, konsol, browser_name, 1104, 1105)
    _antre(halaman, b).locator('button[data-aksi="pasang"]').click()
    expect(halaman.locator("#toasts")).to_contain_text(kamus(halaman, "err_line_semua_terpakai"))
    expect(_antre(halaman, b)).to_be_visible()
    for kode in _DUA_LINE:
        expect(_kartu(halaman, kode).locator(".truk")).to_contain_text(a)
    _kosong(halaman, a)
    _kosong(halaman, b)


def test_skip_asks_first_and_takes_the_truck_out_of_the_queue(halaman, konsol, browser_name, penugasan_bersih):
    a, b = _a_di_line_b_antre(halaman, konsol, browser_name, 1106, 1107)
    lewati = _antre(halaman, b).locator('button[data-aksi="lewati"]')
    bawaan: list[str] = []
    halaman.on("dialog", lambda d: (bawaan.append(d.message), d.dismiss()))
    # The in-page dialog (2026-10-03), never the browser's own box.
    dialog = halaman.locator("#konfirmasi-modal")
    lewati.click()
    expect(dialog).to_be_visible()
    expect(dialog.locator("#konfirmasi-judul")).to_contain_text(b)
    expect(dialog.locator("#konfirmasi-ya")).to_have_text(kamus(halaman, "btnLewati"))
    expect(dialog.locator("#konfirmasi-ya")).to_have_class(re.compile(r"\bbahaya\b.*\bpekat\b"))
    halaman.click("#konfirmasi-tidak")
    expect(dialog).to_be_hidden()
    expect(_antre(halaman, b)).to_be_visible()

    lewati.click()
    halaman.click("#konfirmasi-ya")
    expect(dialog).to_be_hidden()
    expect(halaman.locator("#toasts")).to_contain_text(kamus(halaman, "sukLewati").replace("{truk}", b))
    expect(halaman.locator("#antrean-bongkar .antrean-truk")).to_have_count(0)

    _kosong(halaman, a)
    for kode in _DUA_LINE:
        expect(_kartu(halaman, kode).locator(".truk")).not_to_contain_text(a)
    halaman.evaluate("() => refresh()")
    for kode in _DUA_LINE:
        expect(_kartu(halaman, kode).locator(".truk")).not_to_contain_text(b)
    expect(halaman.locator("#toasts")).not_to_contain_text(_ditugaskan(halaman, b, _DUA_LINE))
    _kosong(halaman, b)
    assert not bawaan, bawaan


def test_lepas_on_the_last_line_puts_the_next_truck_on(halaman, konsol, browser_name, penugasan_bersih):
    a, b = _a_di_line_b_antre(halaman, konsol, browser_name, 1108, 1109)
    toasts = halaman.locator("#toasts")
    buka_menu_line(_kartu(halaman, "line-1"))
    _kartu(halaman, "line-1").locator('[data-aksi="lepas"]').click()
    expect(toasts).to_contain_text(kamus(halaman, "sukLepas").replace("{line}", _nama(halaman, "line-1")))
    expect(_antre(halaman, b)).to_be_visible()
    expect(toasts).not_to_contain_text(_ditugaskan(halaman, b, _DUA_LINE))

    buka_menu_line(_kartu(halaman, "line-2"))
    _kartu(halaman, "line-2").locator('[data-aksi="lepas"]').click()
    expect(toasts).to_contain_text(_ditugaskan(halaman, b, _DUA_LINE))
    expect(halaman.locator("#antrean-bongkar .antrean-truk")).to_have_count(0)
    for kode in _DUA_LINE:
        expect(_kartu(halaman, kode).locator(".truk")).to_contain_text(b)
        expect(_kartu(halaman, kode).locator(".truk")).not_to_contain_text(a)
    _kosong(halaman, a)
    _kosong(halaman, b)
    for kode in _DUA_LINE:
        expect(_kartu(halaman, kode).locator(".truk")).not_to_contain_text(a)


def test_switch_off_hides_the_strip_and_saving_it_on_puts_the_waiting_truck_on(
    halaman, konsol, browser_name, penugasan_bersih
):
    """D13: with the switch off the screen is what it was before this release, so no strip
    (the per-line dropdown is the manual way). Saving the switch on from Setelan puts the
    truck already waiting onto the free chosen lines at once, and says so."""
    b = plat(browser_name, 1110)
    masuk(halaman, SUPPORT)
    _daftar(halaman, b)
    _isi(halaman, b)
    antre = halaman.request.get(konsol.url + "/api/console/state").json()["antrean_bongkar"]
    assert [a["plate_number"] for a in antre] == [b], antre
    halaman.evaluate("() => refresh()")
    expect(halaman.locator("#antrean-bongkar .antrean-truk")).to_have_count(0)
    for kode in _TIGA_LINE:
        expect(_kartu(halaman, kode).locator(".truk")).not_to_contain_text(b)

    buka_setelan(halaman, "penugasan")
    halaman.check("#set-otomatis")
    halaman.uncheck('#set-otomatis-lines input[data-line="line-3"]')
    halaman.click("#set-penugasan-simpan")
    expect(halaman.locator("#toasts .toast.sukses", has_text=kamus(halaman, "penugasanTersimpan"))).to_have_count(1)
    expect(halaman.locator("#toasts")).to_contain_text(_ditugaskan(halaman, b, _DUA_LINE))
    for kode in _DUA_LINE:
        expect(_kartu(halaman, kode).locator(".truk")).to_contain_text(b)
    _kosong(halaman, b)


def test_the_operator_works_the_strip(halaman, konsol, browser_name, penugasan_bersih):
    """The strip's real user is OPERATOR: support turns the switch on, the operator weighs
    in, sees the waiting truck, is refused "Tugaskan sekarang" while the first truck still
    sorts, and takes the truck out with Lewati after the confirm."""
    a, b = plat(browser_name, 1111), plat(browser_name, 1112)
    masuk(halaman, SUPPORT)
    _nyalakan(halaman, konsol, _DUA_LINE)
    _daftar(halaman, a, b)
    keluar(halaman)
    masuk(halaman, OPERATOR)

    toasts = halaman.locator("#toasts")
    _isi(halaman, a)
    expect(toasts).to_contain_text(_ditugaskan(halaman, a, _DUA_LINE))
    _isi(halaman, b)
    strip = halaman.locator("#antrean-bongkar")
    expect(_antre(halaman, b)).to_be_visible()
    expect(strip.locator(".antrean-kepala .lb")).to_have_text(kamus(halaman, "antreanBongkarOtomatis"))
    halaman.click("#bahasa")
    expect(strip.locator(".antrean-kepala .lb")).to_have_text("Unloading queue (automatic)")
    halaman.click("#bahasa")
    expect(strip.locator(".antrean-kepala .lb")).to_have_text(kamus(halaman, "antreanBongkarOtomatis"))

    _antre(halaman, b).locator('button[data-aksi="pasang"]').click()
    expect(toasts).to_contain_text(kamus(halaman, "err_line_semua_terpakai"))
    expect(_antre(halaman, b)).to_be_visible()

    _antre(halaman, b).locator('button[data-aksi="lewati"]').click()
    halaman.click("#konfirmasi-ya")
    expect(toasts).to_contain_text(kamus(halaman, "sukLewati").replace("{truk}", b))
    expect(strip.locator(".antrean-truk")).to_have_count(0)

    _kosong(halaman, a)
    halaman.evaluate("() => refresh()")
    for kode in _DUA_LINE:
        expect(_kartu(halaman, kode).locator(".truk")).not_to_contain_text(a)
        expect(_kartu(halaman, kode).locator(".truk")).not_to_contain_text(b)
    _kosong(halaman, b)


def test_lepas_on_the_truck_card_releases_only_that_truck(halaman, lines, browser_name, penugasan_bersih):
    """Manual mode, two different trucks (spec 2026-10-07 §5.2): the truck card lists both with
    their own lines, and its Lepas releases only the truck it sits beside."""
    a, b = plat(browser_name, 1121), plat(browser_name, 1122)
    masuk(halaman, OPERATOR)
    _daftar(halaman, a, b)
    buka_tab(halaman, "grading")
    for kode, nomor in (("line-1", a), ("line-2", b)):
        kartu = _kartu(halaman, kode)
        buka_menu_line(kartu)
        kartu.locator(".pilih-tombol").click()
        kartu.locator('[role="option"]', has_text=nomor).click()
        kartu.locator('[data-aksi="tugaskan"]').click()
        expect(kartu.locator(".truk")).to_contain_text(nomor)
    grup_a = halaman.locator("#truk-di-line .truk-grup", has_text=a)
    expect(grup_a).to_have_attribute("data-lines", "line-1")
    expect(halaman.locator("#truk-di-line .truk-grup", has_text=b)).to_have_attribute("data-lines", "line-2")

    grup_a.locator('button[data-aksi="lepas-truk"]').click()
    expect(halaman.locator("#toasts")).to_contain_text(
        kamus(halaman, "sukLepasTruk").replace("{truk}", a).replace("{line}", _nama(halaman, "line-1")))
    expect(halaman.locator("#truk-di-line .truk-grup", has_text=a)).to_have_count(0)
    expect(_kartu(halaman, "line-1").locator(".truk")).not_to_contain_text(a)
    expect(_kartu(halaman, "line-2").locator(".truk")).to_contain_text(b)
