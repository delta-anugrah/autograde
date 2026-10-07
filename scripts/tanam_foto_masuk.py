"""Embed the sign-in photo (`assets/masuk/masuk.jpg`) into console.html as a data URI.

F1: the console is one file that opens with the internet down, so its one picture lives
inside it, as the CSS custom property `--foto-masuk` on `#gerbang` (spec 2026-10-07 §5.4).
The photo is frame 134 of `media/sample_sawit_video.avi` (a Lampung camera), 600 x 500,
JPEG quality 84, at most 60 KB. Run after changing it: `.venv/bin/python scripts/tanam_foto_masuk.py`.
`tests/unit/test_console_html_masuk.py` fails while the page and the file differ.
"""
from __future__ import annotations

import base64
from pathlib import Path

AKAR = Path(__file__).resolve().parents[1]
HTML = AKAR / "src/palmgrade/static/console.html"
FOTO = AKAR / "assets/masuk/masuk.jpg"
MULAI = "/* foto-masuk:mulai, ditulis scripts/tanam_foto_masuk.py */"
SELESAI = "/* foto-masuk:selesai */"


def blok() -> str:
    data = base64.b64encode(FOTO.read_bytes()).decode("ascii")
    return f"{MULAI}\n  #gerbang {{ --foto-masuk:url(data:image/jpeg;base64,{data}); }}\n  {SELESAI}"


def tanam(isi: str) -> str:
    awal = isi.index(MULAI)
    akhir = isi.index(SELESAI) + len(SELESAI)
    return isi[:awal] + blok() + isi[akhir:]


if __name__ == "__main__":
    HTML.write_text(tanam(HTML.read_text(encoding="utf-8")), encoding="utf-8")
