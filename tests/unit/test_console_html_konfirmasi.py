"""One in-page confirm dialog, no native browser dialogs (user 2026-10-03).

The browser's own `confirm` box ignores the dark theme, prints the console's address in its
title on the kiosk and cannot be read from metres away. Every "are you sure?" goes through
`tanyaKonfirmasi({judul, pesan, ya, batal, bahaya})`, a `<dialog>` that resolves to true or
false; behaviour (focus, Esc, backdrop, Enter) is in `tests/browser/test_browser_konfirmasi.py`.
"""
from __future__ import annotations

import re
from pathlib import Path

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()


def _skrip_tanpa_komentar() -> str:
    """Every `<script>` body with its `//` and `/* */` comments removed: a comment may name
    the banned functions to explain why they are banned."""
    skrip = "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", HTML, re.S))
    skrip = re.sub(r"/\*.*?\*/", "", skrip, flags=re.S)
    return re.sub(r"(?<![:\\])//[^\n]*", "", skrip)


def _fungsi(nama: str) -> str:
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


def test_tidak_ada_dialog_bawaan_browser_di_skrip():
    skrip = _skrip_tanpa_komentar()
    telanjang = re.findall(r"(?<![\w$.])(confirm|alert|prompt)\s*\(", skrip)
    lewat_window = re.findall(r"\b(?:window|self|globalThis)\s*(?:\.\s*|\[\s*[\"'])(confirm|alert|prompt)\b", skrip)
    assert not telanjang and not lewat_window, (
        f"native browser dialog in console.html: {telanjang + lewat_window}; use tanyaKonfirmasi()"
    )


def test_penjaga_menangkap_panggilan_yang_dilarang():
    """The guard above is a regex: prove it would catch the shapes it bans."""
    for kode in ("if (!confirm(x)) return;", "alert('x')", "window.prompt('a')", 'window["confirm"](1)'):
        cocok = re.search(r"(?<![\w$.])(confirm|alert|prompt)\s*\(", kode) or re.search(
            r"\b(?:window|self|globalThis)\s*(?:\.\s*|\[\s*[\"'])(confirm|alert|prompt)\b", kode)
        assert cocok, kode
    for kode in ("tanyaKonfirmasi({})", 'role="alert"', "el.prompt2(", "obj.confirm("):
        assert not re.search(r"(?<![\w$.])(confirm|alert|prompt)\s*\(", kode), kode


def test_dialog_bersama_ada_dengan_batal_lebih_dulu():
    blok = re.search(r'<dialog id="konfirmasi-modal"[^>]*>(.*?)</dialog>', HTML, re.S)
    assert blok, "no #konfirmasi-modal dialog"
    assert 'aria-labelledby="konfirmasi-judul"' in HTML
    isi = blok.group(1)
    assert isi.index('id="konfirmasi-tidak"') < isi.index('id="konfirmasi-ya"'), (
        "Batal comes first: an accidental Enter cancels"
    )
    # Red like every other cancel (F11, user 2026-10-03); the first focus keeps it the safe choice.
    tidak = re.search(r'<button\b[^>]*id="konfirmasi-tidak"[^>]*>', isi).group(0)
    assert 'class="bahaya"' in tidak, tidak


def test_bahaya_membuat_konfirmasi_merah_pekat():
    fn = _fungsi("tanyaKonfirmasi")
    assert 'bahaya ? "bahaya pekat" : "utama"' in fn
    assert "showModal()" in fn and "new Promise(" in fn
    assert '$("konfirmasi-tidak").focus()' in fn, "initial focus on the safe choice"
    assert ".focus()" in fn.split("modal.close()", 1)[1], "focus goes back after closing"


def test_esc_batal_dan_backdrop_menjawab_false():
    awal = HTML.index('$("konfirmasi-ya").addEventListener')
    blok = HTML[awal : HTML.index("\n});", HTML.index('$("konfirmasi-modal").addEventListener("close"')) + 4]
    assert "jawabKonfirmasi(true)" in blok.split("\n", 1)[0]
    assert blok.count("jawabKonfirmasi(false)") == 3, "Batal, backdrop and Esc (close) answer false"
    assert "ev.target === ev.currentTarget" in blok
    assert "!ev.currentTarget.open" in blok, "a close from an older question never answers a newer one"


def test_piston_dan_lewati_memakai_dialog_bersama():
    lines = HTML[HTML.index('$("lines").addEventListener("click"') :]
    assert "tanyaKonfirmasi(" in lines.split("\n});", 1)[0]
    antre = HTML[HTML.index('$("antrean-bongkar").addEventListener("click"') :]
    antre = antre.split("\n});", 1)[0]
    assert "async (ev)" in antre and "await tanyaKonfirmasi(" in antre
    assert antre.index("tanyaKonfirmasi(") < antre.index("denganSibuk("), "ask before the busy lock"


def test_kata_dialog_di_kedua_bahasa():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        for kunci in ("konfirmasiYa", "konfirmasiTidak", "konfirmasiBukaJudul", "konfirmasiBuka",
                      "konfirmasiLewatiJudul", "konfirmasiLewati"):
            assert f"{kunci}:" in isi, f"KAMUS.{bahasa} misses {kunci}"
    assert 'konfirmasiTidak:"Batal"' in _kamus("id") and 'konfirmasiTidak:"Cancel"' in _kamus("en")
