"""Settings as stacked, full-width, collapsible sections (owner 2026-10-08): one `details` per
category inside each sub-tab, e.g. Kamera & Conveyor = Conveyor & tampilan, Garis capture,
Kotak area deteksi. A sub-tab with one category opens it; the sections opened are remembered."""
from __future__ import annotations

import re

import pytest
from konsol_js import HTML

SETELAN = HTML.split('<section id="sec-setelan"', 1)[1].split('<section id="sec-status"', 1)[0]
HARAPAN = {
    "grading": ["grading"],
    "kamera": ["conveyor", "garis", "kotak"],
    "dev": ["dev", "dummy"],
    "penugasan": ["otomatis", "lines"],
    "scanner": ["scanner"],
    "slip": ["slip"],
    "harikerja": ["harikerja"],
}


def _grup(nama: str) -> str:
    return "".join(re.findall(rf'data-setelan-grup="{nama}">(.*?)\n    </div>\n', SETELAN, re.S))


@pytest.mark.parametrize(("grup", "bagian"), sorted(HARAPAN.items()))
def test_each_sub_tab_is_a_stack_of_named_sections(grup, bagian):
    isi = _grup(grup)
    assert re.findall(r'<details class="setelan-bagian" data-bagian="([\w-]+)"', isi) == bagian
    assert isi.count('<summary class="setelan-bagian-judul">') == len(bagian)


@pytest.mark.parametrize(("grup", "bagian"), sorted(HARAPAN.items()))
def test_a_lone_section_opens_and_a_stack_starts_closed(grup, bagian):
    isi = _grup(grup)
    terbuka = re.findall(r'<details class="setelan-bagian" data-bagian="[\w-]+" open>', isi)
    assert len(terbuka) == (1 if len(bagian) == 1 else 0)


def test_no_three_column_grid_and_no_fieldset_blocks_left():
    assert "setelan-tiga" not in HTML and 'class="setelan-sub"' not in SETELAN


def test_sections_are_full_width_cards():
    aturan = re.search(r"\n  \.setelan-bagian \{([^}]*)\}", HTML).group(1)
    assert "border:1px solid var(--line)" in aturan and "border-radius:var(--r-md)" in aturan


def test_opened_sections_are_remembered_and_a_refused_value_opens_its_section():
    assert 'simpan("setelanTerbuka"' in HTML and 'baca("setelanTerbuka"' in HTML
    simpan = HTML.split('$("set-simpan").addEventListener', 1)[1].split("\n}));", 1)[0]
    assert '.closest("details.setelan-bagian")' in simpan
