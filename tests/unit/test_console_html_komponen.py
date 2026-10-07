"""The other views in the new look (spec 2026-10-07 §4, §5.5, PR 5): the brand blue for every
selection, boxes inside a card without a second heavy outline, plates as plate chips, JK violet,
and no colour or radius that points at a token which does not exist."""
from __future__ import annotations

import re

import pytest
from konsol_js import HTML, NODE, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")


def test_every_token_used_is_defined():
    """`var(--r)`, `var(--aksen)` and `var(--kartu)` pointed at nothing: the Setelan fields came
    out square and their focus ring had no colour. A token set from JS counts as defined."""
    dipakai = set(re.findall(r"var\(--([\w-]+)", HTML))
    ditulis = set(re.findall(r"--([\w-]+)\s*:", HTML))
    dari_js = set(re.findall(r"""setProperty\(\s*["'`]--([\w-]+)""", HTML))
    assert dipakai - ditulis - dari_js == set()


def test_selection_is_the_brand_blue():
    for pemilih in (r"\.sub-tab button\.aktif, \.sub-tab button\.aktif:hover:not\(:disabled\)",
                    r"\.riwayat-cepat button\.aktif"):
        aturan = re.search(pemilih + r" \{([^}]*)\}", HTML).group(1)
        assert "var(--merek)" in aturan and "var(--acc)" not in aturan, pemilih


def test_boxes_inside_a_card_have_no_heavy_outline():
    for pemilih in (r"\n  \.tools \{", r"\n  \.tabel \{", r"\n  \.riwayat-ringkasan \{"):
        aturan = re.search(pemilih + r"([^}]*)\}", HTML).group(1)
        assert "var(--line-kuat)" not in aturan and "border-left:5px" not in aturan, pemilih


@pytest.mark.parametrize(("kelas", "token"), [("ripe", "ripe"), ("unripe", "unripe"), ("jk", "jk"), ("tp", "tp")])
def test_recap_summary_uses_the_class_colours(kelas, token):
    assert re.search(rf"\.riwayat-ringkasan \.stat\.{kelas} b \{{ color:var\(--{token}\); \}}", HTML)


def test_recap_summary_marks_jk_as_jk_not_unripe():
    kerja = re.search(r"function isiRingkasanRiwayat\(r\) \{(.*?)\n\}", HTML, re.S).group(1)
    assert 'kotak("jk", "clsJk"' in kerja and 'kotak("unripe", "clsUnripe"' in kerja


DASH = re.search(r"^const dash = .*$", HTML, re.M).group(0)


@butuh_node
def test_chip_plat_escapes_and_falls_back_to_a_dash():
    assert jalankan(["chipPlat"], 'chipPlat("BE <1> AA")', tambahan=DASH) == '<b class="plat">BE &lt;1&gt; AA</b>'
    assert jalankan(["chipPlat"], "chipPlat(null)", tambahan=DASH) == "-"
    assert jalankan(["chipPlat"], 'chipPlat("")', tambahan=DASH) == "-"


@pytest.mark.parametrize("sumber", ["tr.plate_number", "w.plate_number", "a.plate_number", "r.plate_number"])
def test_plate_cells_are_chips(sumber):
    assert f'<td class="key">${{dash({sumber})}}' not in HTML
    assert f'<td class="key">${{chipPlat({sumber})}}' in HTML

