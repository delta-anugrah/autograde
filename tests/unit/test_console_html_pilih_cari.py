"""One dropdown for the whole console (batch 5.6): type to filter, trucks on site first,
never rebuilt under the finger, and no native `<select>` left.

With 100+ trucks the list was a long scroll for a gloved hand, the weighbridge picker was
replaced whole every 60 s (`outerHTML`), and the support screens still used the OS picker.

Two layers like `test_console_html_lepas_paksa.py`: text invariants (always run) and
behaviour through node with the real KAMUS (`konsol_js`).
"""
from __future__ import annotations

import json
import re

import pytest
from konsol_js import HTML, NODE, fungsi, jalankan, konstanta

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")

KUNCI = ("pilihCari", "pilihTakCocok", "grupDiLokasi", "grupTrukLain")


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_every_word_is_in_both_languages(bahasa):
    isi = _kamus(bahasa)
    for kunci in KUNCI:
        assert f"{kunci}:" in isi, f"KAMUS.{bahasa} misses {kunci}"


# ── type to filter ────────────────────────────────────────────────────────

_CARI = ["ratakanCari", "cocokCari", "hasilSaring"]


@butuh_node
@pytest.mark.parametrize(
    ("teks", "cari", "cocok"),
    [
        ("BE 1234 AB", "be1234", True),
        ("BE 1234 AB", "1234 a", True),
        ("BE 1234 AB", "  ", True),
        ("BE 1234 AB", "", True),
        ("BE 1234 AB", "4321", False),
        ("BE-1234.AB", "be1234ab", True),
        ("line-2", "LINE 2", True),
    ],
)
def test_the_filter_ignores_case_spaces_and_punctuation(teks, cari, cocok):
    assert jalankan(_CARI, f"cocokCari({json.dumps(teks)}, {json.dumps(cari)})") is cocok


@butuh_node
def test_a_section_header_stays_only_while_a_row_under_it_does():
    daftar = [
        {"grup": False, "teks": "Pilih Truk"},
        {"grup": True, "teks": "Di lokasi"},
        {"grup": False, "teks": "BE 1 AA"},
        {"grup": True, "teks": "Truk lain"},
        {"grup": False, "teks": "BE 2 BB"},
        {"grup": False, "teks": "BE 22 CC"},
    ]
    semua, dua, satu, nihil = jalankan(
        _CARI,
        f"['', '2', 'be1', 'zz'].map((c) => hasilSaring({json.dumps(daftar)}, c))",
    )
    assert semua == [True] * 6
    assert dua == [False, False, False, True, True, True]
    assert satu == [False, True, True, False, False, False]
    assert nihil == [False] * 6


@butuh_node
@pytest.mark.parametrize(("jumlah", "perlu"), [(0, False), (7, False), (8, True), (120, True)])
def test_only_a_long_list_gets_the_search_field(jumlah, perlu):
    assert jalankan(["perluCari"], f"perluCari({jumlah})", tambahan=konstanta("AMBANG_CARI")) is perlu


def test_the_search_field_is_put_in_on_open_and_taken_out_on_close():
    buka = fungsi("bukaPilih")
    assert "pasangCari(root)" in buka
    assert "(cariDulu && cari)" in buka, "the keyboard opens on the picked row, a tap in the field"
    assert "bukaPilih(root, { cariDulu: true })" in HTML
    assert "lepasCari(root)" in fungsi("tutupPilih")
    pasang = fungsi("pasangCari")
    assert "perluCari(" in pasang and 'class="pilih-cari"' in pasang and 'class="pilih-kosong"' in pasang
    assert 't("pilihCari")' in pasang and 't("pilihTakCocok")' in pasang
    assert "hasilSaring(" in fungsi("saringPilih")


def test_a_hidden_row_is_really_hidden():
    """`display:flex` on a row beats the `hidden` attribute (`test_console_html_hidden.py`)."""
    assert re.search(r'\.pilih-panel \[role="option"\]\[hidden\], \.pilih-grup\[hidden\], \.pilih-kosong\[hidden\]\s*\{\s*display:none;', HTML)


def test_the_keyboard_walks_only_the_rows_that_are_shown():
    awal = HTML.index('document.addEventListener("keydown", (ev) => {\n  const root = ev.target.closest && ev.target.closest(".pilih");')
    kerja = HTML[awal : HTML.index("\n});", awal)]
    assert "opsiTampak(root)" in kerja
    assert ".pilih-cari" in kerja, "typing on a row moves to the search field"


def test_a_click_inside_the_open_panel_does_not_close_it():
    awal = HTML.index("// One listener for every dropdown on the page")
    kerja = HTML[awal : HTML.index("\n});", awal)]
    assert 'ev.target.closest(".pilih-panel")' in kerja


# ── options that cannot be picked (model that does not fit) ───────────────


@butuh_node
def test_a_row_can_be_shown_but_not_pickable_with_its_reason():
    html = jalankan(
        ["barisPilih"],
        'barisPilih([{v:"a", teks:"A"}, {v:"b", teks:"B (tidak bisa)", mati:true, judul:"2 kelas"}], "a")',
    )
    baris_b = html[html.index('data-nilai="b"') :]
    assert 'aria-disabled="true"' in baris_b and 'title="2 kelas"' in baris_b
    assert 'aria-disabled="true"' not in html[: html.index('data-nilai="b"')]


def test_a_row_that_cannot_be_picked_is_refused_by_click_and_by_keyboard():
    assert 'aria-disabled") === "true"' in fungsi("aturPilih")
    assert "aturPilih(root, v)" in fungsi("pilihNilai")
    assert re.search(r'\.pilih-panel \[role="option"\]\[aria-disabled="true"\]\s*\{[^}]*cursor:not-allowed', HTML)


# ── trucks on site first ──────────────────────────────────────────────────

_TRUK = ('[{id:"t1", plate_number:"BE 1 AA", di_lokasi:false}, {id:"t2", plate_number:"BE 2 BB", di_lokasi:true},'
         ' {id:"t3", plate_number:"BE 3 CC", di_lokasi:false}, {id:"t4", plate_number:"BE 4 DD", di_lokasi:true}]')


@butuh_node
@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_trucks_with_an_open_ticket_lead_the_card_list_in_their_own_section(bahasa):
    opsi = jalankan(["opsiTrukKartu"], "opsiTrukKartu()", bahasa=bahasa, tambahan=f"const trucks = {_TRUK};")
    di_lokasi = jalankan([], "KAMUS[bahasa].grupDiLokasi", bahasa=bahasa)
    lain = jalankan([], "KAMUS[bahasa].grupTrukLain", bahasa=bahasa)
    assert [o["v"] for o in opsi] == ["", "t2", "t4", "t1", "t3"]
    assert [o.get("grup") for o in opsi] == [None, di_lokasi, di_lokasi, lain, lain]


@butuh_node
def test_no_truck_on_site_means_no_section_headers():
    truk = '[{id:"t1", plate_number:"BE 1 AA"}, {id:"t2", plate_number:"BE 2 BB", di_lokasi:false}]'
    opsi = jalankan(["opsiTrukKartu"], "opsiTrukKartu()", tambahan=f"const trucks = {truk};")
    assert [o["v"] for o in opsi] == ["", "t1", "t2"]
    assert all(not o.get("grup") for o in opsi)


# ── never rebuilt whole ───────────────────────────────────────────────────


def test_no_dropdown_is_replaced_whole_any_more():
    assert "outerHTML = komponenPilih(" not in HTML
    for nama, id_ in (("isiTrucks", "plat-datang"), ("isiPlatTimbang", "plat-timbang"), ("siapkanLineRiwayat", "riwayat-line")):
        assert "isiUlangPilih(" in fungsi(nama), nama
        assert re.search(rf'<div class="pilih" id="{id_}" data-nilai="">\s*<button type="button" class="pilih-tombol"', HTML), id_


# ── one component everywhere ──────────────────────────────────────────────


def test_no_native_select_is_left_on_the_screen():
    markup = HTML.split("<script>", 1)[0].split("</style>", 1)[1]
    assert "<select" not in markup
    skrip = HTML.split("<script>", 1)[1]
    assert 'createElement("option")' not in skrip and "new Option(" not in skrip


@pytest.mark.parametrize(
    "penanda",
    ['id="set-sumbu"', 'id="akun-role"', 'data-berkas="line-1"', 'data-berkas="line-3"',
     'data-model="line-1"', 'data-model="line-3"'],
)
def test_every_former_select_is_the_dropdown_component(penanda):
    awal = HTML.index(penanda)
    tag = HTML[HTML.rindex("<", 0, awal) : HTML.index(">", awal)]
    assert tag.startswith('<div class="pilih"') and "data-nilai=" in tag, tag


def test_a_dropdown_is_not_wrapped_in_a_label():
    """A click on a row inside a `<label>` is sent on to the trigger and reopens the list."""
    for cocok in re.finditer(r"<label\b[^>]*>(?:(?!</label>).)*</label>", HTML.split("<script>", 1)[0], re.S):
        assert 'class="pilih"' not in cocok.group(0), cocok.group(0)[:120]


def test_the_converted_fields_are_read_and_set_through_the_component():
    assert 'sumbu_garis: $("set-sumbu").dataset.nilai' in HTML
    assert 'role: $("akun-role").dataset.nilai' in HTML
    assert 'aturPilih($("set-sumbu"), r.sumbu_garis ?? "tegak")' in HTML
    assert '$("set-sumbu").addEventListener("pilih", labelGaris)' in HTML
    assert "isiUlangPilih(" in fungsi("isiBerkasSumber") and "isiUlangPilih(" in fungsi("opsiModel")
    assert 'el.addEventListener("pilih", () => rinciModel(el.dataset.model))' in HTML
