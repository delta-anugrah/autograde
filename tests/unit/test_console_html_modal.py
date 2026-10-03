"""One modal component for every text dialog in the console (user 2026-10-03).

The four text dialogs (model swap, confirmation, CSV import, version and licence) each
carried their own copy of the box, backdrop and button row, and the version box had drifted:
its Update now button sat alone on the left with its own size while Tutup sat on the right in
another. Now they share `dialog.modal`, `.modal-isi` and `.modal-tombol`, and the buttons in
that row share one width (F5). The photo viewer is not a text dialog and keeps its own shape.
"""

from __future__ import annotations

import re

import pytest
from konsol_js import HTML, NODE, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada (image CI)")
DIALOG_TEKS = ("model-modal", "konfirmasi-modal", "impor-modal", "info-sistem-modal")


def _aturan(selector: str) -> str:
    awal = HTML.find("\n  " + selector + " {")
    assert awal != -1, f"aturan CSS `{selector}` tidak ada"
    return HTML[awal : HTML.find("}", awal)]


def _dialog(id_: str) -> str:
    awal = HTML.index(f'<dialog id="{id_}"')
    return HTML[awal : HTML.index("</dialog>", awal)]


def test_komponen_modal_satu_aturan():
    kotak = _aturan("dialog.modal")
    assert "padding:0" in kotak and "background:var(--card)" in kotak
    assert "dialog.modal::backdrop" in HTML
    assert "padding" in _aturan(".modal-isi")
    tombol = _aturan(".modal-tombol > button")
    # One width for every button in the row (F5), large enough for a gloved thumb.
    assert "flex:1 1 0" in tombol and "min-height:48px" in tombol


@pytest.mark.parametrize("id_", DIALOG_TEKS)
def test_dialog_teks_memakai_komponen(id_):
    dialog = _dialog(id_)
    assert re.search(r'<dialog id="[^"]+" class="modal"', dialog), dialog[:120]
    assert '<div class="modal-isi">' in dialog
    assert 'class="modal-tombol"' in dialog
    # The global `.tools` is a framed table header; inside a modal it read as a broken box.
    assert 'class="tools"' not in dialog


@pytest.mark.parametrize("id_", DIALOG_TEKS)
def test_tidak_ada_salinan_kotak_per_dialog(id_):
    assert f"#{id_}::backdrop" not in HTML
    assert f"#{id_} .tools" not in HTML


def test_tutup_versi_merah_pasang_hijau():
    dialog = _dialog("info-sistem-modal")
    tutup = re.search(r'<button[^>]*id="info-sistem-tutup"[^>]*>', dialog).group(0)
    assert 'class="bahaya"' in tutup
    # Tutup first: it takes the first focus, so a stray Enter closes instead of installing.
    assert dialog.index('id="info-sistem-tutup"') < dialog.index('id="info-sistem-pasang"')


@butuh_node
def test_tombol_pasang_utama_dan_terpisah_dari_isi():
    fungsi = ["tombolPasang", "teksHasilPembaruan", "htmlPembaruan"]
    ikon = "const IKON_UNDUH = '<svg></svg>';"
    siap = "{terpasang:true, siap:'v1.23.0', berjalan:false, hasil:null}"
    tombol = jalankan(fungsi, f"tombolPasang({siap})", tambahan=ikon)
    assert 'class="pembaruan-pasang utama" data-target="v1.23.0"' in tombol
    # In the modal the button lives in the button row, not inside the text.
    isi = jalankan(fungsi, f"htmlPembaruan({siap}, false, false)", tambahan=ikon)
    assert "pembaruan-pasang" not in isi and "v1.23.0" in isi
    berjalan = "{terpasang:true, siap:null, berjalan:true, hasil:null}"
    assert jalankan(fungsi, f"tombolPasang({berjalan})", tambahan=ikon) == ""
