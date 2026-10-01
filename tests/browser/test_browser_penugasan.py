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

from langkah import OPERATOR, SUPPORT, buka_tab, kamus, masuk, plat
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


def test_the_switch_is_off_by_default_and_keeps_what_support_saved(halaman, konsol, penugasan_bersih):
    masuk(halaman, SUPPORT)
    buka_tab(halaman, "setelan")
    expect(halaman.locator("#set-otomatis")).not_to_be_checked()
    pilihan = halaman.locator("#set-otomatis-lines input[data-line]")
    expect(pilihan).to_have_count(3)
    for i in range(3):
        expect(pilihan.nth(i)).to_be_checked()

    halaman.check("#set-otomatis")
    halaman.uncheck('#set-otomatis-lines input[data-line="line-3"]')
    halaman.click("#set-penugasan-simpan")
    expect(halaman.locator("#set-penugasan-pesan")).to_have_text(kamus(halaman, "penugasanTersimpan"))

    halaman.reload()
    expect(halaman.locator("#keluar")).to_be_visible()
    buka_tab(halaman, "setelan")
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
    expect(_antre(halaman, b).locator('button[data-aksi="lewati"]')).to_have_text(kamus(halaman, "btnLewati"))
    for kode in _DUA_LINE:
        expect(_kartu(halaman, kode).locator(".truk")).to_contain_text(a)

    _kosong(halaman, a)
    expect(halaman.locator("#toasts")).to_contain_text(_ditugaskan(halaman, b, _DUA_LINE))
    expect(strip).to_be_hidden()
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
    pesan: list[str] = []
    halaman.once("dialog", lambda d: (pesan.append(d.message), d.dismiss()))
    lewati.click()
    expect(_antre(halaman, b)).to_be_visible()
    assert pesan and b in pesan[0], pesan

    halaman.once("dialog", lambda d: d.accept())
    lewati.click()
    expect(halaman.locator("#toasts")).to_contain_text(kamus(halaman, "sukLewati").replace("{truk}", b))
    expect(halaman.locator("#antrean-bongkar")).to_be_hidden()

    _kosong(halaman, a)
    for kode in _DUA_LINE:
        expect(_kartu(halaman, kode).locator(".truk")).not_to_contain_text(a)
    halaman.evaluate("() => refresh()")
    for kode in _DUA_LINE:
        expect(_kartu(halaman, kode).locator(".truk")).not_to_contain_text(b)
    expect(halaman.locator("#toasts")).not_to_contain_text(_ditugaskan(halaman, b, _DUA_LINE))
    _kosong(halaman, b)


def test_lepas_on_the_last_line_puts_the_next_truck_on(halaman, konsol, browser_name, penugasan_bersih):
    a, b = _a_di_line_b_antre(halaman, konsol, browser_name, 1108, 1109)
    toasts = halaman.locator("#toasts")
    _kartu(halaman, "line-1").locator('[data-aksi="lepas"]').click()
    expect(toasts).to_contain_text(kamus(halaman, "sukLepas").replace("{line}", _nama(halaman, "line-1")))
    expect(_antre(halaman, b)).to_be_visible()
    expect(toasts).not_to_contain_text(_ditugaskan(halaman, b, _DUA_LINE))

    _kartu(halaman, "line-2").locator('[data-aksi="lepas"]').click()
    expect(toasts).to_contain_text(_ditugaskan(halaman, b, _DUA_LINE))
    expect(halaman.locator("#antrean-bongkar")).to_be_hidden()
    for kode in _DUA_LINE:
        expect(_kartu(halaman, kode).locator(".truk")).to_contain_text(b)
        expect(_kartu(halaman, kode).locator(".truk")).not_to_contain_text(a)
    _kosong(halaman, a)
    _kosong(halaman, b)
    for kode in _DUA_LINE:
        expect(_kartu(halaman, kode).locator(".truk")).not_to_contain_text(a)


def test_switch_off_strip_reads_manual_and_assign_now_still_works(halaman, browser_name, penugasan_bersih):
    b = plat(browser_name, 1110)
    masuk(halaman, SUPPORT)
    _daftar(halaman, b)
    _isi(halaman, b)
    strip = halaman.locator("#antrean-bongkar")
    expect(strip.locator(".lb")).to_have_text(kamus(halaman, "antreanBongkarManual"))
    for kode in _TIGA_LINE:
        expect(_kartu(halaman, kode).locator(".truk")).not_to_contain_text(b)

    halaman.click("#bahasa")
    expect(strip.locator(".lb")).to_have_text("Unloading queue")
    halaman.click("#bahasa")
    expect(strip.locator(".lb")).to_have_text(kamus(halaman, "antreanBongkarManual"))

    _antre(halaman, b).locator('button[data-aksi="pasang"]').click()
    toasts = halaman.locator("#toasts")
    expect(toasts).to_contain_text(_ditugaskan(halaman, b, _DUA_LINE))
    expect(toasts).to_contain_text(
        kamus(halaman, "tugaskanGagalLine").replace("{line}", _nama(halaman, "line-3")).replace("{truk}", b)
    )
    expect(strip).to_be_hidden()
    for kode in _DUA_LINE:
        expect(_kartu(halaman, kode).locator(".truk")).to_contain_text(b)
    _kosong(halaman, b)
