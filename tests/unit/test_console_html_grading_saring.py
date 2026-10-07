"""Grading tab: a line and truck filter, and tables that load the small photo (batch 5.10,
5.12).

The server already filtered `/api/console/history` by `line_code` and `truck_id`; the
screen had no way to ask. Every table loaded the 5 MP photo for a 52 px picture.

Two layers like `test_console_html_lepas_paksa.py`: text invariants (always run) and
behaviour through node with the real KAMUS (`konsol_js`).
"""
from __future__ import annotations

import json
import re

import pytest
from konsol_js import HTML, NODE, fungsi, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")

KUNCI = ("saringLine", "saringTruk", "saringSemuaLine", "saringSemuaTruk", "kosongGradingSaring")


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_every_word_is_in_both_languages(bahasa):
    isi = _kamus(bahasa)
    for kunci in KUNCI:
        assert f"{kunci}:" in isi, f"KAMUS.{bahasa} misses {kunci}"


# ── the filter ────────────────────────────────────────────────────────────


@butuh_node
@pytest.mark.parametrize(
    ("saring", "harapan"),
    [
        ({"line": "", "truk": ""}, "limit=25&offset=50"),
        ({"line": "line-2", "truk": ""}, "limit=25&offset=50&line_code=line-2"),
        ({"line": "", "truk": "t 1"}, "limit=25&offset=50&truck_id=t+1"),
        ({"line": "line-1", "truk": "t1"}, "limit=25&offset=50&line_code=line-1&truck_id=t1"),
    ],
)
def test_the_history_request_carries_only_the_filters_that_are_set(saring, harapan):
    hasil = jalankan(["paramGrading"], f"paramGrading(25, 50, {json.dumps(saring)})")
    assert hasil == harapan


def test_the_table_asks_with_the_filter_and_says_when_it_matches_nothing():
    muat = fungsi("muatGrading")
    assert "paramGrading(per, gradingOffset, gradingSaring)" in muat
    assert "adaSaringan()" in muat and '"kosongGradingSaring"' in muat


@butuh_node
@pytest.mark.parametrize(
    ("saring", "ada"), [({"line": "", "truk": ""}, False), ({"line": "line-1", "truk": ""}, True), ({"line": "", "truk": "t1"}, True)]
)
def test_a_filter_counts_as_set_when_either_picker_has_a_value(saring, ada):
    assert jalankan(["adaSaringan"], "adaSaringan()", tambahan=f"const gradingSaring = {json.dumps(saring)};") is ada


def test_both_pickers_are_the_dropdown_component_with_search():
    for id_ in ("grading-line", "grading-truk"):
        assert re.search(rf'<div class="pilih" id="{id_}" data-nilai="">\s*<button type="button" class="pilih-tombol"', HTML), id_


def test_a_new_pick_goes_back_to_page_one():
    kerja = fungsi("gantiSaringGrading")
    assert kerja.index("gradingOffset = 0") < kerja.index("muatGrading()")
    for id_ in ("grading-line", "grading-truk"):
        assert f'$("{id_}").addEventListener("pilih", gantiSaringGrading);' in HTML


@butuh_node
def test_the_line_list_follows_the_cards_and_the_truck_list_the_trucks():
    opsi = jalankan(
        ["opsiSaringLine"], "opsiSaringLine()",
        tambahan='const urutan = ["line-2", "line-1"]; const namaLineKartu = {"line-1": "Line 1", "line-2": "Line 2"};',
    )
    assert [o["v"] for o in opsi] == ["", "line-1", "line-2"]
    assert [o["teks"] for o in opsi][1:] == ["Line 1", "Line 2"]
    truk = jalankan(
        ["opsiSaringTruk"], "opsiSaringTruk()",
        tambahan='const trucks = [{id:"t1", plate_number:"BE 1 AA"}, {id:"t2", plate_number:"BE 2 BB"}];',
    )
    assert [o["v"] for o in truk] == ["", "t1", "t2"]
    assert "isiUlangPilih(" in fungsi("segarkanSaringGrading")
    assert "segarkanSaringGrading()" in fungsi("isiTrucks") and "segarkanSaringGrading()" in fungsi("refresh")


# ── the small photo ───────────────────────────────────────────────────────

_FOTO = ["selFoto"]


@butuh_node
def test_a_table_shows_the_small_photo_and_opens_the_full_one():
    html = jalankan(_FOTO, 'selFoto({image_url: "/c/bbox/a.webp", thumb_url: "/c/thumb/a.webp"}, "Judul")')
    assert 'data-foto="/c/bbox/a.webp"' in html
    assert '<img src="/c/thumb/a.webp"' in html and 'data-penuh="/c/bbox/a.webp"' in html
    assert 'src="/c/bbox/a.webp"' not in html


@butuh_node
def test_a_photo_with_no_small_copy_shows_the_full_one():
    html = jalankan(_FOTO, 'selFoto({image_url: "/c/lama.webp", thumb_url: null}, "J")')
    assert '<img src="/c/lama.webp"' in html and "data-penuh" not in html


@butuh_node
def test_no_photo_is_a_dash():
    assert jalankan(_FOTO, 'selFoto({image_url: null, thumb_url: null}, "J")') == "-"


def test_both_photo_tables_use_the_one_cell():
    for nama in ("barisRecent", "barisRiwayatJanjang"):
        baris = fungsi(nama)
        assert "selFoto(r," in baris, nama
        assert "<img" not in baris, nama


def test_a_small_photo_that_is_missing_falls_back_to_the_full_one_once():
    awal = HTML.index("// A small copy that is missing")
    kerja = HTML[awal : HTML.index("\n}, true);", awal)]
    assert 'document.addEventListener("error"' in kerja
    assert "dataset.penuh" in kerja and 'removeAttribute("data-penuh")' in kerja


def test_a_new_filter_does_not_flash_the_first_row():
    """Review #256: every row is "new" after a filter change, so the first one flashed."""
    kerja = fungsi("gantiSaringGrading")
    assert 'barisAtasGrading = ""' in kerja
    assert kerja.index('barisAtasGrading = ""') < kerja.index("muatGrading()")
