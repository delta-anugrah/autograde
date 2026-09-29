"""Menjalankan potongan JS `console.html` lewat node, dengan KAMUS ASLI.

Test lain menyalin `_fungsi()` masing-masing dan memakai KAMUS tiruan; yang ini
dipakai bersama test unit dan e2e penjaga AI (batch 2.1), yang justru ingin
membaca kalimat yang sungguh tampil di layar. Terimpor sebagai `konsol_js`
karena `tests/conftest.py` menaruh `tests/` di `sys.path` (pola `model_palsu`).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "src/palmgrade/static/console.html").read_text()
NODE = shutil.which("node")


def fungsi(nama: str) -> str:
    """Satu fungsi tingkat atas, sampai baris pertama yang menutupnya."""
    awal = HTML.index(f"function {nama}(")
    if HTML[awal - 6 : awal] == "async ":
        awal -= 6
    return HTML[awal : HTML.index("\n}", awal) + 2]


def esc_asli() -> str:
    """`esc` di layar adalah arrow function, bukan `function esc(`."""
    awal = HTML.index("const esc = ")
    return HTML[awal : HTML.index("\nconst KOSONG", awal) + 1]


def kamus_asli() -> str:
    awal = HTML.index("const KAMUS = {")
    return HTML[awal : HTML.index("\n};", awal) + 3]


def konstanta(*nama: str) -> str:
    """Baris `const NAMA = ...;` apa adanya dari layar (konstanta satu baris)."""
    baris = []
    for n in nama:
        awal = HTML.index(f"\nconst {n} = ") + 1
        baris.append(HTML[awal : HTML.index("\n", awal)])
    return "\n".join(baris)


def jalankan(
    fungsi_dipakai: list[str],
    ekspresi: str,
    *,
    bahasa: str = "id",
    tz: str = "Asia/Jakarta",
    tambahan: str = "",
):
    """Evaluasi `ekspresi` sesudah KAMUS asli + fungsi yang disebut; hasil JSON.

    `tambahan` (stub, konstanta) disisipkan sebelum fungsi-fungsinya.
    """
    skrip = "\n".join(
        [
            kamus_asli(),
            esc_asli(),
            f"let bahasa = {json.dumps(bahasa)};",
            'const KOSONG = "-";',
            "const t = (k) => KAMUS[bahasa][k] ?? k;",
            'const lokal = () => (bahasa === "id" ? "id-ID" : "en-GB");',
            tambahan,
            *(fungsi(n) for n in fungsi_dipakai),
            f"console.log(JSON.stringify({ekspresi}));",
        ]
    )
    hasil = subprocess.run(
        [NODE, "-e", skrip], capture_output=True, text=True, timeout=30,
        env={**os.environ, "TZ": tz},
    )
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout)
