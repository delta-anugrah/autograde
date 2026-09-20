"""Berapa lama satu truk diproses, dari timbang masuk sampai timbang keluar.

Angka ini turunan: tidak ada kolom ketiga di SQLite, cuma selisih `entered_at`
dan `exited_at` yang dihitung di layar. Yang diuji di sini dua lapis, karena
keduanya bisa rusak diam-diam:

- **invarian teks**, seperti `test_console_html.py` — kolom baru menggeser lebar
  tabel, dan `colspan` baris kosong yang tertinggal di angka lama adalah cacat
  tanpa error: barisnya cuma terlihat kependekan dan tidak ada yang sadar.
- **perilaku fungsinya**, dijalankan sungguhan lewat node kalau ada. Tiga
  jawabannya yang tidak boleh ditebak dari membaca saja: tiket yang belum
  timbang keluar (masih berjalan, bukan nol menit), jam yang mundur karena
  dikoreksi manual atau NTP menyentak (bukan durasi negatif), dan pembulatan di
  batas jam. Node tidak ada di image CI, jadi lapis ini skip di sana — lapis
  teks di atas yang tetap jalan di setiap PR.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

KONSOL = Path(__file__).resolve().parents[2] / "src" / "palmgrade" / "static" / "console.html"
HTML = KONSOL.read_text(encoding="utf-8")


def _fungsi(nama: str) -> str:
    """Body of one top-level function, up to the first line that closes it."""
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


# ── invarian teks: selalu jalan, juga di CI tanpa node ──────────────────────


def test_tabel_timbangan_punya_kolom_lama():
    assert 'data-t="thLama"' in HTML, "kolom Lama hilang dari header tabel timbangan"
    assert "lamaProses(w.entered_at, w.exited_at)" in HTML, (
        "sel Lama tidak memanggil lamaProses dengan dua jam timbangan"
    )


def test_kolom_lama_diterjemahkan_di_kedua_bahasa():
    assert 'thLama:"Lama"' in HTML, "label Lama hilang dari kamus Indonesia"
    assert 'thLama:"Duration"' in HTML, "label Lama hilang dari kamus Inggris"


def test_baris_kosong_selebar_tabel_yang_sudah_ditambah_kolom():
    """`colspan` yang tertinggal di lebar lama tidak melempar apa pun."""
    kolom = HTML.count('<th data-t="thMasuk"')
    assert kolom == 1, "header tabel timbangan tidak tunggal lagi, hitungan di bawah tak sahih"
    awal = HTML.index('<th data-t="thMasuk"')
    kepala = HTML[awal : HTML.index("</thead>", awal)]
    assert kepala.count("<th") == 9, "lebar header berubah - colspan baris kosong ikut berubah"
    assert 'barisKosong(9, "kosongTiket")' in HTML, (
        "baris 'belum ada tiket' tidak selebar tabel timbangan"
    )


def test_durasi_tidak_disimpan_sebagai_kolom_ketiga():
    """Dihitung dari dua jam yang sudah ada, bukan ditulis ke SQLite.

    Kolom simpanan bisa berbeda dari selisihnya sendiri begitu salah satu jam
    dikoreksi, dan operator tidak punya cara tahu yang mana yang benar.
    """
    for nama in ("duration_min", "lama_proses", "dwell_min"):
        assert nama not in HTML, f"{nama} disimpan - durasi harus tetap turunan"


# ── perilaku: butuh node, skip di CI ───────────────────────────────────────

NODE = shutil.which("node")
butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada (image CI)")


def _lama(masuk: str | None, keluar: str | None) -> str | None:
    """Jalankan `lamaProses` yang SUNGGUHAN dari console.html, bukan salinannya.

    Disalin ke test, fungsinya akan terus lulus setelah yang di layar diubah.
    """
    skrip = _fungsi("lamaProses") + f"\nconsole.log(JSON.stringify(lamaProses({json.dumps(masuk)}, {json.dumps(keluar)})));"
    keluaran = subprocess.run(
        [NODE, "-e", skrip], capture_output=True, text=True, check=True, timeout=30
    ).stdout.strip()
    return json.loads(keluaran)


@butuh_node
def test_tiket_yang_belum_timbang_keluar_masih_berjalan():
    """Bukan '0 mnt': truknya masih di pabrik, durasinya belum ada."""
    assert _lama("2026-09-20T08:00:00", None) is None
    assert _lama(None, None) is None


@butuh_node
def test_jam_mundur_tidak_tampil_sebagai_durasi_negatif():
    """Koreksi jam manual atau NTP menyentak memberi selisih negatif."""
    assert _lama("2026-09-20T09:00:00", "2026-09-20T08:00:00") is None


@butuh_node
def test_jam_yang_tak_bisa_dibaca_tidak_menjatuhkan_baris():
    assert _lama("bukan jam", "2026-09-20T08:00:00") is None


@butuh_node
@pytest.mark.parametrize(
    ("masuk", "keluar", "harap"),
    [
        ("2026-09-20T08:00:00", "2026-09-20T08:25:00", "25 mnt"),
        ("2026-09-20T08:00:00", "2026-09-20T08:00:00", "0 mnt"),
        # Tepat di batas jam: 60 menit adalah "1 j", bukan "60 mnt".
        ("2026-09-20T08:00:00", "2026-09-20T09:00:00", "1 j"),
        ("2026-09-20T08:00:00", "2026-09-20T09:45:00", "1 j 45 mnt"),
        # Pabrik jalan lewat tengah malam - tanggalnya boleh beda.
        ("2026-09-20T23:30:00", "2026-09-21T01:10:00", "1 j 40 mnt"),
    ],
)
def test_durasi_dibaca_dalam_menit_dan_jam(masuk, keluar, harap):
    assert _lama(masuk, keluar) == harap
