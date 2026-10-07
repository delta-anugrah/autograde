"""Embed the console fonts (`assets/fonts/*.woff2`) into console.html as data URIs.

F1: the console is one file that opens with the internet down, so its fonts live inside it.
Run after changing a font file: `.venv/bin/python scripts/tanam_font.py`.
`tests/unit/test_console_html_font.py` fails while the page and the files differ.
The files are the Google Fonts latin subsets, OFL licensed (`assets/fonts/OFL-*.txt`).
"""
from __future__ import annotations

import base64
from pathlib import Path

AKAR = Path(__file__).resolve().parents[1]
HTML = AKAR / "src/palmgrade/static/console.html"
FONT = AKAR / "assets/fonts"
MULAI = "/* font:mulai, ditulis scripts/tanam_font.py */"
SELESAI = "/* font:selesai */"
DAFTAR = (
    ("Plus Jakarta Sans", "400 800", "plus-jakarta-sans-latin.woff2"),
    ("Barlow Condensed", "500", "barlow-condensed-500-latin.woff2"),
    ("Barlow Condensed", "600", "barlow-condensed-600-latin.woff2"),
    ("Barlow Condensed", "700", "barlow-condensed-700-latin.woff2"),
)


def blok() -> str:
    baris = [MULAI]
    for nama, berat, berkas in DAFTAR:
        data = base64.b64encode((FONT / berkas).read_bytes()).decode("ascii")
        baris.append(f'  @font-face {{ font-family:"{nama}"; font-style:normal; font-weight:{berat};'
                     f' font-display:swap; src:url(data:font/woff2;base64,{data}) format("woff2"); }}')
    baris.append("  " + SELESAI)
    return "\n".join(baris)


def tanam(isi: str) -> str:
    awal = isi.index(MULAI)
    akhir = isi.index(SELESAI) + len(SELESAI)
    return isi[:awal] + blok() + isi[akhir:]


if __name__ == "__main__":
    HTML.write_text(tanam(HTML.read_text(encoding="utf-8")), encoding="utf-8")
