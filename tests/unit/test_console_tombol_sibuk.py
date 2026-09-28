"""Tombol yang memanggil server dikunci selama prosesnya jalan (permintaan 2026-09-26).

Dua lapis:

- `denganSibuk()` dijalankan sungguhan lewat node: klik kedua di tengah proses
  tidak menjalankan pekerjaan kedua, spinner (kelas `sibuk`) hilang lagi sesudah
  sukses maupun gagal, dan status `disabled` bawaan tombol tidak disentuh. Layar
  sendiri yang mengatur kapan tombol boleh ditekan (misalnya "Sebelumnya" di
  halaman pertama); helper yang memulihkan `disabled` akan menimpanya.
- Penjaga struktur: setiap panggilan yang mengubah data di server
  (`method: "POST"`) ada di dalam handler yang memakai `denganSibuk` atau
  penjaga khusus miliknya sendiri (scan, login, uji PLC, kartu line, rekam).
  Handler baru tanpa kunci membuat test ini merah.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()
NODE = shutil.which("node")
butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")

#: Penanda kunci yang sah di sebuah handler. `denganSibuk(` untuk semua tombol;
#: sisanya penjaga lama yang sudah terbukti: kolom scan (bukan tombol, dibaca
#: scanner), gerbang login, dialog uji PLC yang mengosongkan `ujiUntuk`.
PENANDA_KUNCI = ("denganSibuk(", 'classList.add("sibuk")', "scanSibuk", "gerbangSibuk", "ujiUntuk")


def _fungsi_async(nama: str) -> str:
    awal = HTML.index(f"async function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


@butuh_node
def test_dengan_sibuk_mengunci_selama_proses_dan_melepas_sesudahnya():
    skrip = _fungsi_async("denganSibuk") + """
class Kelas { constructor() { this.s = new Set(); } add(c) { this.s.add(c); }
  remove(c) { this.s.delete(c); } contains(c) { return this.s.has(c); } }
const tombol = { classList: new Kelas(), atribut: {}, disabled: true,
  setAttribute(k, v) { this.atribut[k] = v; }, removeAttribute(k) { delete this.atribut[k]; } };
(async () => {
  let jalan = 0, lepas;
  const kerja = () => { jalan++; return new Promise((r) => { lepas = r; }); };
  const p1 = denganSibuk(tombol, kerja);
  const selama = tombol.classList.contains("sibuk") && tombol.atribut["aria-busy"] === "true";
  const p2 = denganSibuk(tombol, kerja);
  lepas("ok");
  const [h1, h2] = await Promise.all([p1, p2]);
  const sesudah = tombol.classList.contains("sibuk");
  let galat = null;
  try { await denganSibuk(tombol, async () => { throw new Error("gagal"); }); } catch (e) { galat = e.message; }
  console.log(JSON.stringify({ jalan, selama, h1, h2: h2 === undefined ? null : h2, sesudah, galat,
    bersih: !tombol.classList.contains("sibuk") && !("aria-busy" in tombol.atribut),
    disabled: tombol.disabled }));
})();
"""
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-600:]
    assert json.loads(hasil.stdout) == {
        "jalan": 1, "selama": True, "h1": "ok", "h2": None, "sesudah": False,
        "galat": "gagal", "bersih": True, "disabled": True,
    }


def test_setiap_panggilan_yang_mengubah_data_ada_di_handler_terkunci():
    baris = HTML.split("\n")
    lolos = []
    for i, isi in enumerate(baris):
        if not re.search(r'method:\s*"(POST|PUT|PATCH|DELETE)"', isi):
            continue
        j = i
        while j > 0 and not re.search(r"(addEventListener\(|^\s*(async )?function )", baris[j]):
            j -= 1
        blok = "\n".join(baris[j : i + 1])
        if not any(p in blok for p in PENANDA_KUNCI):
            lolos.append(f"baris {i + 1}: {baris[j].strip()[:80]}")
    assert not lolos, lolos


def test_spinner_sibuk_menolak_klik_dan_berputar():
    aturan = re.search(r"button\.sibuk\s*\{([^}]*)\}", HTML).group(1).replace(" ", "")
    assert "pointer-events:none" in aturan
    putar = re.search(r"button\.sibuk::before\s*\{([^}]*)\}", HTML).group(1)
    assert "animation" in putar


def test_badge_pintas_di_tengah_vertikal():
    """Badge SPASI+1 sejajar tengah dengan tulisan tombolnya (2026-09-26)."""
    tombol = re.search(r"\.aksi-line\s*>\s*button\s*\{([^}]*)\}", HTML).group(1).replace(" ", "")
    assert "display:flex" in tombol and "align-items:center" in tombol
