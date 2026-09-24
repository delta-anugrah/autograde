"""Invarian HTML layar Model Deteksi — dijaga sebagai teks, seperti tetangganya.

Konsol tidak punya test runner JS (lihat `test_console_html_sumber.py`), jadi
yang dijaga di CI adalah bahwa elemen, endpoint, dan kunci kamus yang dipakai
skrip benar-benar ada di berkas yang sama. Perilaku layar dibuktikan di
browser saat pengerjaan (Playwright), bukan di sini.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HTML = (REPO_ROOT / "src" / "palmgrade" / "static" / "console.html").read_text(encoding="utf-8")


def test_tab_support_saja():
    tombol = re.search(r'<button data-tab="model-deteksi"[^>]*>', HTML)
    assert tombol, "tab Model Deteksi tidak ada"
    assert 'data-dev="1"' in tombol.group(0), "tab Model Deteksi harus support-only"
    assert re.search(r'<section id="sec-model-deteksi"[^>]*data-dev="1"', HTML)


def test_tab_terdaftar_di_tab_sah_dan_muat_tab():
    tab_sah = re.search(r"const TAB_SAH = \[(.*?)\];", HTML)
    assert tab_sah and '"model-deteksi"' in tab_sah.group(1)
    assert '"model-deteksi": muatModelDeteksi' in HTML


@pytest.mark.parametrize("n", [1, 2, 3])
def test_tiga_line_punya_kartu_pilihan_dan_rincian(n):
    assert f'data-model-line="line-{n}"' in HTML
    assert f'<select data-model="line-{n}"' in HTML
    assert f'data-model-rinci="line-{n}"' in HTML
    assert f'data-model-jalan="line-{n}"' in HTML


def test_kedua_endpoint_dipanggil():
    assert 'api("/api/console/dev/model-deteksi")' in HTML
    assert re.search(r'api\("/api/console/dev/model-deteksi",\s*\{\s*method:\s*"POST"', HTML)


def test_yang_sedang_jalan_dibaca_dari_diagnostik():
    # "Sudah dipilih" dan "sudah berlaku" dua hal berbeda; yang kedua cuma
    # diketahui line sendiri lewat /health/detail.
    awal = HTML.find("async function muatJalanModel")
    assert awal != -1
    assert 'api("/api/console/dev/diagnostik")' in HTML[awal : HTML.find("\n}\n", awal)]


def test_modal_restart_sebelum_menyimpan():
    """Permintaan user 2026-09-24: sebelum restart, tampilkan info dulu."""
    assert '<dialog id="model-modal"' in HTML
    for id_ in ("model-modal-daftar", "model-modal-batal", "model-modal-jalankan"):
        assert f'id="{id_}"' in HTML
    # Tombol Simpan cuma MEMBUKA modal; POST hanya ada di tombol konfirmasi.
    simpan = HTML[HTML.find('$("model-simpan").addEventListener') :]
    simpan = simpan[: simpan.find("\n});\n")]
    assert 'showModal()' in simpan
    assert "method: \"POST\"" not in simpan
    jalankan = HTML[HTML.find('$("model-modal-jalankan").addEventListener') :]
    jalankan = jalankan[: jalankan.find("\n});\n")]
    assert "/api/console/dev/model-deteksi" in jalankan


def test_modal_menyebut_truk_yang_sedang_diproses():
    awal = HTML.find('$("model-simpan").addEventListener')
    blok = HTML[awal : HTML.find("\n});\n", awal)]
    assert 'api("/api/console/state")' in blok
    assert "plate_number" in blok


def test_model_tidak_cocok_tidak_bisa_dipilih():
    awal = HTML.find("function opsiModel")
    assert awal != -1
    blok = HTML[awal : HTML.find("\n}\n", awal)]
    assert "disabled = !m.cocok" in blok


@pytest.mark.parametrize(
    "kunci",
    [
        "judulModelDeteksi", "modelPeringatan", "modelPilih", "modelBawaan",
        "modelJalan", "btnModelSimpan", "btnModelJalankan", "modelModalJudul",
        "modelModalRestart", "modelSibuk", "modelTersimpanSemua",
        "modelTersimpanSebagian", "gagalModelDeteksi", "gagalModelSimpan",
        "modelTanpaEngine", "modelEngineBasi", "modelTidakAdaPerubahan",
    ],
)
def test_kamus_dua_bahasa(kunci):
    # Satu kunci yang hilang di salah satu bahasa tampil sebagai nama kuncinya
    # sendiri di layar — terbaca seperti fitur setengah jadi.
    assert HTML.count(f"{kunci}:") >= 2, f"{kunci} tidak ada di kedua bahasa"


def test_nol_referensi_web():
    assert "https://" not in HTML


def _aturan_css(selector: str) -> str:
    awal = HTML.find(selector + " {")
    assert awal != -1, f"aturan CSS `{selector}` tidak ada"
    return HTML[awal : HTML.find("}", awal)]


def test_tombol_modal_tanpa_bingkai_tools():
    # `.tools` global adalah kepala tabel berbingkai. Di dalam modal bingkai
    # itu terpotong di bawah dan terbaca seperti kotak rusak (terlihat di
    # browser 2026-09-24).
    aturan = _aturan_css("#model-modal .tools")
    assert "border:0" in aturan
    assert "background:none" in aturan


def test_alasan_dan_engine_di_tabel_boleh_membungkus():
    # `th, td` global `white-space:nowrap`: kalimat alasan "kelas tidak
    # dikenal: ...; kelas hilang: ..." terpotong di kanan tabel.
    assert "white-space:normal" in _aturan_css("#model-baris td.bungkus")
    awal = HTML.find("function barisModel")
    blok = HTML[awal : HTML.find("\n}\n", awal)]
    assert blok.count('class="bungkus"') >= 2
