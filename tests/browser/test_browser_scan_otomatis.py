"""The one scan field on the real screen (user 2026-10-06): scan only, and the console records
the next step of the visit from the truck's state.

The test console has no scale (`SCALE_PLC_REGISTER` empty), so both weight steps open the
typed box, the fallback the mill uses until the PLC register is known; saving the live
weight is pinned in `tests/unit/test_scan_otomatis_service.py`. Every scan here comes within
3 minutes of the previous step, so steps 1 to 3 ask the double-read question first.

The console lives for the whole session: every test runs inside `scanner_nyala` (switch
back OFF after) and `penugasan_bersih`, and every truck it weighs in is weighed out and leaves.
"""

from __future__ import annotations

import re

import pytest
from langkah import JEDA_HALAMAN_MS, OPERATOR, SUPPORT, buka_tab, kamus, masuk, plat
from playwright.sync_api import expect

pytestmark = pytest.mark.usefixtures("scanner_nyala", "penugasan_bersih")

_SALAH = re.compile(r"\bsalah\b")
_BUKAN_PLAT = "https://promo.example/qr"


def _daftar(halaman, nomor: str) -> None:
    """On the Truk tab, which redraws every plate picker at once."""
    buka_tab(halaman, "truk")
    halaman.fill("#plat", nomor)
    halaman.click("#daftar")
    expect(halaman.locator("#trucks")).to_contain_text(nomor)
    buka_tab(halaman, "timbangan")


def _scan(halaman, teks: str, *, baca_ulang: bool = False) -> None:
    """What the scanner does: type into the focused field, then Enter. The screen drops the
    same QR read again within 2 s; a test scans faster than a person, so it forgets the last
    read unless the test is about that drop."""
    kolom = halaman.locator("#scan-otomatis")
    expect(kolom).to_be_focused()
    if not baca_ulang:
        halaman.evaluate("() => { scanTerakhir = { qr: '', pada: 0 }; }")
    halaman.keyboard.type(teks)
    halaman.keyboard.press("Enter")


def _jawab(halaman, ya: bool) -> None:
    dialog = halaman.locator("#konfirmasi-modal")
    expect(dialog).to_be_visible()
    halaman.click("#konfirmasi-ya" if ya else "#konfirmasi-tidak")
    expect(dialog).to_be_hidden()


def _popup(halaman, nomor: str, langkah: str = "") -> None:
    """The result popup (2026-10-07) shows the plate, and the step when `langkah` is given."""
    popup = halaman.locator("#scan-popup")
    expect(popup).to_be_visible()
    expect(popup).to_contain_text(nomor)
    if langkah:
        expect(popup).to_contain_text(kamus(halaman, langkah), ignore_case=True)


def _ketik_berat(halaman, kg: str) -> None:
    """The weight popup asks for the number: its box has the focus, typing and Enter save."""
    popup = halaman.locator("#scan-popup")
    expect(popup).to_have_attribute("data-jenis", "berat")
    expect(halaman.locator("#scan-popup-berat")).to_be_focused()
    halaman.keyboard.type(kg)
    halaman.keyboard.press("Enter")
    expect(popup).to_have_attribute("data-jenis", "sukses")


def _tiket(halaman, konsol, nomor: str) -> list[dict]:
    items = halaman.request.get(konsol.url + "/api/console/weighings").json()["items"]
    return [w for w in items if w["plate_number"] == nomor]


def test_four_scans_make_one_visit(halaman, konsol, browser_name):
    nomor = plat(browser_name, 1401)
    masuk(halaman, OPERATOR)
    _daftar(halaman, nomor)
    pesan = halaman.locator("#scan-otomatis-pesan")

    _scan(halaman, nomor.lower())
    _popup(halaman, nomor, "scanLangkahDatang")

    _scan(halaman, nomor)
    _jawab(halaman, ya=True)
    # No scale: a popup asks for the weight, the Timbangan boxes stay untouched.
    _popup(halaman, nomor, "scanLangkahIsi")
    expect(halaman.locator("#bruto")).not_to_be_focused()
    _ketik_berat(halaman, "14000")
    expect(halaman.locator("#scan-popup")).to_contain_text("14.000 kg")
    expect(halaman.locator("#scan-otomatis")).to_be_focused()
    expect(pesan).to_have_text("")

    _scan(halaman, nomor)
    _jawab(halaman, ya=True)
    _popup(halaman, nomor, "scanLangkahKosong")
    expect(halaman.locator("#tara-nilai")).not_to_be_focused()
    _ketik_berat(halaman, "6000")
    expect(halaman.locator("#scan-otomatis")).to_be_focused()

    # Keluar never asks: an early leave time is harmless.
    _scan(halaman, nomor)
    _popup(halaman, nomor, "scanLangkahKeluar")
    expect(halaman.locator("#konfirmasi-modal")).to_be_hidden()
    [tiket] = _tiket(halaman, konsol, nomor)
    assert (tiket["gross_kg"], tiket["tare_kg"], tiket["net_kg"]) == (14000, 6000, 8000), tiket
    assert tiket["left_at"] and tiket["arrived_at"], tiket


def test_a_double_read_is_dropped_or_asked_and_writes_nothing(halaman, konsol, browser_name):
    nomor = plat(browser_name, 1402)
    masuk(halaman, OPERATOR)
    _daftar(halaman, nomor)
    _scan(halaman, nomor)
    _popup(halaman, nomor)

    # The same QR again at once: dropped by the screen, nothing asked, nothing sent.
    _scan(halaman, nomor, baca_ulang=True)
    halaman.wait_for_timeout(JEDA_HALAMAN_MS)
    expect(halaman.locator("#konfirmasi-modal")).to_be_hidden()

    # Later than 2 s but within 3 min: the server asks; Batal records nothing.
    _scan(halaman, nomor)
    _jawab(halaman, ya=False)
    expect(halaman.locator("#bruto")).not_to_be_focused()
    assert _tiket(halaman, konsol, nomor) == []
    waiting = halaman.request.get(konsol.url + "/api/console/weighings").json()["waiting"]
    datang = [w for w in waiting if w["plate_number"] == nomor]
    assert len(datang) == 1, datang
    halaman.request.post(konsol.url + f"/api/console/arrivals/{datang[0]['id']}/cancel")


def test_not_a_plate_is_refused_and_the_field_is_cleared(halaman):
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")
    _scan(halaman, _BUKAN_PLAT)
    pesan = halaman.locator("#scan-otomatis-pesan")
    expect(pesan).to_have_text(kamus(halaman, "err_bukan_plat"))
    expect(pesan).to_have_class(_SALAH)
    expect(halaman.locator("#scan-otomatis")).to_have_value("")


def test_an_unregistered_truck_may_arrive_but_is_not_weighed(halaman, konsol, browser_name):
    nomor = plat(browser_name, 1403)
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")
    _scan(halaman, nomor)
    _popup(halaman, nomor)
    _scan(halaman, nomor)
    _jawab(halaman, ya=True)
    pesan = halaman.locator("#scan-otomatis-pesan")
    expect(halaman.locator("#scan-popup")).to_have_attribute("data-jenis", "gagal")
    expect(pesan).to_contain_text(kamus(halaman, "scanBelumAda"))
    expect(pesan).to_have_class(_SALAH)
    assert _tiket(halaman, konsol, nomor) == []
    waiting = halaman.request.get(konsol.url + "/api/console/weighings").json()["waiting"]
    for w in waiting:
        if w["plate_number"] == nomor:
            halaman.request.post(konsol.url + f"/api/console/arrivals/{w['id']}/cancel")


def test_the_field_keeps_the_focus_but_never_takes_it_from_a_typed_box(halaman, browser_name):
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")
    kolom = halaman.locator("#scan-otomatis")
    expect(kolom).to_be_focused()
    # A click on empty page space gives it back.
    halaman.click("#sec-timbangan .tabel")
    expect(kolom).to_be_focused()
    # The bruto box keeps the focus across polls while the operator types.
    halaman.click("#bruto")
    halaman.keyboard.type("12")
    halaman.wait_for_timeout(2_500)
    expect(halaman.locator("#bruto")).to_be_focused()
    halaman.fill("#bruto", "")
    # Another tab: the hidden field takes nothing.
    buka_tab(halaman, "truk")
    expect(kolom).not_to_be_focused()
    buka_tab(halaman, "timbangan")
    expect(kolom).to_be_focused()


def test_a_card_picker_follows_an_automatic_assignment(halaman, konsol, lines, browser_name):
    nomor = plat(browser_name, 1404)
    masuk(halaman, SUPPORT)  # the auto-assign switch is support's
    _daftar(halaman, nomor)
    r = halaman.request.post(konsol.url + "/api/console/dev/auto-assign",
                             data={"aktif": True, "lines": ["line-1"]})
    assert r.status == 200, r.text()
    truk = next(t for t in halaman.request.get(konsol.url + "/api/console/trucks").json()["items"]
                if t["plate_number"] == nomor)
    pilih = halaman.locator('#lines .card[data-line="line-1"] .assign .pilih')

    _scan(halaman, nomor)
    _popup(halaman, nomor)
    _scan(halaman, nomor)
    _jawab(halaman, ya=True)
    _ketik_berat(halaman, "14000")
    # Put on line-1 by the weigh-in, not by a pick on the card: the card's picker follows.
    expect(pilih).to_have_attribute("data-nilai", truk["id"], timeout=10_000)

    _scan(halaman, nomor)
    _jawab(halaman, ya=True)
    _ketik_berat(halaman, "6000")
    _scan(halaman, nomor)
    _popup(halaman, nomor, "scanLangkahKeluar")


def _buka_pertanyaan(halaman, nomor: str) -> None:
    """Datang, then a second scan of the same truck: the "Catat?" question opens."""
    _scan(halaman, nomor)
    _popup(halaman, nomor)
    _scan(halaman, nomor)
    expect(halaman.locator("#konfirmasi-modal")).to_be_visible()


def _scan_di_dialog(halaman, teks: str) -> None:
    """The scanner types into whatever has the focus: the dialog's Batal button."""
    halaman.keyboard.type(teks)
    halaman.keyboard.press("Enter")


def _batal_kedatangan(halaman, konsol, nomor: str) -> None:
    for w in halaman.request.get(konsol.url + "/api/console/weighings").json()["waiting"]:
        if w["plate_number"] == nomor:
            halaman.request.post(konsol.url + f"/api/console/arrivals/{w['id']}/cancel")


def test_scanning_the_same_qr_again_answers_catat(halaman, konsol, browser_name):
    nomor = plat(browser_name, 1405)
    masuk(halaman, OPERATOR)
    _daftar(halaman, nomor)
    _buka_pertanyaan(halaman, nomor)
    # The operator reads the question and scans again later than 2 s (the clock is moved, not slept).
    halaman.evaluate("() => { scanUlang.dibuka -= 3000; }")
    _scan_di_dialog(halaman, nomor.lower())
    expect(halaman.locator("#konfirmasi-modal")).to_be_hidden()
    _popup(halaman, nomor, "scanLangkahIsi")
    expect(halaman.locator("#scan-popup-berat")).to_be_focused()
    halaman.keyboard.press("Escape")
    expect(halaman.locator("#scan-popup")).to_be_hidden()
    _batal_kedatangan(halaman, konsol, nomor)


def test_a_double_read_inside_2_s_does_not_answer(halaman, konsol, browser_name):
    nomor = plat(browser_name, 1406)
    masuk(halaman, OPERATOR)
    _daftar(halaman, nomor)
    _buka_pertanyaan(halaman, nomor)
    # The same QR read again at once: neither Catat nor Batal, the question stays.
    _scan_di_dialog(halaman, nomor)
    halaman.wait_for_timeout(JEDA_HALAMAN_MS)
    expect(halaman.locator("#konfirmasi-modal")).to_be_visible()
    expect(halaman.locator("#bruto")).not_to_be_focused()
    halaman.keyboard.press("Escape")
    expect(halaman.locator("#konfirmasi-modal")).to_be_hidden()
    assert _tiket(halaman, konsol, nomor) == []
    _batal_kedatangan(halaman, konsol, nomor)


def test_another_truck_scanned_at_the_question_answers_batal(halaman, konsol, browser_name):
    nomor = plat(browser_name, 1407)
    masuk(halaman, OPERATOR)
    _daftar(halaman, nomor)
    _buka_pertanyaan(halaman, nomor)
    halaman.evaluate("() => { scanUlang.dibuka -= 3000; }")
    _scan_di_dialog(halaman, plat(browser_name, 1408))
    expect(halaman.locator("#konfirmasi-modal")).to_be_hidden()
    expect(halaman.locator("#scan-otomatis")).to_be_focused()
    assert _tiket(halaman, konsol, nomor) == []
    _batal_kedatangan(halaman, konsol, nomor)


# --- Scan from any tab (2026-10-07) -------------------------------------------------------

_PLAT_BERSPASI = "B 1995 SME"


def _tugaskan_line_1(halaman, nomor: str) -> None:
    """A truck on line-1, so its Reject button is enabled (Space+1 reaches it)."""
    _daftar(halaman, nomor)
    buka_tab(halaman, "grading")
    kartu = halaman.locator('#lines .card[data-line="line-1"]')
    kartu.locator(".pilih-tombol").click()
    kartu.locator('[role="option"]', has_text=nomor).click()
    kartu.locator('[data-aksi="tugaskan"]').click()
    expect(kartu.locator(".truk")).to_contain_text(nomor)


def test_scan_dari_tab_grading_mencatat_tanpa_pindah_tab(halaman, konsol):
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "grading")
    try:
        halaman.keyboard.type(_PLAT_BERSPASI, delay=10)  # scanner speed
        halaman.keyboard.press("Enter")
        expect(halaman.locator('#tabs [data-tab="grading"]')).to_have_attribute("aria-selected", "true")
        _popup(halaman, "B1995SME", "scanLangkahDatang")
        # It goes by itself, no click.
        expect(halaman.locator("#scan-popup")).to_be_hidden(timeout=5_000)
    finally:
        _batal_kedatangan(halaman, konsol, "B1995SME")


def test_scan_plat_berspasi_tidak_memicu_reject(halaman, konsol, browser_name):
    nomor = plat(browser_name, 1410)
    masuk(halaman, OPERATOR)
    _tugaskan_line_1(halaman, nomor)
    tombol = halaman.locator('#lines .card[data-line="line-1"] button.reject')
    expect(tombol).to_be_enabled()
    try:
        halaman.keyboard.type(_PLAT_BERSPASI, delay=10)
        halaman.keyboard.press("Enter")
        _popup(halaman, "B1995SME", "scanLangkahDatang")
        expect(tombol).not_to_have_class(re.compile(r"\bkedip\b"))
    finally:
        _batal_kedatangan(halaman, konsol, "B1995SME")


def test_spasi_ditahan_lalu_1_tetap_reject(halaman, browser_name):
    nomor = plat(browser_name, 1411)
    masuk(halaman, OPERATOR)
    _tugaskan_line_1(halaman, nomor)
    tombol = halaman.locator('#lines .card[data-line="line-1"] button.reject')
    # The fake line has no reject endpoint (502 would fail the page-error guard); the flash is the proof.
    halaman.route("**/manual-reject", lambda r: r.fulfill(status=200, content_type="application/json", body="{}"))
    halaman.keyboard.down("Space")
    halaman.wait_for_timeout(300)  # a person's slow Space then 1; auto-repeat is pinned in the node test
    halaman.keyboard.press("1")
    halaman.keyboard.up("Space")
    expect(tombol).to_have_class(re.compile(r"\bkedip\b"))


# --- Scan result popup (2026-10-07) -------------------------------------------------------


def _sampai_popup_berat(halaman, nomor: str) -> None:
    """Datang, then the second scan and Catat: the weight popup opens (no scale on this console)."""
    _scan(halaman, nomor)
    _popup(halaman, nomor)
    _scan(halaman, nomor)
    _jawab(halaman, ya=True)
    expect(halaman.locator("#scan-popup")).to_have_attribute("data-jenis", "berat")
    expect(halaman.locator("#scan-popup-berat")).to_be_focused()


def _selesaikan(halaman, nomor: str) -> None:
    """Weigh the truck out and let it leave, so the shared console is left clean."""
    _scan(halaman, nomor)
    _jawab(halaman, ya=True)
    _ketik_berat(halaman, "6000")
    _scan(halaman, nomor)
    _popup(halaman, nomor, "scanLangkahKeluar")


def _baris_timbangan(halaman, nomor: str):
    return halaman.locator("#sec-timbangan tr", has_text=nomor).first


def test_typed_weight_in_the_popup_saves_and_the_popup_closes_itself(halaman, konsol, browser_name):
    nomor = plat(browser_name, 1701)
    masuk(halaman, OPERATOR)
    _daftar(halaman, nomor)
    _sampai_popup_berat(halaman, nomor)
    expect(halaman.locator("#scan-popup-petunjuk")).to_have_text(kamus(halaman, "scanKetikBeratPopup"))
    halaman.keyboard.type("30000")
    halaman.keyboard.press("Enter")
    popup = halaman.locator("#scan-popup")
    expect(popup).to_have_attribute("data-jenis", "sukses")
    expect(popup).to_contain_text("30.000 kg")
    expect(_baris_timbangan(halaman, nomor)).to_contain_text("30.000")
    expect(popup).to_be_hidden(timeout=6_000)
    expect(halaman.locator("#scan-otomatis")).to_be_focused()
    _selesaikan(halaman, nomor)


def test_scanning_the_same_qr_in_the_popup_saves_the_typed_weight(halaman, konsol, browser_name):
    nomor = plat(browser_name, 1702)
    masuk(halaman, OPERATOR)
    _daftar(halaman, nomor)
    _sampai_popup_berat(halaman, nomor)
    halaman.keyboard.type("30000", delay=150)  # a person's pace, not a scanner burst
    halaman.wait_for_timeout(600)  # a person scans after typing, never inside the same burst
    halaman.keyboard.type(nomor.lower())  # the plate holds digits: they must not become weight
    halaman.keyboard.press("Enter")
    popup = halaman.locator("#scan-popup")
    expect(popup).to_have_attribute("data-jenis", "sukses")
    expect(popup).to_contain_text("30.000 kg")
    expect(_baris_timbangan(halaman, nomor)).to_contain_text("30.000")
    _selesaikan(halaman, nomor)


def _pesan_berat_tersimpan(halaman, konsol, nomor: str) -> list[dict]:
    """Tickets of `nomor` that carry a gross weight: what a popup save would have written."""
    return [w for w in _tiket(halaman, konsol, nomor) if w.get("gross_kg")]


def test_popup_weight_below_the_minimum_is_refused_and_esc_closes_it(halaman, konsol, browser_name):
    nomor = plat(browser_name, 1703)
    masuk(halaman, OPERATOR)
    _daftar(halaman, nomor)
    try:
        _sampai_popup_berat(halaman, nomor)
        halaman.keyboard.type("500")
        halaman.keyboard.press("Enter")
        expect(halaman.locator("#scan-popup-galat")).to_have_text(kamus(halaman, "scanBeratMinimum"))
        expect(halaman.locator("#scan-popup")).to_have_attribute("data-jenis", "berat")
        assert _pesan_berat_tersimpan(halaman, konsol, nomor) == []
        halaman.keyboard.press("Escape")
        expect(halaman.locator("#scan-popup")).to_be_hidden()
        expect(halaman.locator("#scan-otomatis")).to_be_focused()
    finally:
        _batal_kedatangan(halaman, konsol, nomor)


def test_another_qr_scanned_into_the_popup_closes_it_and_is_sent(halaman, konsol, browser_name):
    nomor, lain = plat(browser_name, 1704), plat(browser_name, 1705)
    masuk(halaman, OPERATOR)
    _daftar(halaman, nomor)
    try:
        _sampai_popup_berat(halaman, nomor)
        halaman.keyboard.type(lain)
        halaman.keyboard.press("Enter")
        _popup(halaman, lain, "scanLangkahDatang")
        expect(halaman.locator("#scan-popup")).to_have_attribute("data-jenis", "sukses")
        assert _pesan_berat_tersimpan(halaman, konsol, nomor) == []
    finally:
        _batal_kedatangan(halaman, konsol, nomor)
        _batal_kedatangan(halaman, konsol, lain)


def test_a_failed_read_shows_a_red_popup(halaman):
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "grading")
    halaman.keyboard.type("B 19", delay=10)
    halaman.wait_for_timeout(140)  # a gap inside a plate: the read failed
    halaman.keyboard.type("95 SME", delay=10)
    halaman.keyboard.press("Enter")
    popup = halaman.locator("#scan-popup")
    expect(popup).to_have_attribute("data-jenis", "gagal")
    expect(popup).to_contain_text(kamus(halaman, "scanTakTerbaca"))


def test_a_scan_that_stalls_never_becomes_a_weight(halaman, konsol, browser_name):
    nomor = plat(browser_name, 1706)
    masuk(halaman, OPERATOR)
    _daftar(halaman, nomor)
    try:
        _sampai_popup_berat(halaman, nomor)
        halaman.keyboard.type("BE 12", delay=10)
        halaman.wait_for_timeout(600)
        halaman.keyboard.type("34", delay=10)
        halaman.keyboard.press("Enter")
        expect(halaman.locator("#scan-popup-galat")).to_have_text(kamus(halaman, "scanTakTerbaca"))
        expect(halaman.locator("#scan-popup-berat")).to_have_value("")
        halaman.keyboard.press("Enter")
        expect(halaman.locator("#scan-popup-galat")).to_have_text(kamus(halaman, "scanBeratKosong"))
        assert _pesan_berat_tersimpan(halaman, konsol, nomor) == []
    finally:
        _batal_kedatangan(halaman, konsol, nomor)
