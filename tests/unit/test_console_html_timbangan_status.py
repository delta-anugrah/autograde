"""Timbangan tab polish (user 2026-10-02, after a manual test of PR #214).

TANPA SCAN 1 in the warning colour, a Status badge per row coloured like its step header,
waiting arrivals as rows at the top and as their own section in step 2's plate picker.
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

_STUB = """
const esc = (s) => String(s ?? "").replace(/[&<>"'`]/g, (c) =>
  ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;","`":"&#96;" }[c]));
const KOSONG = "-";
const dash = (v) => (v === null || v === undefined || v === "" ? KOSONG : esc(v));
const t = (k) => k;
"""


def _fungsi(nama: str) -> str:
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


def _jalankan(ekspresi: str, *fungsi: str, awal: str = ""):
    skrip = _STUB + awal + "".join(_fungsi(f) for f in fungsi) + f"\nprocess.stdout.write(JSON.stringify({ekspresi}));"
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout)


# ── U4: TANPA SCAN 1 in the warning colour ──────────────────────────────


def test_tag_tanpa_scan_1_berwarna_peringatan():
    assert re.search(r'class="tag peringatan"', _fungsi("durasiAntre"))
    aturan = re.search(r"\.tag\.peringatan\s*\{([^}]*)\}", HTML)
    assert aturan, "no .tag.peringatan rule"
    for sifat in ("color:var(--warn)", "background:var(--warn-bg)", "border-color:var(--warn)"):
        assert sifat in aturan.group(1).replace(" ", "")


@butuh_node
def test_tag_tanpa_scan_1_tetap_berkata_bukan_cuma_warna():
    hasil = _jalankan("durasiAntre({tanpa_scan_1:true, antre_menit:null})", "teksMenit", "durasiAntre")
    assert 'class="tag peringatan"' in hasil and ">antreKelewat<" in hasil
