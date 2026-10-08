"""Sign-in, new look (spec 2026-10-07 §5.4): a product photo with one detection box and three
facts on one side, the form with account chips on the other. Same ids as before; the photo is
one JPEG of at most 60 KB written into the page by `scripts/tanam_foto_masuk.py` (F1)."""
from __future__ import annotations

import importlib.util
import json
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


def test_photos_are_embedded_and_match_the_assets():
    assert tanam_foto_masuk.tanam(HTML) == HTML, "jalankan scripts/tanam_foto_masuk.py"


def test_every_photo_is_at_most_60_kb():
    foto = sorted((AKAR / "assets/masuk").glob("*.jpg"))
    assert [f.stem for f in foto] == ["ripe", "unripe"]
    for f in foto:
        assert f.stat().st_size <= 60 * 1024, f.name


@pytest.mark.parametrize("kelas", ["ripe", "unripe"])
def test_each_class_photo_is_a_jpeg_data_uri_with_its_own_box(kelas):
    """Owner 2026-10-08: the photo turns through the classes it has (JK and TP to come)."""
    assert re.search(rf"--foto-masuk-{kelas}:url\(data:image/jpeg;base64,[A-Za-z0-9+/=]+\)", HTML)
    assert re.search(rf'\.gerbang-bingkai\[data-kelas="{kelas}"\] #gerbang-foto \{{ background-image:var\(--foto-masuk-{kelas}\); \}}', HTML)
    assert re.search(rf'\.gerbang-bingkai\[data-kelas="{kelas}"\] \.gerbang-deteksi \{{ left:[\d.]+%; top:[\d.]+%; width:[\d.]+%; height:[\d.]+%; \}}', HTML)


def test_the_page_knows_which_classes_it_has():
    assert 'const KELAS_FOTO_MASUK = ["ripe", "unripe"];' in HTML


def test_the_photo_turns_every_4_s_only_while_the_gate_shows():
    kerja = re.search(r"function gantiFotoMasuk\(\) \{(.*?)\n\}", HTML, re.S).group(1)
    assert '$("gerbang").hidden' in kerja and "KELAS_FOTO_MASUK" in kerja
    assert "setInterval(gantiFotoMasuk, 4000)" in HTML


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
    assert 'class="gerbang-bingkai" data-kelas="ripe"' in gerbang


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
def test_operator_chip_is_just_the_email():
    """Owner 2026-10-08: the chip holds the email only (name and initials made it too big);
    the name stays as its hover title."""
    html = jalankan(["tombolOperator", "inisialNama"], 'tombolOperator({email: "a@b.c", full_name: "Budi Santoso"})')
    assert 'data-email="a@b.c"' in html and 'aria-pressed="false"' in html and 'title="Budi Santoso"' in html
    assert re.sub(r"<[^>]+>", "", html).strip() == "a@b.c"
    assert "gerbang-op-inisial" not in html


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


def test_account_chips_are_small_pills_that_wrap():
    aturan = re.search(r"\.gerbang-nama \{([^}]*)\}", HTML).group(1)
    assert "flex-wrap:wrap" in aturan and "overflow-y:auto" in aturan
    chip = re.search(r"\.gerbang-op \{([^}]*)\}", HTML).group(1)
    assert "min-height:44px" in chip and "border-radius:var(--r-pill)" in chip


def test_photo_frame_takes_its_height_from_its_width():
    aturan = re.search(r"\.gerbang-bingkai \{([^}]*)\}", HTML).group(1)
    assert "aspect-ratio:6 / 5" in aturan and re.search(r"(?<!-)height:", aturan) is None


def test_headline_to_photo_is_centred():
    """Owner 2026-10-08: the block from the headline down to the photo sits in the middle of the hero."""
    tengah = re.search(r"\.gerbang-tengah \{([^}]*)\}", HTML).group(1)
    assert "justify-items:center" in tengah and "text-align:center" in tengah


@butuh_node
@pytest.mark.parametrize(
    ("tersimpan", "harapan"),
    [
        ({}, "en"),                                   # a brand-new browser: the sign-in a prospect sees
        ({"tab": "grading"}, "id"),                   # a kiosk that used the console, never pressed ID / EN
        ({"tema": "gelap", "urutan": "x"}, "id"),
        ({"bahasa": "en", "tab": "grading"}, "en"),   # a choice is a choice
        ({"bahasa": "id"}, "id"),
        ({"bahasa": "fr"}, "en"),                     # unknown value: treated as no choice
    ],
)
def test_first_language_is_english_only_for_a_new_browser(tersimpan, harapan):
    jejak = re.search(r"^const JEJAK_KONSOL = .*$", HTML, re.M).group(0)
    awal = jejak + "\nconst ambil = (k) => (" + json.dumps(tersimpan) + ")[k] || '';"
    assert jalankan(["bahasaAwal"], "bahasaAwal(ambil)", tambahan=awal) == harapan
