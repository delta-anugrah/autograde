"""Pita frame berhenti di kartu line (3.6) dan pita disk untuk seluruh layar
(3.7), dua lapis seperti `test_console_html_ai_mati.py`: invarian teks (selalu
jalan) dan kalimat sungguhan lewat node dengan KAMUS asli.
"""
from __future__ import annotations

import json
import re

import pytest
from konsol_js import HTML, NODE, fungsi, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")
SEJAK = 1_790_000_000.0          # 21.13 WIB
FUNGSI_PITA = ["jamSinkron", "aiMati", "pitaAi"]
FUNGSI_DISK = ["jamSinkron", "gabungDisk", "pitaDisk"]


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


def _line(ai=None, disk=None, *, nama="Line 2", reachable=True) -> dict:
    return {"line_code": nama.lower().replace(" ", "-"), "name": nama,
            "plc": {"reachable": reachable, "ai": ai, "disk": disk}}


FRAME = {"keadaan": "frame_berhenti", "mati": False, "kode": "FRAME_BERHENTI", "sejak": SEJAK,
         "umur_detik": None, "ambang_detik": 30}


def _disk(tingkat: str, bebas: float, sejak: float = SEJAK) -> dict:
    kode = {"peringatan": "DISK_HAMPIR_PENUH", "kritis": "DISK_KRITIS"}.get(tingkat)
    return {"tingkat": tingkat, "kode": kode, "bebas_gb": bebas, "total_gb": 468.0, "sejak": sejak}


def test_kunci_baru_ada_di_kedua_bahasa():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        for kunci in ("frameBerhentiJudul", "frameBerhentiRinci", "diskHampirPenuhJudul",
                      "diskKritisJudul", "diskRinci"):
            assert f"{kunci}:" in isi, (bahasa, kunci)


def test_pita_disk_ada_di_layar_dan_digambar_tiap_polling():
    assert '<div id="pita-disk" hidden></div>' in HTML
    assert "gambarPitaDisk(s.lines)" in fungsi("refresh")
    assert "tulisKalauBeda(el, html)" in fungsi("gambarPitaDisk")


def test_pita_disk_memakai_esc():
    assert fungsi("pitaDisk").count("esc(") == 3


def test_tanpa_suara():
    blok = fungsi("pitaDisk") + fungsi("gambarPitaDisk") + fungsi("gabungDisk") + fungsi("pitaAi")
    assert not re.search(r"Audio|\.play\(|speechSynthesis|beep", blok)


@butuh_node
def test_frame_berhenti_menulis_line_jam_dan_tindakan_tanpa_kode():
    html = jalankan(FUNGSI_PITA, f"pitaAi({json.dumps(_line(FRAME))}, {SEJAK + 42})")
    assert 'class="pita-ai" role="alert"' in html
    assert "Line 2: kamera berhenti mengirim gambar" in html
    assert "Sejak 21.13." in html
    assert "periksa kabel data dan switch kamera" in html
    # Keputusan user 2026-10-01: kodenya cuma di tab Log.
    assert "FRAME_BERHENTI" not in html and "Kode" not in html


@butuh_node
def test_frame_berhenti_membuat_kartu_merah():
    assert jalankan(FUNGSI_PITA, f"aiMati({json.dumps(_line(FRAME))})") is True


@butuh_node
def test_frame_berhenti_bahasa_inggris():
    html = jalankan(FUNGSI_PITA, f"pitaAi({json.dumps(_line(FRAME))}, {SEJAK + 42})", bahasa="en")
    assert "Line 2: camera stopped sending images" in html
    assert "Since 21:13." in html and "FRAME_BERHENTI" not in html


@pytest.mark.parametrize(
    "ai",
    [{"keadaan": "sumber_selesai", "mati": False}, {"keadaan": "kamera_putus", "mati": False},
     {"keadaan": "sumber_diam", "mati": False}],
    ids=["sumber-selesai", "kamera-putus", "line-2.1-sumber-diam"],
)
@butuh_node
def test_keadaan_bukan_gagal_tidak_menggambar(ai):
    line = json.dumps(_line(ai))
    assert jalankan(FUNGSI_PITA, f"[aiMati({line}), pitaAi({line})]") == [False, ""]


@butuh_node
def test_disk_tiga_line_satu_pita_dengan_sisa_terkecil():
    lines = [_line(disk=_disk("peringatan", b), nama=f"Line {i}") for i, b in ((1, 12.4), (2, 12.1), (3, 12.3))]
    html = jalankan(FUNGSI_DISK, f"pitaDisk({json.dumps(lines)}, {SEJAK + 60})")
    assert html.count('role="alert"') == 1
    assert 'class="peringatan"' in html
    assert "Disk PC hampir penuh" in html
    assert "Sejak 21.13, dilaporkan Line 1, Line 2, Line 3." in html
    assert "DISK_HAMPIR_PENUH" not in html
    assert "Sisa 12,1 GB dari 468 GB." in html
    # Permintaan user 2026-10-01: cukup sampai sisa GB, langkah teknisnya urusan teknisi.
    assert "Jadwalkan pengosongan" not in html and html.endswith("dari 468 GB.</span></p>")


@butuh_node
def test_disk_kritis_didahulukan_dan_berdenyut():
    lines = [_line(disk=_disk("peringatan", 12), nama="Line 1"), _line(disk=_disk("kritis", 3), nama="Line 2")]
    html = jalankan(FUNGSI_DISK, f"pitaDisk({json.dumps(lines)}, {SEJAK + 60})")
    assert html.index('class="kritis"') < html.index('class="peringatan"')
    assert "Disk PC hampir habis" in html and "Kosongkan sekarang" not in html


@butuh_node
def test_disk_bahasa_inggris():
    html = jalankan(FUNGSI_DISK, f"pitaDisk({json.dumps([_line(disk=_disk('kritis', 3))])}, {SEJAK + 60})",
                    bahasa="en")
    assert "PC disk nearly out of space" in html and "Since 21:13, reported by Line 2." in html
    assert "DISK_KRITIS" not in html


@pytest.mark.parametrize(
    "line",
    [_line(disk=_disk("aman", 232)), _line(disk={"tingkat": "tidak_terbaca", "kode": None}),
     _line(disk=None), _line(disk=_disk("kritis", 3), reachable=False),
     {"line_code": "line-9", "name": "? line-9"}],
    ids=["aman", "tak-terbaca", "line-lama", "offline", "line-asing"],
)
@butuh_node
def test_disk_tanpa_masalah_tidak_menggambar(line):
    assert jalankan(FUNGSI_DISK, f"pitaDisk({json.dumps([line])})") == ""


# Permintaan user 2026-10-01: pita disk selebar kartu di bawahnya, berdenyut, dan
# peringatannya bisa ditutup selama 24 jam.
SEHARI = 24 * 3600


def test_pita_layar_selebar_bagian_lain():
    # #lines dan #tally memakai --pad; 13px membuat pita menjorok keluar 7px.
    for pita in ("#pita-alarm", "#pita-disk"):
        aturan = re.search(rf"{pita} \{{([^}}]*)\}}", HTML).group(1)
        assert "margin:10px var(--pad) 0" in aturan, pita


def test_pita_disk_peringatan_juga_berdenyut():
    aturan = re.search(r"#pita-disk p \{([^}]*)\}", HTML).group(1)
    assert "animation:denyut-pita" in aturan


def test_saran_disk_dibuang_dari_kamus():
    assert "diskSaran" not in HTML


def test_pita_disk_ditutup_disimpan_dengan_jamnya():
    assert "pitaDisk(lines, undefined, bacaPitaDiskDitutupPada())" in fungsi("gambarPitaDisk")
    assert 'simpan("pitaDiskDitutupPada"' in HTML
    assert '$("pita-disk").addEventListener("click"' in HTML


def _peringatan() -> str:
    return json.dumps([_line(disk=_disk("peringatan", 12))])


@butuh_node
def test_disk_peringatan_punya_tombol_tutup():
    html = jalankan(FUNGSI_DISK, f"pitaDisk({_peringatan()}, {SEJAK + 60})")
    assert "data-tutup-pita" in html and 'aria-label="Tutup"' in html


@butuh_node
def test_disk_kritis_tidak_bisa_ditutup():
    lines = json.dumps([_line(disk=_disk("kritis", 3))])
    html = jalankan(FUNGSI_DISK, f"pitaDisk({lines}, {SEJAK + 60}, {SEJAK + 30})")
    assert "Disk PC hampir habis" in html and "data-tutup-pita" not in html


@pytest.mark.parametrize(
    ("umur", "tampil"),
    [(0, False), (SEHARI - 1, False), (SEHARI, True), (-60, True)],
    ids=["baru-ditutup", "hampir-sehari", "sehari", "jam-mundur"],
)
@butuh_node
def test_disk_peringatan_yang_ditutup_muncul_lagi_sesudah_24_jam(umur, tampil):
    sekarang = SEJAK + 2 * SEHARI
    html = jalankan(FUNGSI_DISK, f"pitaDisk({_peringatan()}, {sekarang}, {sekarang - umur})")
    assert ("Disk PC hampir penuh" in html) is tampil


# Permintaan user 2026-10-01: ikon peringatan di depan judul, judul dan rincian satu baris.
def test_pita_disk_satu_baris():
    aturan = re.search(r"#pita-disk p \{([^}]*)\}", HTML).group(1)
    assert "display:flex" in aturan
    for anak in ("b", "span"):
        assert "display:block" not in re.search(rf"#pita-disk {anak} \{{([^}}]*)\}}", HTML).group(1), anak


@pytest.mark.parametrize("tingkat", ["peringatan", "kritis"])
@butuh_node
def test_pita_disk_berikon_peringatan(tingkat):
    html = jalankan(FUNGSI_DISK, f"pitaDisk({json.dumps([_line(disk=_disk(tingkat, 3))])}, {SEJAK + 60})")
    # Ikon SVG di dalam halaman (konsol harus jalan tanpa internet), bukan emoji yang
    # tergantung font PC pabrik; dibaca pembaca layar lewat judulnya saja.
    assert re.search(r'<svg class="ikon-pita"[^>]*aria-hidden="true"', html)
    assert html.index("<svg") < html.index("<b>")
