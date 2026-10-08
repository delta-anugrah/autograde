"""Embed the sign-in photos (`assets/masuk/<class>.jpg`) into console.html as data URIs.

F1: the console is one file that opens with the internet down, so its pictures live inside it.
One photo per grading class, shown in turn on the sign-in (owner 2026-10-08): `ripe`, `unripe`,
`jk`, `tp`, whichever files exist, in that order. Each is 600 x 500 (the camera's 6:5), JPEG,
at most 60 KB; its detection box (percent of the frame) is in `assets/masuk/kotak.json`.
Run after adding or changing one: `.venv/bin/python scripts/tanam_foto_masuk.py`.
`tests/unit/test_console_html_masuk.py` fails while the page and the files differ.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

AKAR = Path(__file__).resolve().parents[1]
HTML = AKAR / "src/palmgrade/static/console.html"
FOTO = AKAR / "assets/masuk"
URUTAN = ("ripe", "unripe", "jk", "tp")
MULAI = "/* foto-masuk:mulai, ditulis scripts/tanam_foto_masuk.py */"
SELESAI = "/* foto-masuk:selesai */"
MULAI_JS = "// foto-masuk-kelas:mulai, ditulis scripts/tanam_foto_masuk.py"
SELESAI_JS = "// foto-masuk-kelas:selesai"


def kelas_ada() -> list[str]:
    return [k for k in URUTAN if (FOTO / f"{k}.jpg").exists()]


def blok_css() -> str:
    kotak = json.loads((FOTO / "kotak.json").read_text(encoding="utf-8"))
    nilai, aturan = [], []
    for k in kelas_ada():
        data = base64.b64encode((FOTO / f"{k}.jpg").read_bytes()).decode("ascii")
        nilai.append(f"--foto-masuk-{k}:url(data:image/jpeg;base64,{data});")
        kiri, atas, lebar, tinggi = kotak[k]
        aturan.append(f'  .gerbang-bingkai[data-kelas="{k}"] #gerbang-foto {{ background-image:var(--foto-masuk-{k}); }}')
        aturan.append(f'  .gerbang-bingkai[data-kelas="{k}"] .gerbang-deteksi {{ left:{kiri}%; top:{atas}%;'
                      f" width:{lebar}%; height:{tinggi}%; }}")
    return "\n".join([MULAI, "  #gerbang { " + " ".join(nilai) + " }", *aturan, "  " + SELESAI])


def blok_js() -> str:
    daftar = ", ".join(f'"{k}"' for k in kelas_ada())
    return f"{MULAI_JS}\nconst KELAS_FOTO_MASUK = [{daftar}];\n{SELESAI_JS}"


def _ganti(isi: str, mulai: str, selesai: str, baru: str) -> str:
    awal = isi.index(mulai)
    akhir = isi.index(selesai) + len(selesai)
    return isi[:awal] + baru + isi[akhir:]


def tanam(isi: str) -> str:
    return _ganti(_ganti(isi, MULAI, SELESAI, blok_css()), MULAI_JS, SELESAI_JS, blok_js())


if __name__ == "__main__":
    HTML.write_text(tanam(HTML.read_text(encoding="utf-8")), encoding="utf-8")
