"""Write the button icons into console.html as CSS masks (Lampung 2026-10-08, v1.26.0).

F1: the console is one file that opens with the internet down, so the icons live inside it.
Each icon is a 24 px stroke drawing (2.2 stroke, round caps); a button shows one with
`data-ikon="<name>"`, drawn by `button[data-ikon]::before` in the text colour. Add or change an
icon in `IKON`, then run `.venv/bin/python scripts/ikon_tombol.py`.
`tests/unit/test_console_html_ikon_tombol.py` fails while the page and this list differ.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

AKAR = Path(__file__).resolve().parents[1]
HTML = AKAR / "src/palmgrade/static/console.html"
MULAI = "/* ikon-tombol:mulai, ditulis scripts/ikon_tombol.py */"
SELESAI = "/* ikon-tombol:selesai */"

IKON = {
    "cari": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    "unduh": '<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
    "unggah": '<path d="M12 15V3M7 8l5-5 5 5M5 21h14"/>',
    "simpan": '<path d="M5 12.5l4.5 4.5L19 7"/>',
    "tambah": '<path d="M12 5v14M5 12h14"/>',
    "tutup": '<path d="M6 6l12 12M18 6L6 18"/>',
    "hapus": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    "segarkan": '<path d="M20 12a8 8 0 1 1-2.34-5.66M20 4v5h-5"/>',
    "cetak": '<path d="M7 9V3h10v6M7 17H4v-8h16v8h-3M7 14h10v7H7z"/>',
    "lihat": '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "qr": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>'
          '<rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 14h3v3M21 14v.01M14 21h.01M17 21h4v-4"/>',
    "timbang": '<path d="M4 17a8 8 0 1 1 16 0M12 17l4-5M3 21h18"/>',
    "datang": '<path d="M5 21V4M5 4h12l-2.5 4L17 12H5"/>',
    "pergi": '<path d="M9 4H5v16h4M14 7l5 5-5 5M19 12H9"/>',
    "tugaskan": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "lepas": '<path d="M9 15l-2 2a3.5 3.5 0 0 1-5-5l2-2M15 9l2-2a3.5 3.5 0 0 1 5 5l-2 2M4 4l16 16"/>',
    "tolak": '<circle cx="12" cy="12" r="9"/><path d="M5.6 5.6l12.8 12.8"/>',
    "piston": '<rect x="8" y="3" width="8" height="7" rx="1"/><path d="M12 10v7M6 17h12M4 21h16"/>',
    "kirim": '<path d="M21 3L10 14M21 3l-7 18-4-7-7-4z"/>',
    "reset": '<path d="M4 12a8 8 0 1 0 2.34-5.66M4 4v5h5"/>',
    "restart": '<path d="M12 3v8M6.34 6.34a8 8 0 1 0 11.32 0"/>',
    "keluar": '<path d="M15 4h4v16h-4M10 17l-5-5 5-5M5 12h11"/>',
    "masuk": '<path d="M15 4h4v16h-4M10 17l5-5-5-5M15 12H3"/>',
    "kunci": '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M16.5 6.5l3 3"/>',
    "peran": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
    "akun-mati": '<circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0M17 8l5 5M22 8l-5 5"/>',
    "akun-hidup": '<circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0M16 11l2 2 4-4"/>',
    "akun-tambah": '<circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0M19 8v6M16 11h6"/>',
    "sebelum": '<path d="M15 18l-6-6 6-6"/>',
    "berikut": '<path d="M9 18l6-6-6-6"/>',
    "rekam": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3.5"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    "jalankan": '<path d="M7 4l13 8-13 8z"/>',
    "periksa": '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
    "waktu": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "daftar": '<path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01"/>',
    "ganti": '<path d="M4 8h13l-3-3M20 16H7l3 3"/>',
    "lewati": '<path d="M5 5l9 7-9 7zM19 5v14"/>',
}


def baris(nama: str, isi: str) -> str:
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' "
           f"stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'>{isi}</svg>")
    # ":" and "/" are encoded too, so the page never holds a plain URL (F1, zero https://).
    return f'  button[data-ikon="{nama}"] {{ --ikon:url("data:image/svg+xml,{quote(svg, safe=" =,.-")}"); }}'


def blok() -> str:
    return "\n".join(["  " + MULAI, *(baris(n, i) for n, i in IKON.items()), "  " + SELESAI])


def tanam(isi: str) -> str:
    awal = isi.index("  " + MULAI)
    akhir = isi.index(SELESAI) + len(SELESAI)
    return isi[:awal] + blok() + isi[akhir:]


if __name__ == "__main__":
    HTML.write_text(tanam(HTML.read_text(encoding="utf-8")), encoding="utf-8")
