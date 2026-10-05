"""Working day cutoff on the screen (batch 5.11)."""
from __future__ import annotations

import re

import pytest
from konsol_js import HTML, NODE, fungsi, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")
KUNCI = ("grupHariKerja", "labelCutoff", "bantuCutoff", "btnSimpanCutoff", "cutoffTersimpan", "rekapCutoff",
         "err_cutoff_tidak_sah", "konfirmasiCutoffJudul", "konfirmasiCutoffPesan")


def _simpan() -> str:
    """The Simpan hari kerja click handler, up to its closing line."""
    awal = HTML.index('$("set-cutoff-simpan").addEventListener("click"')
    return HTML[awal : HTML.index("\n});", awal)]


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_every_word_is_in_both_languages(bahasa):
    for kunci in KUNCI:
        assert f"{kunci}:" in _kamus(bahasa), kunci


@butuh_node
@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_the_rekap_names_the_cutoff_only_when_it_is_not_midnight(bahasa):
    pola = jalankan([], "KAMUS[bahasa].rekapCutoff", bahasa=bahasa)
    # With the factory zone (user 2026-10-06): "(dipotong jam 05:00 Asia/Jakarta)".
    hasil = jalankan(["teksCutoffRekap"], 'teksCutoffRekap("05:00", "Asia/Jakarta")', bahasa=bahasa)
    assert hasil == pola.replace("{jam}", "05:00").replace("{zona}", "Asia/Jakarta") and "Asia/Jakarta" in hasil
    for kosong in ('"00:00"', '""', "null", "undefined"):
        assert jalankan(["teksCutoffRekap"], f"teksCutoffRekap({kosong})", bahasa=bahasa) == ""


def test_the_poll_reads_the_cutoff_and_settings_save_it():
    assert "aturCutoffShift(s.cutoff_shift)" in fungsi("refresh")
    assert "await muatCutoffSetelan();" in fungsi("muatSetelan")
    kerja = _simpan()
    assert "denganSibuk(tombol" in kerja and '"/api/console/dev/shift"' in kerja
    assert 'gagalKarena("gagalSetelan", e)' in kerja and 'toastSukses(t("cutoffTersimpan"))' in kerja
    assert '<input id="set-cutoff" type="time"' in HTML
    assert re.search(r'<span id="riwayat-cutoff" class="muted"( hidden)?></span>', HTML)


def test_save_stays_off_until_the_stored_cutoff_is_loaded():
    """Review 5.11: a failed load left the field empty, and Save then stored 00:00 over 05:00."""
    muat = fungsi("muatCutoffSetelan")
    assert muat.index('$("set-cutoff-simpan").disabled = true') < muat.index('api("/api/console/dev/shift")')
    assert '$("set-cutoff-simpan").disabled = false' in muat.split("catch")[0]
    assert '<button id="set-cutoff-simpan" class="utama" data-t="btnSimpanCutoff" disabled>' in HTML


@butuh_node
@pytest.mark.parametrize(("teks", "tanya"), [("13:00", True), ("23:59", True), ("12:00", False), ("05:00", False),
                                             ("00:00", False), ("", False)])
def test_a_cutoff_after_noon_asks_first(teks, tanya):
    """User 2026-10-05: any hour is allowed, but after 12:00 the screen warns and asks first."""
    assert jalankan(["cutoffPerluTanya"], f"cutoffPerluTanya({teks!r})") is tanya


def test_the_save_asks_with_the_example_and_the_field_shows_the_zone():
    kerja = _simpan()
    tanya = kerja.index("cutoffPerluTanya(")
    assert tanya < kerja.index("tanyaKonfirmasi(") < kerja.index('"/api/console/dev/shift"')
    assert 't("konfirmasiCutoffPesan")' in kerja and 't("konfirmasiCutoffJudul")' in kerja
    assert '<input id="set-cutoff" type="time" step="60">' in HTML, "no max: any hour is allowed"
    assert '<span id="set-cutoff-zona" class="muted"></span>' in HTML
    # The Settings tab is taken out of the page for an operator (`data-dev`), so the 2 s poll
    # only keeps the zone name; the support-only load writes it (an operator's poll broke on it).
    assert "set-cutoff-zona" not in fungsi("refresh") and "zonaPabrik = s.timezone" in fungsi("refresh")
    assert '$("set-cutoff-zona").textContent' in fungsi("muatCutoffSetelan")


def test_the_confirm_text_is_short_paragraphs_not_one_block():
    """User 2026-10-05: the warning read as one wall of text; one point per paragraph."""
    for bahasa in ("id", "en"):
        pesan = re.search(r'konfirmasiCutoffPesan:"([^"]*)"', _kamus(bahasa)).group(1)
        assert pesan.count("\\n\\n") == 2, bahasa
    assert re.search(r"#konfirmasi-pesan\s*\{[^}]*white-space:\s*pre-line", HTML)


@butuh_node
@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_the_recap_title_names_one_working_day_once(bahasa):
    """User 2026-10-05: "Mon, 5 Oct 2026 to Mon, 5 Oct 2026" repeated itself and did not say
    what the dates are. One day is written once, and both say they are working days."""
    satu = jalankan(["judulRentangRiwayat"], 'judulRentangRiwayat("Sen", "Sen")', bahasa=bahasa)
    dua = jalankan(["judulRentangRiwayat"], 'judulRentangRiwayat("Sen", "Jum")', bahasa=bahasa)
    assert satu.count("Sen") == 1 and satu == jalankan([], "KAMUS[bahasa].riwayatSatuHari", bahasa=bahasa).replace(
        "{tanggal}", "Sen")
    assert dua == jalankan([], "KAMUS[bahasa].riwayatJudulRentang", bahasa=bahasa).replace(
        "{dari}", "Sen").replace("{sampai}", "Jum")
