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
                      "diskKritisJudul", "diskRinci", "diskSaranPeringatan", "diskSaranKritis"):
            assert f"{kunci}:" in isi, (bahasa, kunci)


def test_pita_disk_ada_di_layar_dan_digambar_tiap_polling():
    assert '<div id="pita-disk" hidden></div>' in HTML
    assert "gambarPitaDisk(s.lines)" in fungsi("refresh")
    assert "tulisKalauBeda(el, html)" in fungsi("gambarPitaDisk")


def test_pita_disk_memakai_esc():
    assert fungsi("pitaDisk").count("esc(") == 5


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
    assert "Jadwalkan pengosongan" in html


@butuh_node
def test_disk_kritis_didahulukan_dan_berdenyut():
    lines = [_line(disk=_disk("peringatan", 12), nama="Line 1"), _line(disk=_disk("kritis", 3), nama="Line 2")]
    html = jalankan(FUNGSI_DISK, f"pitaDisk({json.dumps(lines)}, {SEJAK + 60})")
    assert html.index('class="kritis"') < html.index('class="peringatan"')
    assert "Disk PC hampir habis" in html and "Kosongkan sekarang" in html


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


# Permintaan user 2026-10-01: pita disk selebar kartu di bawahnya dan bisa ditutup.
KUNCI_PERINGATAN = str(int(SEJAK))


def test_pita_layar_selebar_bagian_lain():
    # #lines dan #tally memakai --pad; 13px membuat pita menjorok keluar 7px.
    for pita in ("#pita-disk", "#pita-alarm"):
        aturan = re.search(rf"{pita} \{{([^}}]*)\}}", HTML).group(1)
        assert "margin:10px var(--pad) 0" in aturan, pita


def test_pita_disk_ditutup_disimpan_per_episode():
    assert "pitaDisk(lines, undefined, bacaPitaDiskDitutup())" in fungsi("gambarPitaDisk")
    assert 'simpan("pitaDiskDitutup"' in HTML
    assert '$("pita-disk").addEventListener("click"' in HTML


@butuh_node
def test_disk_peringatan_punya_tombol_tutup():
    html = jalankan(FUNGSI_DISK, f"pitaDisk({json.dumps([_line(disk=_disk('peringatan', 12))])}, {SEJAK + 60})")
    assert f'data-tutup-pita="{KUNCI_PERINGATAN}"' in html
    assert 'aria-label="Tutup"' in html


@butuh_node
def test_disk_kritis_tidak_bisa_ditutup():
    lines = json.dumps([_line(disk=_disk("kritis", 3))])
    html = jalankan(FUNGSI_DISK, f"pitaDisk({lines}, {SEJAK + 60}, ['{int(SEJAK)}'])")
    assert "Disk PC hampir habis" in html and "data-tutup-pita" not in html


@butuh_node
def test_disk_peringatan_yang_ditutup_hilang_sampai_episode_baru():
    tutup = json.dumps([KUNCI_PERINGATAN])
    sama = json.dumps([_line(disk=_disk("peringatan", 12))])
    assert jalankan(FUNGSI_DISK, f"pitaDisk({sama}, {SEJAK + 60}, {tutup})") == ""
    baru = json.dumps([_line(disk=_disk("peringatan", 12, sejak=SEJAK + 3600))])
    assert "Disk PC hampir penuh" in jalankan(FUNGSI_DISK, f"pitaDisk({baru}, {SEJAK + 3700}, {tutup})")
    # Kritis tidak pernah disaring, walau jam mulainya sama dengan peringatan yang ditutup.
    kritis = json.dumps([_line(disk=_disk("kritis", 3))])
    assert "Disk PC hampir habis" in jalankan(FUNGSI_DISK, f"pitaDisk({kritis}, {SEJAK + 60}, {tutup})")
