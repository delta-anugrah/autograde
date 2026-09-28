"""Tab menurut peran akun, tanpa memuat ulang halaman (umpan balik tes staging 2026-09-28).

Dua bug yang ketemu saat berganti akun di satu jendela:

- Operator masuk sesudah support membuka tab support (misalnya Setelan): tab itu
  diingat, lalu dibuang untuk operator, jadi tidak ada tab aktif dan layarnya kosong.
- Support masuk sesudah operator keluar: tab support sudah dibuang dari halaman dan
  tidak pernah kembali sampai halaman dimuat ulang.

Elemen `data-dev="1"` sekarang disimpan bersama tempatnya dan dikembalikan saat akun
support masuk; tab yang tidak ada lagi jatuh ke Grading. Server tetap yang menjaga
(403 untuk non-support), ini cuma kerapian layar.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()
NODE = shutil.which("node")
butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada (image CI)")

# DOM tiruan secukupnya: induk, anak berurutan, remove, insertBefore, querySelector.
_DOM = """
class El {
  constructor(tag, attr = {}, anak = []) {
    this.tag = tag; this.attr = attr; this.children = []; this.parentNode = null;
    anak.forEach((a) => this.appendChild(a));
  }
  appendChild(a) { a.parentNode = this; this.children.push(a); return a; }
  get nextSibling() {
    if (!this.parentNode) return null;
    const s = this.parentNode.children; return s[s.indexOf(this) + 1] || null;
  }
  remove() {
    if (!this.parentNode) return;
    const s = this.parentNode.children; s.splice(s.indexOf(this), 1); this.parentNode = null;
  }
  insertBefore(a, ref) {
    a.parentNode = this;
    if (ref === null) { this.children.push(a); return a; }
    this.children.splice(this.children.indexOf(ref), 0, a); return a;
  }
  semua() { return this.children.flatMap((c) => [c, ...c.semua()]); }
  nama() { return this.attr.id || this.attr["data-tab"] || this.tag; }
}
const el = (tag, attr, anak) => new El(tag, attr, anak);
"""


def _fungsi(nama: str) -> str:
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _pembuka_let(nama: str) -> str:
    awal = HTML.index(f"let {nama} ")
    return HTML[awal : HTML.index("\n", awal)]


def _node(isi: str):
    hasil = subprocess.run([NODE, "-e", _DOM + isi], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout)


@butuh_node
def test_elemen_support_kembali_ke_tempatnya_saat_support_masuk_tanpa_muat_ulang():
    hasil = _node(_pembuka_let("devDisimpan") + "\n" + _fungsi("aturTabDeveloper") + """
const tabs = el("div", {id: "tabs"}, [
  el("button", {"data-tab": "grading"}), el("button", {"data-tab": "riwayat"}),
  el("button", {"data-tab": "log", "data-dev": "1"}), el("button", {"data-tab": "akun", "data-dev": "1"}),
  el("button", {"data-tab": "setelan", "data-dev": "1"})]);
const aksi = el("div", {id: "riwayat-aksi"}, [el("button", {id: "riwayat-csv"}),
  el("button", {id: "riwayat-impor", "data-dev": "1"})]);
const body = el("body", {}, [tabs, aksi, el("section", {id: "sec-log", "data-dev": "1"},
  [el("dialog", {id: "di-dalam", "data-dev": "1"})]), el("dialog", {id: "impor-modal", "data-dev": "1"})]);
globalThis.document = { querySelectorAll: () => body.semua().filter((e) => e.attr["data-dev"] === "1") };
const susunan = () => body.semua().map((e) => e.nama());
const awal = susunan();
aturTabDeveloper("operator");
const operator = susunan();
aturTabDeveloper("operator");
aturTabDeveloper("support");
const support = susunan();
aturTabDeveloper("support");
console.log(JSON.stringify({awal, operator, support, lagi: susunan()}));
""")

    assert "log" not in hasil["operator"] and "impor-modal" not in hasil["operator"]
    assert "riwayat-impor" not in hasil["operator"] and "riwayat-csv" in hasil["operator"]
    assert hasil["support"] == hasil["awal"]
    assert hasil["lagi"] == hasil["awal"]


@butuh_node
def test_role_tidak_terbaca_tetap_membuang_dan_tercatat():
    hasil = _node(_pembuka_let("devDisimpan") + "\n" + _fungsi("aturTabDeveloper") + """
const body = el("body", {}, [el("button", {"data-tab": "log", "data-dev": "1"})]);
globalThis.document = { querySelectorAll: () => body.semua().filter((e) => e.attr["data-dev"] === "1") };
const galat = []; console.error = (m) => galat.push(m);
aturTabDeveloper(undefined);
console.log(JSON.stringify({sisa: body.semua().length, galat: galat.length}));
""")

    assert hasil == {"sisa": 0, "galat": 1}


@butuh_node
def test_tab_yang_hilang_jatuh_ke_grading_bukan_layar_kosong():
    hasil = _node(_fungsi("pastikanTabTersedia") + """
let tab = "setelan";
const disimpan = [];
const simpan = (k, v) => disimpan.push([k, v]);
let diterapkan = 0;
const terapkanTab = () => { diterapkan += 1; };
const ada = new Set(["grading", "riwayat"]);
globalThis.document = { querySelector: (sel) => (ada.has(/data-tab="([^"]+)"/.exec(sel)[1]) ? {} : null) };
pastikanTabTersedia();
const hilang = [tab, disimpan.length, diterapkan];
tab = "riwayat";
pastikanTabTersedia();
console.log(JSON.stringify({hilang, tetap: [tab, disimpan.length, diterapkan]}));
""")

    assert hasil["hilang"] == ["grading", 1, 1]
    assert hasil["tetap"] == ["riwayat", 1, 2]


def test_masuk_dan_cek_sesi_mengatur_tab_lalu_memastikan_ada_yang_aktif():
    for fungsi in ("kirimSandi", "cekSesi"):
        isi = _fungsi(fungsi)
        assert isi.index("aturTabDeveloper(operator.role)") < isi.index("pastikanTabTersedia()"), fungsi
    assert "hapusTabDeveloper" not in HTML
