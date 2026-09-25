"""Kotak `.tools`: kepala tabel, bukan wadah tombol yang berdiri sendiri.

`.tools` bergaya kartu putih berbingkai TANPA garis bawah dan bersudut atas saja,
karena dirancang menempel ke `.tabel` di bawahnya (`.tools + .tabel` menyambung
keduanya jadi satu kartu). Dipakai tanpa tabel, kotaknya menggantung dengan bawah
terbuka — terlihat rusak di Sumber Kamera, Model Deteksi, Rekam Video, Setelan,
dan kepala Manifest R2 yang terlepas dari tabelnya (keluhan user 2026-09-25).

Dijaga di struktur HTML, bukan di mata: tiap `.tools` biasa harus langsung
diikuti `.tabel`, dan bar simpan yang berdiri sendiri memakai `.tools.lepas`
(tanpa kotak, tombol simpan selebar panel).
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HTML = (REPO_ROOT / "src" / "palmgrade" / "static" / "console.html").read_text(encoding="utf-8")

_VOID = {"input", "br", "img", "meta", "link", "hr", "source", "wbr"}


class _Simpul:
    def __init__(self, tag: str, attrs: list, induk: _Simpul | None) -> None:
        self.tag = tag
        self.attrs = dict(attrs)
        self.induk = induk
        self.anak: list[_Simpul] = []

    @property
    def kelas(self) -> list[str]:
        return (self.attrs.get("class") or "").split()


class _Pohon(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.akar = _Simpul("root", [], None)
        self._kini = self.akar

    def handle_starttag(self, tag, attrs):
        simpul = _Simpul(tag, attrs, self._kini)
        self._kini.anak.append(simpul)
        if tag not in _VOID:
            self._kini = simpul

    def handle_endtag(self, tag):
        k = self._kini
        while k is not None and k.tag != tag:
            k = k.induk
        if k is not None and k.induk is not None:
            self._kini = k.induk


def _pohon() -> _Simpul:
    p = _Pohon()
    p.feed(HTML)
    return p.akar


def _semua(simpul: _Simpul):
    for anak in simpul.anak:
        yield anak
        yield from _semua(anak)


def _di_dalam_dialog(simpul: _Simpul) -> bool:
    k = simpul.induk
    while k is not None:
        if k.tag == "dialog":
            return True
        k = k.induk
    return False


def _aturan_css(selector: str) -> str:
    awal = HTML.find(selector + " {")
    assert awal != -1, f"aturan CSS `{selector}` tidak ada"
    return HTML[awal : HTML.find("}", awal)]


def test_kotak_tools_selalu_menempel_ke_tabel():
    """Kotak `.tools` biasa tanpa `.tabel` tepat sesudahnya = kotak menggantung."""
    lepas = []
    for simpul in _semua(_pohon()):
        if simpul.tag != "div" or "tools" not in simpul.kelas:
            continue
        if "lepas" in simpul.kelas or _di_dalam_dialog(simpul):
            continue
        saudara = simpul.induk.anak
        berikut = saudara[saudara.index(simpul) + 1] if simpul is not saudara[-1] else None
        if berikut is None or berikut.tag != "div" or "tabel" not in berikut.kelas:
            isi = [a.attrs.get("id") for a in simpul.anak if a.attrs.get("id")]
            lepas.append((isi, berikut.tag if berikut else None, berikut and berikut.attrs.get("id")))
    assert not lepas, f"kotak .tools tidak menempel ke tabel: {lepas}"


@pytest.mark.parametrize("tombol", ["sumber-simpan", "model-simpan", "rekam-simpan", "set-simpan"])
def test_bar_simpan_mandiri_memakai_tools_lepas(tombol):
    simpul = next(s for s in _semua(_pohon()) if s.attrs.get("id") == tombol)
    assert "utama" in simpul.kelas, f"{tombol} bukan tombol utama"
    assert "tools" in simpul.induk.kelas and "lepas" in simpul.induk.kelas, (
        f"{tombol} masih di dalam kotak .tools berbingkai"
    )


def test_tools_lepas_tanpa_kotak_dan_tombolnya_selebar_panel():
    aturan = _aturan_css(".tools.lepas")
    for sifat in ("background:none", "border:0", "border-radius:0"):
        assert sifat in aturan, sifat
    assert "flex:1 1 100%" in _aturan_css(".tools.lepas button.utama")


def test_area_cetak_qr_tetap_anak_langsung_section_truk():
    """Aturan cetak (`#sec-truk > *:not(#qr-cetak)`) butuh #qr-cetak sebagai anak
    LANGSUNG section Truk; memindahkannya supaya kepala tabel menempel tidak
    boleh memutus itu."""
    simpul = next(s for s in _semua(_pohon()) if s.attrs.get("id") == "qr-cetak")
    assert simpul.induk.attrs.get("id") == "sec-truk"
