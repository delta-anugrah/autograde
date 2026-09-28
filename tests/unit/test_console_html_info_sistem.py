"""Versi + lisensi di bawah tulisan AUTOGRADE, untuk semua akun (permintaan 2026-09-28).

Dulu versi dan lisensi cuma ada di tab Versi yang support-only, jadi operator tidak
pernah tahu langganan PC-nya sampai kapan. Sekarang satu baris kecil di header
(`teksInfoSistem`) dan kotak detail saat diklik (`barisInfoSistem`). Datanya sudah
dikirim `/api/console/state` ke semua akun: tanggal, tingkat, nama perusahaan, bukan token.
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

# 30 Sep 2027 dan 29 Nov 2027, jam 05.00 UTC: hari yang sama di zona mana pun di Asia.
AKTIF_SAMPAI = 1822280400
TENGGANG_SAMPAI = 1827464400


def _fungsi(nama: str) -> str:
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    bagian = kamus.split("\n  en: {", 1)
    return bagian[0] if bahasa == "id" else bagian[1]


def _t_id() -> str:
    kunci = (
        "versiDariSource", "infoLisensiSampai", "infoTenggangSampai", "infoLisensiHabis",
        "infoTanpaToken", "infoLisensiAktif", "lisensiTokenRusak", "lisensiAktif", "labelVersi", "labelLisensi",
        "labelPerusahaan", "labelAktifSampai", "labelTenggangSampai", "lisensiMati",
        "lisensiSaklarMati", "lisensiTanpaToken", "lisensiSisaHari",
    )
    kamus = _kamus("id")
    pasangan = {}
    for k in kunci:
        m = re.search(rf'\b{k}:"([^"]*)"', kamus)
        assert m, f"KAMUS.id belum punya {k}"
        pasangan[k] = m.group(1)
    return f"const t = (k) => ({json.dumps(pasangan)})[k] ?? k;"


def _node(ekspresi: str):
    fungsi = "\n".join(
        _fungsi(n)
        for n in ("tanggalLisensi", "tanggalPendek", "ringkasLisensi", "barisVersi",
                  "barisLisensi", "teksInfoSistem", "barisInfoSistem")
    )
    kode = (
        _t_id()
        + '\nconst lokal = () => "id-ID";\nconst KOSONG = "-";\n'
        + 'const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => "&#" + c.charCodeAt(0) + ";");\n'
        + fungsi
        + f"\nconsole.log(JSON.stringify({ekspresi}));"
    )
    hasil = subprocess.run([NODE, "-e", kode], capture_output=True, text=True, timeout=30,
                           env={"TZ": "Asia/Jakarta", "PATH": "/usr/bin:/bin"})
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout)


def _lisensi(**ubah) -> dict:
    dasar = {
        "aktif": True, "token_terpasang": True, "status": "VALID", "severity": "none",
        "aktif_sampai": AKTIF_SAMPAI, "tenggang_sampai": TENGGANG_SAMPAI, "sisa_hari": 368,
        "perusahaan": "PT Nexio",
    }
    dasar.update(ubah)
    return dasar


@butuh_node
def test_header_menulis_versi_dan_tanggal_langganan():
    hasil = _node(f"teksInfoSistem('v1.18.0', {json.dumps(_lisensi())})")

    assert hasil == {"teks": "v1.18.0 · Lisensi s/d 30 Sep 2027", "tingkat": "none"}


@butuh_node
def test_header_ikut_tingkat_dari_server_bukan_menghitung_sendiri():
    kasus = {
        "warning": _lisensi(severity="warning", sisa_hari=10),
        "grace": _lisensi(severity="grace", sisa_hari=-5),
        "habis": _lisensi(severity="blocked", sisa_hari=-90),
        "rusak": _lisensi(severity="blocked", aktif_sampai=None, tenggang_sampai=None, sisa_hari=None),
        "tanpa_token": _lisensi(token_terpasang=False, severity="blocked", aktif_sampai=None,
                                tenggang_sampai=None, sisa_hari=None, perusahaan=None),
    }
    hasil = _node("{" + ", ".join(f"{k}: teksInfoSistem('v1.18.0', {json.dumps(v)})"
                                  for k, v in kasus.items()) + "}")

    assert hasil["warning"] == {"teks": "v1.18.0 · Lisensi s/d 30 Sep 2027", "tingkat": "warning"}
    assert hasil["grace"] == {"teks": "v1.18.0 · Tenggang s/d 29 Nov 2027", "tingkat": "grace"}
    assert hasil["habis"] == {"teks": "v1.18.0 · Lisensi habis", "tingkat": "blocked"}
    assert hasil["rusak"] == {"teks": "v1.18.0 · Token tidak terbaca", "tingkat": "blocked"}
    assert hasil["tanpa_token"] == {"teks": "v1.18.0 · Token lisensi belum dipasang", "tingkat": "blocked"}


@butuh_node
def test_header_tanpa_fitur_lisensi_cuma_versi():
    """PC dev atau pabrik tanpa langganan: kata "mati" di header terbaca seperti
    kerusakan. Keterangan lengkapnya tetap ada di kotak detail."""
    hasil = _node(
        "[teksInfoSistem('v1.18.0', " + json.dumps(_lisensi(aktif=False)) + "),"
        " teksInfoSistem('unknown', null), teksInfoSistem(undefined, undefined)]"
    )

    assert hasil == [
        {"teks": "v1.18.0", "tingkat": "none"},
        {"teks": "dev (dari source)", "tingkat": "none"},
        {"teks": "", "tingkat": "none"},
    ]


@butuh_node
def test_kotak_detail_memuat_perusahaan_dan_tanggal_tanpa_token():
    lisensi = _lisensi(nomor_token="RAHASIA-JTI")
    isi = _node(f"barisInfoSistem('v1.18.0', {json.dumps(lisensi)})")

    for ada in ("v1.18.0", "368 hari lagi", "PT Nexio", "30 September 2027", "29 November 2027"):
        assert ada in isi, ada
    assert "RAHASIA" not in isi


def test_tab_versi_dan_kotak_detail_memakai_baris_lisensi_yang_sama():
    assert "barisLisensi(l)" in _fungsi("muatVersi")
    assert "barisLisensi(" in _fungsi("barisInfoSistem")


def test_tombol_header_untuk_semua_akun_dan_ikut_tiap_polling():
    kepala = HTML[HTML.index('<header id="topbar">') : HTML.index("</header>")]
    assert 'id="info-sistem"' in kepala
    tombol = re.search(r'<button[^>]*id="info-sistem"[^>]*>', kepala).group(0)
    assert "data-dev" not in tombol and "hidden" in tombol
    modal = re.search(r'<dialog[^>]*id="info-sistem-modal"[^>]*>', HTML).group(0)
    assert "data-dev" not in modal
    assert "gambarInfoSistem(s.versi, s.lisensi)" in _fungsi("refresh")
    assert "gambarInfoSistem(" in _fungsi("terapkanBahasa")


def test_warna_header_mengikuti_tingkat():
    for tingkat, warna in (("warning", "var(--warn)"), ("grace", "var(--rej)"), ("blocked", "var(--rej)")):
        aturan = re.search(rf'#info-sistem\[data-tingkat="{tingkat}"\]\s*\{{([^}}]*)\}}', HTML)
        assert aturan and warna in aturan.group(1), tingkat


def test_kamus_info_sistem_dua_bahasa():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        for kunci in ("infoLisensiSampai", "infoTenggangSampai", "infoLisensiHabis",
                      "infoTanpaToken", "infoLisensiAktif", "judulInfoSistem"):
            assert f"{kunci}:" in isi, f"KAMUS.{bahasa} belum punya {kunci}"
