"""Setiap `<script>` di `console.html` harus bisa diparse browser, bukan cuma fungsi yang diuji.

Test konsol yang lain menyalin SATU fungsi (`konsol_js.fungsi`) lalu menjalankannya di node.
Syntax error di luar fungsi itu (konstanta, `KAMUS`, listener tingkat atas) tidak dibaca
siapa pun: semua test hijau, tapi browser menolak seluruh skrip dan layar operator kosong
(rencana perbaikan, batch 4.3). Berkas ini menyerahkan tiap blok utuh ke node.

Skrip klasik diparse lewat `vm.Script`, tata bahasa yang sama dengan browser. `node --check`
tidak dipakai untuknya: ia membaca berkas sebagai CommonJS (badan fungsi), jadi `return` di
tingkat atas lolos di sana padahal browser menolaknya ("Illegal return statement").
`<script type="module">` memang modul, jadi yang itu diperiksa `node --check` atas `.mjs`.

Dipakai dua cara: langkah CI `python tests/cek_skrip_konsol.py src/palmgrade/static/console.html`
dan diimpor `tests/unit/test_cek_skrip_konsol.py`.

Kode keluar: 0 semua blok lolos, 1 ada blok rusak, 2 pemeriksaan tidak bisa dijalankan
(berkas tidak ada, node tidak ada, nol blok JavaScript). Kode 2 sengaja GAGAL, bukan lolos:
pemeriksa yang diam-diam tidak memeriksa apa pun adalah kegagalan yang dicegah berkas ini.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

LOLOS = 0
RUSAK = 1
TIDAK_BISA_DIPERIKSA = 2

BATAS_WAKTU_NODE_S = 60

_TIPE_KLASIK = frozenset(
    {"", "text/javascript", "application/javascript", "text/ecmascript", "application/ecmascript"}
)
_TIPE_MODUL = "module"

# Mem-parse tanpa menjalankan. Galatnya dicetak `<berkas>:<baris>` di baris pertama,
# bentuk yang sama dengan `node --check`, jadi satu pembaca untuk dua jalur.
_PARSE_SKRIP_KLASIK = (
    'const vm = require("vm");'
    'const berkas = process.argv[1];'
    "try {"
    '  new vm.Script(require("fs").readFileSync(berkas, "utf8"), { filename: berkas });'
    "} catch (galat) {"
    "  process.stderr.write(String(galat.stack));"
    "  process.exit(1);"
    "}"
)
_LETAK_GALAT = re.compile(r":(\d+)\s*$")
_BARIS_JENIS_GALAT = re.compile(r"^\w*Error\b")


@dataclass(frozen=True)
class BlokSkrip:
    """Satu `<script>` berisi JavaScript. `nomor` dihitung dari SEMUA tag `<script>`
    di berkas (mulai 1), termasuk yang dilewati, supaya cocok dengan yang dilihat orang."""

    nomor: int
    baris_tag: int
    baris_isi: int
    modul: bool
    isi: str

    def baris_html(self, baris_blok: int) -> int:
        """Baris 1 blok adalah sisa baris tempat `>` penutup tag `<script>` berada."""
        return self.baris_isi + baris_blok - 1


class _PengumpulSkrip(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.blok: list[BlokSkrip] = []
        self._nomor = 0
        self._di_skrip = False
        self._dibuka: tuple[int, int, bool] | None = None
        self._potongan: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        self._nomor += 1
        self._di_skrip = True
        self._potongan = []
        atribut = {nama: (nilai or "") for nama, nilai in attrs}
        tipe = atribut.get("type", "").strip().lower()
        javascript = "src" not in atribut and (tipe in _TIPE_KLASIK or tipe == _TIPE_MODUL)
        baris_tag = self.getpos()[0]
        baris_isi = baris_tag + (self.get_starttag_text() or "").count("\n")
        self._dibuka = (baris_tag, baris_isi, tipe == _TIPE_MODUL) if javascript else None

    def handle_data(self, data: str) -> None:
        if self._di_skrip:
            self._potongan.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "script" or not self._di_skrip:
            return
        if self._dibuka is not None:
            baris_tag, baris_isi, modul = self._dibuka
            self.blok.append(BlokSkrip(self._nomor, baris_tag, baris_isi, modul, "".join(self._potongan)))
        self._di_skrip = False
        self._dibuka = None


def blok_js(html: str) -> list[BlokSkrip]:
    """Semua blok `<script>` yang dijalankan browser sebagai JavaScript, urut berkas.

    Dilewati: `src=` (isinya diabaikan browser) dan `type` bukan JavaScript
    (`application/json`, template)."""
    pengumpul = _PengumpulSkrip()
    pengumpul.feed(html)
    pengumpul.close()
    return pengumpul.blok


def _perintah_parse(node: str, berkas: Path, modul: bool) -> list[str]:
    if modul:
        return [node, "--check", str(berkas)]
    return [node, "-e", _PARSE_SKRIP_KLASIK, str(berkas)]


def _pesan_rusak(blok: BlokSkrip, keluaran: str) -> str:
    baris = [b.strip() for b in keluaran.strip().splitlines()]
    letak = _LETAK_GALAT.search(baris[0]) if baris else None
    jenis = next((b for b in baris if _BARIS_JENIS_GALAT.match(b)), keluaran.strip()[-300:])
    di_mana = f"baris HTML {blok.baris_html(int(letak.group(1)))}" if letak else "baris tidak diketahui"
    return f"blok <script> #{blok.nomor} (tag di baris {blok.baris_tag}): {jenis}, di {di_mana}"


def periksa_blok(blok: BlokSkrip, node: str, folder: Path) -> str | None:
    """None kalau blok bisa diparse; kalau tidak, satu kalimat: blok ke berapa, galatnya,
    dan baris HTML-nya."""
    berkas = folder / f"blok-{blok.nomor}.{'mjs' if blok.modul else 'js'}"
    berkas.write_text(blok.isi, encoding="utf-8")
    hasil = subprocess.run(
        _perintah_parse(node, berkas, blok.modul),
        capture_output=True,
        text=True,
        timeout=BATAS_WAKTU_NODE_S,
        env={**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0"},
    )
    if hasil.returncode == 0:
        return None
    return _pesan_rusak(blok, hasil.stderr)


def periksa_semua(blok: list[BlokSkrip], node: str) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="cek-skrip-konsol-") as folder:
        hasil = (periksa_blok(b, node, Path(folder)) for b in blok)
        return [pesan for pesan in hasil if pesan is not None]


def _gagal(pesan: str) -> int:
    print(f"GAGAL: {pesan}", file=sys.stderr)
    return TIDAK_BISA_DIPERIKSA


def main(argv: list[str] | None = None) -> int:
    argumen = sys.argv[1:] if argv is None else argv
    if len(argumen) != 1:
        return _gagal("pemakaian: python tests/cek_skrip_konsol.py <berkas.html>")
    berkas = Path(argumen[0])
    if not berkas.is_file():
        return _gagal(f"{berkas} tidak ada")
    node = shutil.which("node")
    if node is None:
        return _gagal("node tidak ada di PATH; pemeriksaan ini tidak boleh dilewati diam-diam")
    semua = blok_js(berkas.read_text(encoding="utf-8"))
    if not semua:
        return _gagal(f"nol blok <script> JavaScript di {berkas}; tidak ada yang diperiksa")
    rusak = periksa_semua(semua, node)
    for pesan in rusak:
        print(f"RUSAK: {berkas.name} {pesan}", file=sys.stderr)
    if rusak:
        return RUSAK
    print(f"OK: {len(semua)} blok <script> di {berkas} bisa diparse")
    return LOLOS


if __name__ == "__main__":
    sys.exit(main())
