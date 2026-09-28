"""Tab konsol digabung dari 15 jadi 9 (permintaan 2026-09-28: "tab kebanyakan").

- Rekap + Riwayat -> **Rekap** (semua operator): dibuka di "Hari ini, per truk", persis
  tab Rekap lama; ganti tanggal = Riwayat. Satu hari di Riwayat sudah dijaga sama
  dengan Rekap (`test_satu_hari_di_riwayat_sama_dengan_tab_rekap`).
- Diagnostik + Antrean ERP + Versi -> **Status** (support): satu layar "sistemnya sehat?".
- Sumber Kamera + Model Deteksi + Uji PLC + Rekam Video -> **Line** (support), dengan
  empat tombol pilihan di dalamnya.

Tab lama yang masih tersimpan di browser dibuka di tempat barunya, bukan jatuh ke Grading.
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

TAB_BARU = ["grading", "truk", "timbangan", "rekap", "log", "status", "akun", "line", "setelan"]
SUB_LINE = ["sumber-kamera", "model-deteksi", "plc", "rekam"]


def _fungsi(nama: str) -> str:
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _nav() -> str:
    return HTML.split('<nav id="tabs">', 1)[1].split("</nav>", 1)[0]


def _panel(nama: str) -> str:
    return HTML.split(f'<section id="sec-{nama}"', 1)[1].split("\n</section>", 1)[0]


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    bagian = kamus.split("\n  en: {", 1)
    return bagian[0] if bahasa == "id" else bagian[1]


def _node(kode: str):
    hasil = subprocess.run([NODE, "-e", kode], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout)


# ── susunan ────────────────────────────────────────────────────────────────


def test_sembilan_tab_urut_dan_empat_untuk_operator():
    tombol = re.findall(r"<button[^>]*data-tab=\"([^\"]+)\"[^>]*>", _nav())
    assert tombol == TAB_BARU
    for baris in _nav().splitlines():
        m = re.search(r'data-tab="([^"]+)"', baris)
        if m:
            dev = 'data-dev="1"' in baris
            assert dev == (m.group(1) not in ("grading", "truk", "timbangan", "rekap")), m.group(1)


def test_panel_lama_tidak_ada_lagi():
    for lama in ("riwayat", "diagnostik", "antrean", "versi", "plc", "sumber-kamera",
                 "model-deteksi", "rekam"):
        assert f'id="sec-{lama}"' not in HTML, lama
        assert f'data-tab="{lama}"' not in HTML, lama


def test_rekap_adalah_riwayat_untuk_semua_operator():
    tag = re.search(r'<section id="sec-rekap"[^>]*>', HTML).group(0)
    assert "data-dev" not in tag
    panel = _panel("rekap")
    for id_ in ("riwayat-dari", "riwayat-sampai", "riwayat-baris"):
        assert f'id="{id_}"' in panel, id_


def test_rekap_lama_dibuang():
    assert "function muatRekap(" not in HTML
    assert "/api/console/recap" not in HTML
    assert "setInterval(muatRekap" not in HTML


def test_status_memuat_versi_diagnostik_dan_antrean_berurutan():
    assert re.search(r'<section id="sec-status"[^>]*data-dev="1"', HTML)
    panel = _panel("status")
    posisi = [panel.index(f'id="{i}"') for i in ("versi-daftar", "diagnostik-kartu",
                                                 "antrean-baris", "manifest-baris")]
    assert posisi == sorted(posisi)
    muat = _fungsi("muatStatus")
    for f in ("muatVersi()", "muatDiagnostik()", "muatAntrean()"):
        assert f in muat, f


def test_line_punya_empat_pilihan_dan_isinya():
    assert re.search(r'<section id="sec-line"[^>]*data-dev="1"', HTML)
    panel = _panel("line")
    assert re.findall(r'data-sub="([^"]+)"', panel) == SUB_LINE
    isi = {"sumber-kamera": "sumber-kamera-panel", "model-deteksi": "model-baris",
           "plc": "plc-kartu", "rekam": "rekam-baris"}
    for sub, id_ in isi.items():
        blok = panel.split(f'<div id="sub-{sub}"', 1)
        assert len(blok) == 2, sub
        assert re.match(r'[^>]*\bhidden\b', blok[1]), f"sub-{sub} harus hidden sampai dipilih"
        assert f'id="{id_}"' in blok[1], sub


def test_muat_tab_dan_tab_sah_memakai_nama_baru():
    tab_sah = re.search(r"const TAB_SAH = \[(.*?)\];", HTML).group(1)
    assert re.findall(r'"([^"]+)"', tab_sah) == TAB_BARU
    sub = re.search(r"const SUB_LINE = \[(.*?)\];", HTML).group(1)
    assert re.findall(r'"([^"]+)"', sub) == SUB_LINE
    muat = re.search(r"const MUAT_TAB = \{(.*?)\};", HTML).group(1)
    for pasangan in ("rekap: muatRiwayat", "status: muatStatus", "line: muatLine"):
        assert pasangan in muat, pasangan


@butuh_node
def test_tab_lama_tersimpan_dibuka_di_tempat_barunya():
    kode = (
        f"const TAB_SAH = {json.dumps(TAB_BARU)};\nconst SUB_LINE = {json.dumps(SUB_LINE)};\n"
        + re.search(r"const TAB_LAMA = \{.*?\};", HTML, re.S).group(0) + "\n"
        + _fungsi("tabDariSimpanan")
        + "\nconsole.log(JSON.stringify(['riwayat','diagnostik','antrean','versi','plc',"
        "'sumber-kamera','model-deteksi','rekam','akun','grading','ngawur'].map(tabDariSimpanan)));"
    )
    assert _node(kode) == [
        {"tab": "rekap", "sub": None}, {"tab": "status", "sub": None},
        {"tab": "status", "sub": None}, {"tab": "status", "sub": None},
        {"tab": "line", "sub": "plc"}, {"tab": "line", "sub": "sumber-kamera"},
        {"tab": "line", "sub": "model-deteksi"}, {"tab": "line", "sub": "rekam"},
        {"tab": "akun", "sub": None}, {"tab": "grading", "sub": None},
        {"tab": "grading", "sub": None},
    ]


@butuh_node
def test_timer_ikut_tab_dan_pilihan_line():
    """Timer cuma jalan untuk layar yang sedang dilihat: diagnostik di Status, PLC dan
    rekam cuma di pilihan Line-nya masing-masing, Rekap segar tiap 15 detik."""
    kode = (
        "const jalan = []; let n = 0;\n"
        "globalThis.setInterval = (f, ms) => { jalan.push(f.name + ':' + ms); return ++n; };\n"
        "globalThis.clearInterval = () => {};\n"
        "let diagnostikTimer, rekamTimer, plcTimer, rekapTimer; let subLine;\n"
        "const MUAT_TAB = {}; const muatDiagnostik = () => {}, muatRekam = () => {},"
        " segarkanPlc = () => {}, segarkanRekap = () => {};\n"
        + _fungsi("bukaTabDev")
        + "\nconst hasil = {};\n"
        "for (const [t, s] of [['status', null], ['line', 'plc'], ['line', 'rekam'],"
        " ['line', 'sumber-kamera'], ['rekap', null], ['grading', null]]) {\n"
        "  jalan.length = 0; subLine = s; bukaTabDev(t); hasil[t + '/' + s] = [...jalan]; }\n"
        "console.log(JSON.stringify(hasil));"
    )
    assert _node(kode) == {
        "status/null": ["muatDiagnostik:5000"],
        "line/plc": ["segarkanPlc:1000"],
        "line/rekam": ["muatRekam:3000"],
        "line/sumber-kamera": [],
        "rekap/null": ["segarkanRekap:15000"],
        "grading/null": [],
    }


def test_pilihan_line_diingat_dan_memuat_ulang():
    klik = HTML.split('$("line-sub").addEventListener("click"', 1)[1].split("\n});", 1)[0]
    assert 'simpan("subLine", subLine)' in klik
    assert 'bukaTabDev("line")' in klik
    assert "MUAT_SUB_LINE[subLine]" in _fungsi("muatLine")
    for sub, fungsi in (("sumber-kamera", "muatSumberKamera"), ("model-deteksi", "muatModelDeteksi"),
                        ("plc", "muatPlc"), ("rekam", "muatRekam")):
        assert f'"{sub}": {fungsi}' in HTML or f"{sub}: {fungsi}" in HTML, sub


def test_pantau_model_berhenti_kalau_pilihan_line_pindah():
    assert 'tab !== "line" || subLine !== "model-deteksi"' in HTML


# ── Rekap: hari ini, per truk, tetap segar ────────────────────────────────


def test_rekap_dibuka_di_hari_ini_per_truk():
    assert re.search(r'^let riwayatTampilan = "truk";', HTML, re.M)
    assert "hariKerja = s.work_date" in _fungsi("refresh")
    assert "riwayatFilter = { dari: hariKerja, sampai: hariKerja }" in _fungsi("muatRiwayat")
    cepat = re.findall(r'data-cepat="([^"]+)"', HTML)
    assert cepat[0] == "hariini"


@butuh_node
def test_tombol_hari_ini_dan_rentangnya():
    kode = (
        _fungsi("tambahHari") + _fungsi("rentangCepat") + _fungsi("cepatAktif")
        + "\nconsole.log(JSON.stringify([rentangCepat('hariini', '2026-09-28'),"
        " cepatAktif('2026-09-28', '2026-09-28', '2026-09-28', null),"
        " cepatAktif('2026-09-01', '2026-09-01', '2026-09-01', 'bulanini'),"
        " cepatAktif('2026-09-01', '2026-09-01', '2026-09-01', null)]));"
    )
    assert _node(kode) == [["2026-09-28", "2026-09-28"], "hariini", "bulanini", "hariini"]


@butuh_node
def test_rekap_hari_ini_segar_sendiri_tanpa_mengganggu_isian():
    """Tab Rekap lama segar tiap 15 detik. Sekarang hanya kalau rentangnya memuat hari ini,
    tabnya sedang dibuka, dan tanggal di kotak belum diubah (yang sedang diketik tidak
    boleh tertimpa)."""
    kode = (
        "let tab, riwayatFilter, riwayatHariIni; let dipanggil = 0; const nilai = {};\n"
        "const $ = (id) => ({ value: nilai[id] });\n"
        "const muatRiwayat = () => { dipanggil += 1; };\n"
        + _fungsi("segarkanRekap")
        + "\nconst hasil = [];\n"
        "function coba(t, f, h, dari, sampai) { tab = t; riwayatFilter = f; riwayatHariIni = h;"
        " nilai['riwayat-dari'] = dari; nilai['riwayat-sampai'] = sampai; dipanggil = 0;"
        " segarkanRekap(); hasil.push(dipanggil); }\n"
        "const hari = { dari: '2026-09-28', sampai: '2026-09-28' };\n"
        "coba('rekap', hari, '2026-09-28', '2026-09-28', '2026-09-28');\n"
        "coba('grading', hari, '2026-09-28', '2026-09-28', '2026-09-28');\n"
        "coba('rekap', { dari: '2026-09-01', sampai: '2026-09-20' }, '2026-09-28', '2026-09-01', '2026-09-20');\n"
        "coba('rekap', hari, '2026-09-28', '2026-09-20', '2026-09-28');\n"
        "coba('rekap', null, '2026-09-28', '', '');\n"
        "console.log(JSON.stringify(hasil));"
    )
    assert _node(kode) == [1, 0, 0, 0, 0]


def test_kamus_tab_baru_dua_bahasa():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        for kunci in ("judulStatus", "judulLine", "riwayatHariIni"):
            assert f"{kunci}:" in isi, f"KAMUS.{bahasa} belum punya {kunci}"
