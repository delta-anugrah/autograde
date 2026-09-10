"""Penjaga statis untuk `static/console.html`.

Layar operator tidak punya build step maupun test runner JS — sengaja, supaya
tetap bisa dibuka saat internet mati. Yang dijaga di sini cuma satu invarian
yang gampang sekali dibalikkan tanpa sadar: nilai dari server tidak boleh
pernah mendarat di dalam string JavaScript di atribut HTML.

`line_code` bisa berisi `machine_id` mentah dari payload event (line yang
machine_id-nya tidak cocok registry), jadi `onclick="tugaskan('${x}')"` adalah
konteks injeksi sungguhan, bukan teori — dan `esc()` versi awal memang tidak
meloloskan kutip tunggal.
"""
from __future__ import annotations

import re
from pathlib import Path

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()


def test_tanpa_handler_inline():
    # Tombol dipasang lewat delegasi + data-line, bukan atribut on*.
    assert not re.search(r"\son[a-z]+\s*=\s*[\"']", HTML), "handler inline muncul lagi"
    assert 'data-line="' in HTML


def test_escaper_menutup_kedua_kutip():
    escaper = next(baris for baris in HTML.splitlines() if "const esc =" in baris)
    for karakter in ("&", "<", ">", '"', "'", "`"):
        assert karakter in escaper, f"esc() tidak meloloskan {karakter!r}"
