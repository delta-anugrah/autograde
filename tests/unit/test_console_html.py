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


def _kamus(bahasa: str) -> str:
    """The body of one language block inside `const KAMUS = {...}`."""
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    blok = re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M)
    assert blok, f"blok bahasa {bahasa!r} tidak ditemukan"
    return blok.group(1)


def test_setiap_kode_error_operator_diterjemahkan_di_kedua_bahasa():
    from palmgrade.domain.operator_error import CODES

    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        hilang = [c for c in CODES if f"err_{c}:" not in isi]
        assert not hilang, f"KAMUS.{bahasa} belum menerjemahkan {hilang}"


def test_pesan_error_dirangkai_di_layar_bukan_ditempel_dari_server():
    # `+ e.message` glues a server sentence onto a translated prefix.
    assert '+ e.message' not in HTML, "pakai alasan(e), bukan e.message mentah"
