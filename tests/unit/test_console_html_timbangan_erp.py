"""Tanda jawaban AutoERP di baris tab Timbangan (batch 2.3).

Tiket final tidak pernah ditulis ulang AutoERP, jadi janjang susulan yang datang
sesudahnya hanya bisa DITANDAI di layar, bukan dibetulkan. Kata dan warna berdua
(`tag no`), seperti tanda lain di konsol.
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
butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada (image CI)")
KUNCI = ("erpFinalBeda", "erpFinalBedaJudul", "erpBatal", "erpBatalJudul")

_STUB = """
const esc = (s) => String(s ?? "").replace(/[&<>"'`]/g, (c) =>
  ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;","`":"&#96;" }[c]));
const KOSONG = "-";
const t = (k) => ({erpFinalBeda: "CEK", erpFinalBedaJudul: "Tiket {tiket} final",
                   erpBatal: "BATAL", erpBatalJudul: "Tiket {tiket} batal"}[k] || k);
"""


def _fungsi(nama: str) -> str:
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


def _tanda(baris: dict) -> str:
    skrip = _STUB + _fungsi("tandaErp") + f"\nconsole.log(JSON.stringify(tandaErp({json.dumps(baris)})));"
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout)


@butuh_node
def test_tanpa_kode_tidak_ada_tanda():
    assert _tanda({"erp_perlu_dicek": None, "erp_ticket": "WB-7"}) == ""


@butuh_node
def test_tiket_final_berbeda_bertanda_dengan_nomor_tiketnya():
    tanda = _tanda({"erp_perlu_dicek": "tiket_final_berbeda", "erp_ticket": "WB-7"})

    assert 'class="tag no"' in tanda and ">CEK<" in tanda
    assert 'title="Tiket WB-7 final"' in tanda


@butuh_node
def test_tiket_batal_bertanda_sendiri():
    assert ">BATAL<" in _tanda({"erp_perlu_dicek": "tiket_dibatalkan", "erp_ticket": "WB-8"})


@butuh_node
def test_nomor_tiket_di_escape_dan_kode_asing_diabaikan():
    assert "&lt;b&gt;" in _tanda({"erp_perlu_dicek": "tiket_dibatalkan", "erp_ticket": "<b>"})
    assert _tanda({"erp_perlu_dicek": "kode_dari_versi_lain"}) == ""


def test_tanda_ada_di_sel_plat_baris_timbangan():
    assert "${dash(w.plate_number)}${tandaErp(w)}" in _fungsi("barisTimbangan")


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_kata_ada_di_dua_bahasa(bahasa):
    isi = _kamus(bahasa)
    for kunci in KUNCI:
        assert f"{kunci}:" in isi, f"{bahasa}: {kunci}"
