"""Atribut `hidden` harus benar-benar menyembunyikan.

Halaman ini TIDAK punya aturan global `[hidden] { display:none }`. Aturan `display`
milik sebuah kelas atau id (grid, flex, block) mengalahkan `[hidden]` bawaan
browser, jadi elemen yang "disembunyikan" tetap tampil tanpa satu pun galat.
Ketemu di browser 2026-09-26: form Tambah akun tidak bisa ditutup, dan pager tab
Riwayat tampil di tampilan Per hari. Keduanya lolos semua test teks.

Penjaga: tiap elemen statis ber-`hidden` yang kena aturan `display` selain `none`
wajib punya aturan `<selector>[hidden] { display:none }` untuk selector yang sama.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()


class _Tersembunyi(HTMLParser):
    """Id dan kelas setiap elemen yang ditulis dengan atribut `hidden`."""

    def __init__(self) -> None:
        super().__init__()
        self.elemen: list[tuple[str, str | None, list[str]]] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "hidden" in a:
            self.elemen.append((tag, a.get("id"), (a.get("class") or "").split()))


def _tanpa_blok_cetak(css: str) -> str:
    """Buang `@media print { ... }`: di sana `display` memang sengaja dipaksa
    (kartu QR yang dicetak dari tab Truk), bukan tampilan layar."""
    while (awal := css.find("@media print")) != -1:
        buka = css.index("{", awal)
        dalam, i = 1, buka + 1
        while dalam:
            dalam += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        css = css[:awal] + css[i:]
    return css


def _aturan() -> list[tuple[str, str]]:
    """(selector tunggal, isi aturan) dari semua blok <style> layar, tanpa komentar."""
    css = "\n".join(re.findall(r"<style>(.*?)</style>", HTML, re.S))
    css = _tanpa_blok_cetak(re.sub(r"/\*.*?\*/", "", css, flags=re.S))
    hasil = []
    for selektor, isi in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        for satu in selektor.split(","):
            hasil.append((" ".join(satu.split()), isi.replace(" ", "")))
    return hasil


def test_elemen_hidden_tidak_dikalahkan_aturan_display():
    aturan = _aturan()
    tampil = {sel for sel, isi in aturan if re.search(r"display:(?!none)", isi)}
    sembunyi = {sel for sel, isi in aturan if "display:none" in isi}
    parser = _Tersembunyi()
    parser.feed(HTML)
    bocor = []
    for tag, id_, kelas in parser.elemen:
        calon = ([f"#{id_}"] if id_ else []) + [f".{k}" for k in kelas] + [f"{tag}.{k}" for k in kelas]
        penentu = [c for c in calon if c in tampil]
        if penentu and not any(f"{c}[hidden]" in sembunyi for c in calon):
            bocor.append((id_ or kelas, penentu))
    assert not bocor, f"elemen hidden yang tetap tampil (tambahkan <selector>[hidden]): {bocor}"
