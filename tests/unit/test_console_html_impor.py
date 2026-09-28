"""Layar impor CSV di tab Riwayat (support saja, 2026-09-27).

- Tombol dan dialognya `data-dev="1"`: dibuang dari halaman untuk akun non-support.
  Yang menjaga tetap server (403, tests/e2e/test_impor_grading_lane.py).
- Tiap kode salah per baris diterjemahkan di kedua bahasa, supaya support membaca
  kalimat, bukan kode.
- Hasil Periksa, daftar impor, dan label "impor" di baris Riwayat digambar lewat node.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from palmgrade.domain.impor_grading import KODE_SALAH_BARIS

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()
NODE = shutil.which("node")
butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada (image CI)")

_STUB = """
const esc = (s) => String(s ?? "").replace(/[&<>"'`]/g, (c) =>
  ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;","`":"&#96;" }[c]));
const KOSONG = "-";
const lokal = () => "id-ID";
const bahasa = "id";
const KAMUS = { id: %s };
const t = (k) => KAMUS.id[k] ?? k;
const waktu = (iso) => "WAKTU(" + iso + ")";
"""


def _kamus(nama: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {nama}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


def _fungsi(nama: str) -> str:
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _node(ekspresi: str):
    kamus_id = "{" + _kamus("id") + "}"
    skrip = (_STUB % kamus_id) + "\n".join(
        _fungsi(n) for n in ("pesanSalahImpor", "rentangImpor", "ringkasImpor", "barisImpor")
    ) + f"\nconsole.log(JSON.stringify({ekspresi}));"
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout)


def test_tombol_dan_dialog_impor_khusus_support():
    tombol = re.search(r'<button[^>]*id="riwayat-impor"[^>]*>', HTML).group(0)
    dialog = re.search(r'<dialog id="impor-modal"[^>]*>', HTML).group(0)

    assert 'data-dev="1"' in tombol and 'data-dev="1"' in dialog
    # Unduh CSV tetap untuk semua operator.
    assert 'data-dev' not in re.search(r'<button[^>]*id="riwayat-csv"[^>]*>', HTML).group(0)


def test_semua_kode_salah_baris_dan_status_diterjemahkan_di_dua_bahasa():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        hilang = [k for k in KODE_SALAH_BARIS if f"imporSalah_{k}:" not in isi]
        assert not hilang, f"{bahasa}: {hilang}"
        for status in ("done", "interrupted", "undone", "running"):
            assert f"imporStatus_{status}:" in isi, (bahasa, status)


def test_berkas_dikirim_mentah_dan_impor_membawa_sidik_hasil_periksa():
    periksa, jalankan = _fungsi("periksaImpor"), _fungsi("jalankanImpor")

    assert '"content-type": "text/csv"' in periksa and "body: berkas" in periksa
    assert "sidik=${encodeURIComponent(imporSidik)}" in jalankan and "body: imporBerkas" in jalankan
    # Memilih berkas lain membatalkan hasil periksa sebelumnya.
    assert '$("impor-berkas").addEventListener("change", bersihkanPeriksaImpor)' in HTML


def test_batal_butuh_dua_klik():
    batal = _fungsi("batalkanImpor")

    assert batal.index('classList.contains("yakin")') < batal.index('method: "POST"')


@butuh_node
def test_hasil_periksa_menulis_angka_rentang_line_dan_baris_salah():
    p = {
        "baris": 1250, "baru": 1200, "sudah_ada": 40, "hari_berjalan": 6, "ganda": 0, "salah": 4,
        "contoh_salah": [{"nomor": 12, "kode": "hasil_tidak_sah", "params": {"nilai": "<b>OK</b>"}}],
        "dari": "2026-09-20", "sampai": "2026-09-24", "truk_baru_jumlah": 3, "bisa_impor": False,
        "per_line": [{"line_code": "line-1", "jumlah": 700, "dikenal": True},
                     {"line_code": "line-9", "jumlah": 500, "dikenal": False}],
    }

    html = _node(f"ringkasImpor({json.dumps(p)})")

    assert "1.250" in html and "1.200" in html
    assert "Ganda" not in html                     # nol dan tidak penting: tidak ditulis
    assert "2026-09-20 s.d. 2026-09-24" in html
    assert "line-9 500 (tidak dikenal di konsol ini)" in html
    assert "Baris 12: Hasil &lt;b&gt;OK&lt;/b&gt; harus ACC atau REJ" in html
    assert "Impor ditolak selama ada baris salah" in html


@butuh_node
def test_daftar_impor_batal_cuma_untuk_yang_selesai_atau_terputus():
    dasar = {"file_name": "a.csv", "imported_by": "support@pks.id", "started_at": 1_790_500_000,
             "added": 12, "date_from": "2026-09-24", "date_to": "2026-09-24"}
    baris = _node("[" + ",".join(
        f"barisImpor({json.dumps({**dasar, 'id': s, 'status': s, 'undone_by': 'x@pks.id'})})"
        for s in ("done", "interrupted", "undone", "running")
    ) + "]")

    assert ['data-batal="' in b for b in baris] == [True, True, False, False]
    assert '<span class="pill">Dibatalkan</span><span class="muted">oleh x@pks.id</span>' in baris[2]
    assert "12 janjang · 2026-09-24" in baris[0]


@butuh_node
def test_nama_berkas_dan_pengimpor_di_escape():
    b = _node('barisImpor({id: "x\\" onclick=\\"y", status: "done", file_name: "<img src=x>", '
              'imported_by: "<b>", added: 1, date_from: null})')

    assert "<img" not in b and 'onclick="y"' not in b
    assert "&lt;img src=x&gt;" in b and "&lt;b&gt;" in b


def test_baris_riwayat_hasil_impor_diberi_label():
    baris = _fungsi("barisRiwayatJanjang")

    assert "r.import_batch" in baris and 'class="label-impor"' in baris
