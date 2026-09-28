"""Bagian Last Sync di strip "Hari ini": AutoERP dan Cloud Photo (2026-09-27).

Satu bagian, dua baris (permintaan user). Tiap baris: titik warna + nama + jam
sinkron terakhir; saat putus, keterangan "Terputus sejak 13:40 · 5 menunggu".
Kata dan warna selalu berdua: layar dibaca lewat AnyDesk dan sebagian teknisi
buta warna. Dibaca semua operator, bukan cuma support.
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
const t = (k) => ({sinkronTerputus: "TERPUTUS {jam}", sinkronMenunggu: "{n} MENUNGGU"}[k] || k);
const lokal = () => "id-ID";
"""


def _fungsi(nama: str) -> str:
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


def _node(ekspresi: str):
    fungsi = "\n".join(_fungsi(n) for n in ("jamSinkron", "barisSinkron", "judulSinkron"))
    skrip = _STUB + fungsi + f"\nconsole.log(JSON.stringify({ekspresi}));"
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout)


def test_satu_bagian_last_sync_berisi_dua_baris_di_strip_hari_ini():
    tally = HTML.split('<section id="tally">', 1)[1].split("</section>", 1)[0]
    bagian = re.search(r'<div class="sinkron"[^>]*>(.*?)\n  </div>', tally, re.S)
    assert bagian, "bagian Last Sync tidak ada di strip Hari ini"
    isi = bagian.group(1)
    assert 'data-t="lastSync"' in isi
    assert re.findall(r'id="(sinkron-[a-z]+)"', isi) == ["sinkron-erp", "sinkron-cloud"]


def test_diisi_dari_polling_state_yang_sudah_ada():
    assert "isiSinkron(s.sinkron)" in _fungsi("refresh")


def test_nama_dan_teks_di_dua_bahasa():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        assert 'lastSync:"Last Sync"' in isi, bahasa
        assert 'sinkronErp:"AutoERP"' in isi, bahasa
        assert 'sinkronCloud:"Cloud Photo"' in isi, bahasa
        for kunci in ("sinkronTersambung", "sinkronTerputus", "sinkronMenunggu", "sinkronTidakDipakai",
                      "sinkronMemeriksa", "sinkronBelum", "sinkronTakTerbaca", "sinkronTerakhir"):
            assert f"{kunci}:" in isi, f"{bahasa}: {kunci}"


def test_warna_titik_dari_keadaan_bukan_dari_umur_jam():
    for keadaan, warna in (("tersambung", "--acc"), ("terputus", "--warn")):
        aturan = re.search(rf"\.sinkron-baris\.{keadaan} \.titik\s*\{{([^}}]*)\}}", HTML)
        assert aturan and warna in aturan.group(1), keadaan


# ── render lewat node ────────────────────────────────────────────────────

_SEKARANG = "Date.UTC(2026, 8, 27, 7, 30) / 1000"  # 27 Sep 2026


@butuh_node
def test_jam_hari_ini_cuma_jam_hari_lain_dengan_tanggal():
    hasil = _node(f"[jamSinkron({_SEKARANG} - 600, {_SEKARANG}), jamSinkron({_SEKARANG} - 86400 * 2, {_SEKARANG}), jamSinkron(null, {_SEKARANG})]")

    assert re.fullmatch(r"\d{2}[.:]\d{2}", hasil[0]), hasil[0]
    assert re.search(r"\d{1,2}\s\w+", hasil[1]) and re.search(r"\d{2}[.:]\d{2}", hasil[1]), hasil[1]
    assert hasil[2] is None


@butuh_node
def test_baris_tersambung_menulis_jam_terakhir():
    r = _node(f'barisSinkron({{keadaan: "tersambung", terakhir: {_SEKARANG} - 300, sejak: null, antre: 0}}, {_SEKARANG})')

    assert r["kelas"] == "tersambung"
    assert re.fullmatch(r"\d{2}[.:]\d{2}", r["jam"])
    assert r["ket"] == ""


@butuh_node
def test_baris_terputus_menulis_sejak_dan_yang_menunggu():
    r = _node(f'barisSinkron({{keadaan: "terputus", terakhir: {_SEKARANG} - 3600, sejak: {_SEKARANG} - 1200, antre: 5}}, {_SEKARANG})')

    assert r["kelas"] == "terputus"
    assert r["ket"].startswith("TERPUTUS ") and "5 MENUNGGU" in r["ket"]


@butuh_node
def test_baris_tidak_dipakai_dan_belum_pernah():
    mati = _node(f'barisSinkron({{keadaan: "tidak_dipakai", terakhir: null, sejak: null, antre: 0}}, {_SEKARANG})')
    baru = _node(f'barisSinkron({{keadaan: "memeriksa", terakhir: null, sejak: null, antre: 0}}, {_SEKARANG})')

    assert (mati["kelas"], mati["jam"]) == ("tidak_dipakai", "sinkronTidakDipakai")
    # "-" di baris, bukan "Belum pernah" (umpan balik 2026-09-28); kalimatnya tetap di tooltip.
    assert (baru["kelas"], baru["jam"]) == ("memeriksa", "-")


@butuh_node
def test_tersambung_tanpa_jam_juga_strip():
    r = _node(f'barisSinkron({{keadaan: "tersambung", terakhir: null, sejak: null, antre: 0}}, {_SEKARANG})')

    assert r["jam"] == "-"


def test_last_sync_dipisah_garis_dari_neto_timbangan():
    aturan = re.search(r"#tally \.sinkron\s*\{([^}]*)\}", HTML)
    assert aturan and "border-left" in aturan.group(1)


@butuh_node
def test_keadaan_asing_dari_server_tidak_jadi_kelas_css():
    r = _node(f'barisSinkron({{keadaan: "x\\" onclick=\\"y", terakhir: null, sejak: null, antre: 0}}, {_SEKARANG})')

    assert r["kelas"] == "memeriksa"


@butuh_node
def test_keterangan_arahkan_kursor_menyebut_keadaan_tiap_line():
    """Cloud Photo merah karena SATU line: tooltip harus menunjuk line yang mana.
    Line yang putus ditulis "terputus sejak", line tanpa R2 "tidak dipakai", bukan
    "belum" yang terbaca seolah line itu belum sempat mengunggah."""
    judul = _node(
        f"(() => {{ const S = {_SEKARANG}; return judulSinkron({{keadaan: 'terputus', terakhir: S - 3600,"
        " sejak: S - 1200, antre: 5, per_line: ["
        "{line_code: 'line-1', terbaca: true, aktif: true, terakhir: S - 300, sejak: null, antre: 0},"
        "{line_code: 'line-2', terbaca: true, aktif: true, terakhir: null, sejak: S - 1200, antre: 5},"
        "{line_code: 'line-3', terbaca: true, aktif: false, terakhir: null, sejak: null, antre: 0},"
        "{line_code: 'line-4', terbaca: false}]}, S); })()"
    ).split("\n")

    line = {b.split(":", 1)[0]: b.split(":", 1)[1].strip() for b in judul if b.startswith("line-")}
    assert re.fullmatch(r"\d{2}[.:]\d{2}", line["line-1"]), line["line-1"]
    assert line["line-2"].startswith("TERPUTUS ") and line["line-2"].endswith("5 MENUNGGU"), line["line-2"]
    assert line["line-3"] == "sinkronTidakDipakai"
    assert line["line-4"] == "sinkronTakTerbaca"
