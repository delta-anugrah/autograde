"""Sign-in, new look (spec 2026-10-07 §5.4): a product photo with one detection box and three
facts on one side, the form with account chips on the other. Same ids as before; the photo is
one JPEG of at most 60 KB written into the page by `scripts/tanam_foto_masuk.py` (F1)."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
from konsol_js import HTML, NODE, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")

AKAR = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("tanam_foto_masuk", AKAR / "scripts/tanam_foto_masuk.py")
tanam_foto_masuk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tanam_foto_masuk)

KUNCI = ("gerbangHeroJudul", "gerbangHeroIsi", "gerbangFakta1", "gerbangFakta2", "gerbangFakta3",
         "gerbangFotoAlt", "gerbangCatatan", "gerbangLabelEmail", "gerbangLabelSandi")


def _gerbang() -> str:
    return HTML.split('<div id="gerbang"', 1)[1].split("<!-- /gerbang -->", 1)[0]


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


def test_photo_is_embedded_and_matches_the_asset():
    assert tanam_foto_masuk.tanam(HTML) == HTML, "jalankan scripts/tanam_foto_masuk.py"


def test_photo_is_at_most_60_kb():
    assert (AKAR / "assets/masuk/masuk.jpg").stat().st_size <= 60 * 1024


def test_photo_is_a_jpeg_data_uri_not_a_link():
    assert re.search(r"--foto-masuk:url\(data:image/jpeg;base64,[A-Za-z0-9+/=]+\)", HTML)


def test_gate_is_split_with_the_same_ids():
    gerbang = _gerbang()
    for id_ in ("gerbang-email", "gerbang-sandi", "gerbang-lihat", "gerbang-masuk", "gerbang-pesan",
                "gerbang-nama", "gerbang-judul", "gerbang-foto", "gerbang-bahasa"):
        assert f'id="{id_}"' in gerbang, id_
    assert 'class="gerbang-hero"' in gerbang and 'class="gerbang-form"' in gerbang


def test_the_photo_has_one_detection_box_and_an_alt():
    gerbang = _gerbang()
    assert gerbang.count('class="gerbang-deteksi"') == 1
    assert re.search(r'id="gerbang-foto" role="img" data-t-lb="gerbangFotoAlt"', gerbang)


def test_three_facts():
    fakta = re.search(r'<ul class="gerbang-fakta">(.*?)</ul>', _gerbang(), re.S).group(1)
    assert [m for m in re.findall(r'data-t="(gerbangFakta\d)"', fakta)] == ["gerbangFakta1", "gerbangFakta2", "gerbangFakta3"]


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_gate_words_in_both_languages(bahasa):
    isi = _kamus(bahasa)
    for kunci in KUNCI:
        assert f"{kunci}:" in isi, f"KAMUS.{bahasa} misses {kunci}"


def test_narrow_window_keeps_the_form_and_drops_the_hero():
    blok = re.search(r"@media \(max-width:900px\) \{(.*?)\n  \}", HTML, re.S).group(1)
    assert re.search(r"\.gerbang-hero \{ display:none; \}", blok)


@butuh_node
def test_operator_chip_has_initials_name_and_email():
    html = jalankan(["tombolOperator", "inisialNama"], 'tombolOperator({email: "a@b.c", full_name: "Budi Santoso"})')
    assert 'data-email="a@b.c"' in html and 'aria-pressed="false"' in html
    assert re.search(r'<span class="gerbang-op-inisial"[^>]*>BS</span\s*>', html)
    assert re.search(r'<span class="gerbang-op-nama">Budi Santoso</span\s*>', html)
    assert '<span class="gerbang-op-email">a@b.c</span>' in html


@butuh_node
def test_operator_chip_escapes_name_and_email():
    html = jalankan(["tombolOperator", "inisialNama"],
                    'tombolOperator({email: "a\\"@b.c", full_name: "Budi <Santoso>"})')
    assert "<Santoso>" not in html and "Budi &lt;Santoso&gt;" in html
    assert 'data-email="a&quot;@b.c"' in html


def test_typing_or_picking_marks_the_chip():
    kerja = re.search(r"function tandaiOperator\(\) \{(.*?)\n\}", HTML, re.S).group(1)
    assert 'aria-pressed' in kerja and '$("gerbang-email").value' in kerja
    assert re.search(r'\$\("gerbang-email"\)\.addEventListener\("input", tandaiOperator\)', HTML)


def test_language_buttons_on_the_gate_reuse_the_header_switch():
    assert re.search(r'id="gerbang-bahasa"', _gerbang())
    assert re.search(r'\$\("bahasa"\)\.click\(\)', HTML)
