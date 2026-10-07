"""Shell of the new look (spec 2026-10-07 §5.1): left rail with icons, a hide button kept per
browser, a header with the view title and status pills, ribbons under the header, the
cameras hidden (never removed) off Grading."""
from __future__ import annotations

import json
import re

import pytest
from konsol_js import HTML, NODE, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")


def test_tab_jadi_rel_kiri_dengan_ikon():
    rel = re.search(r'<nav id="tabs"[^>]*>(.*?)</nav>', HTML, re.S).group(1)
    for tab in ("grading", "truk", "timbangan", "rekap", "log", "status", "akun", "line", "setelan"):
        tombol = re.search(rf'<button data-tab="{tab}"[^>]*>(.*?)</button>', rel, re.S).group(1)
        assert "<svg" in tombol and 'data-t="judul' in tombol, tab
    # The Support divider leaves the DOM with the support tabs for an operator account.
    assert re.search(r'class="rel-pisah"[^>]*data-dev="1"', rel)


def test_tombol_sembunyikan_menu_di_kepala():
    kepala = re.search(r'<header id="topbar">(.*?)</header>', HTML, re.S).group(1)
    assert 'id="menu-samping"' in kepala and 'aria-controls="tabs"' in kepala
    for id_ in ("judul-tampilan", "hari-kerja", "perusahaan", "pil-plc", "sinkron-erp", "sinkron-cloud", "info-sistem"):
        assert f'id="{id_}"' in kepala, id_


def test_pita_tepat_di_bawah_kepala():
    for pita in ("pita-pembaruan", "pita-alarm", "pita-disk", "pita-sesi"):
        assert HTML.index(f'id="{pita}"') < HTML.index('<section id="tally">'), pita


def test_lines_disembunyikan_bukan_dibuang_di_tampilan_lain():
    assert re.search(r'body:not\(\[data-tab="grading"\]\)\s*:is\([^)]*#lines[^)]*\)\s*\{\s*display:none', HTML)
    assert 'document.body.dataset.tab = tab' in HTML


def test_menu_samping_diingat_per_browser():
    assert 'baca("menuSamping"' in HTML and 'simpan("menuSamping"' in HTML


def _plc(reachable, terpasang):
    return {"plc": {"reachable": reachable, "piston_requested": False if terpasang else None}}


@butuh_node
@pytest.mark.parametrize(("lines", "keadaan", "teks"), [
    ([_plc(True, True)] * 3, "tersambung", "3/3"),
    ([_plc(True, True), _plc(False, True), _plc(True, True)], "terputus", "2/3"),
    ([_plc(True, False)] * 3, "tidak_dipakai", None),
])
def test_ringkas_plc(lines, keadaan, teks):
    r = jalankan(["ringkasPlc"], f"ringkasPlc({json.dumps(lines)})")
    assert r["keadaan"] == keadaan
    if teks:
        assert r["teks"] == teks
