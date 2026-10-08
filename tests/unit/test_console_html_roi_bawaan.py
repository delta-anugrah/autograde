"""Settings, detection area box: the PC's own box is shown, and one button goes back to it."""
from __future__ import annotations

import re
from pathlib import Path

HTML = (Path(__file__).resolve().parents[2] / "src" / "palmgrade" / "static" / "console.html").read_text(
    encoding="utf-8"
)


def _blok_kotak() -> str:
    blok = HTML.split('<span data-t="subKotak">', 1)[1].split("</details>", 1)[0]
    return blok


def test_tombol_kembali_ke_bawaan_ada_di_blok_kotak_dan_merah():
    """F11: every reset is `button.bahaya`."""
    tombol = re.search(r'<button[^>]*id="set-roi-reset"[^>]*>', _blok_kotak())
    assert tombol, "the reset button must sit in the detection box block"
    assert 'class="bahaya"' in tombol.group(0)
    assert 'type="button"' in tombol.group(0)


def test_keterangan_bawaan_ada_di_blok_kotak():
    assert 'id="set-roi-bawaan"' in _blok_kotak()


def test_teks_ada_dua_bahasa():
    for kunci in ("btnRoiReset", "roiBawaanPc", "roiBawaanPenuh", "roiBawaanTakTerbaca", "roiResetSimpan"):
        assert HTML.count(f"{kunci}:") == 2, f"{kunci} must exist in id and en"


def test_bawaan_dimuat_bersama_setelan_dan_jadi_placeholder():
    muat = HTML.split("async function muatRoiBawaan", 1)[1].split("\n}", 1)[0]
    assert 'api("/api/console/dev/roi-bawaan")' in muat
    assert ".placeholder =" in muat
    assert "muatRoiBawaan()" in HTML.split("async function muatSetelan", 1)[1].split("\n}", 1)[0]


def test_tombol_reset_mengosongkan_keempat_kolom_dan_mengingatkan_simpan():
    reset = HTML.split('$("set-roi-reset").addEventListener', 1)[1].split("\n});", 1)[0]
    assert "KOTAK_ROI" in reset and '.value = ""' in reset
    assert 'removeAttribute("aria-invalid")' in reset
    assert 'toastPeringatan(t("roiResetSimpan"))' in reset
