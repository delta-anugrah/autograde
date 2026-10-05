"""Working day cutoff on the screen (batch 5.11)."""
from __future__ import annotations

import re

import pytest
from konsol_js import HTML, NODE, fungsi, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")
KUNCI = ("grupHariKerja", "labelCutoff", "bantuCutoff", "btnSimpanCutoff", "cutoffTersimpan", "rekapCutoff",
         "err_cutoff_tidak_sah")


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
    assert jalankan(["teksCutoffRekap"], 'teksCutoffRekap("05:00")', bahasa=bahasa) == pola.replace("{jam}", "05:00")
    for kosong in ('"00:00"', '""', "null", "undefined"):
        assert jalankan(["teksCutoffRekap"], f"teksCutoffRekap({kosong})", bahasa=bahasa) == ""


def test_the_poll_reads_the_cutoff_and_settings_save_it():
    assert "aturCutoffShift(s.cutoff_shift)" in fungsi("refresh")
    assert "await muatCutoffSetelan();" in fungsi("muatSetelan")
    awal = HTML.index('$("set-cutoff-simpan").addEventListener("click"')
    kerja = HTML[awal : HTML.index("\n}));", awal)]
    assert "denganSibuk(ev.currentTarget" in kerja and '"/api/console/dev/shift"' in kerja
    assert 'gagalKarena("gagalSetelan", e)' in kerja and 'toastSukses(t("cutoffTersimpan"))' in kerja
    assert '<input id="set-cutoff" type="time"' in HTML
    assert re.search(r'<span id="riwayat-cutoff" class="muted"( hidden)?></span>', HTML)
