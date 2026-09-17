"""End-to-end: `make demo` menulis berkas gambar yang browser benar-benar bisa muat.

Test unit membuktikan path-nya dihitung benar. Yang tidak bisa dibuktikan di sana
justru bagian yang dulu rusak: berkasnya memang ada, memang WebP, dan ACC/REJ
mengambil dari folder masing-masing.

Sebelum ini seeder cuma menulis `image_path` ke database. Tiap kolom FOTO di tab
Grading dijawab 404, lapisan foto terbuka kosong, dan terlihat seperti gambar
rusak — padahal berkasnya tidak pernah dibuat. Tidak ada error di mana pun.

Butuh cv2 dan numpy (menulis gambar sungguhan), jadi tinggal di e2e, bukan suite
unit yang jalan ringan di CI.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

AKAR = pathlib.Path(__file__).resolve().parents[2]


def _muat_seeder():
    jalur = AKAR / "scripts" / "seed-console-demo.py"
    spec = importlib.util.spec_from_file_location("seed_console_demo", jalur)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


@pytest.fixture
def seeder():
    return _muat_seeder()


def test_gambar_sintetis_adalah_webp_yang_utuh(seeder, tmp_path):
    """Bukan cuma ada: harus WebP yang bisa didekode, karena browser yang menilainya."""
    tujuan = tmp_path / "line-1" / "results" / "2026-09-17" / "t" / "bbox" / "acc" / "a.webp"

    seeder.tulis_gambar_demo(tujuan, label="Ripe", nomor=1)

    assert tujuan.exists()
    isi = tujuan.read_bytes()
    # Header dicek dari byte, bukan dari ekstensi: PNG bernama .webp tidak lolos.
    assert isi[:4] == b"RIFF" and isi[8:12] == b"WEBP", "bukan berkas WebP"
    # Dan benar-benar bisa didekode kembali — header yang betul tapi isi rusak
    # tetap menghasilkan kolom foto yang kosong di layar.
    img = cv2.imread(str(tujuan))
    assert img is not None, "WebP tidak bisa didekode"
    lebar, tinggi = seeder.DEMO_IMAGE_SIZE
    assert img.shape[:2] == (tinggi, lebar)


def test_kelas_berbeda_menghasilkan_gambar_berbeda(seeder, tmp_path):
    """Satu layar penuh gambar sintetis harus masih terbaca sebagai tiga kelas."""
    hasil = {}
    for label in ("Ripe", "Unripe", "JK"):
        p = tmp_path / f"{label}.webp"
        seeder.tulis_gambar_demo(p, label=label, nomor=1)
        hasil[label] = p.read_bytes()
    assert len(set(hasil.values())) == 3, "tiga kelas menghasilkan gambar identik"


def test_capture_nyata_diutamakan_dan_verdict_tidak_tertukar(seeder, tmp_path):
    """Kalau ada capture nyata, itu yang dipakai — dan REJ tidak boleh mengambil
    dari `bbox/acc/`. Demo yang menukarnya salah cerita soal mesinnya sendiri."""
    sumber = tmp_path / "line-1" / "results" / "2026-09-01" / "asli"
    for verdict, nama in (("acc", "asli-acc.webp"), ("rej", "asli-rej.webp")):
        p = sumber / "bbox" / verdict / nama
        p.parent.mkdir(parents=True, exist_ok=True)
        seeder.tulis_gambar_demo(p, label="Ripe" if verdict == "acc" else "Unripe", nomor=7)

    nyata = seeder.kumpulkan_capture_nyata(tmp_path)
    assert len(nyata["acc"]) == 1 and len(nyata["rej"]) == 1

    tujuan_acc = tmp_path / "out" / "acc.webp"
    tujuan_rej = tmp_path / "out" / "rej.webp"
    assert (
        seeder.sediakan_gambar(
            tujuan_acc, label="Ripe", nomor=0, rejected=False, nyata=nyata
        )
        == "nyata"
    )
    assert (
        seeder.sediakan_gambar(
            tujuan_rej, label="Unripe", nomor=0, rejected=True, nyata=nyata
        )
        == "nyata"
    )

    assert tujuan_acc.read_bytes() == (sumber / "bbox/acc/asli-acc.webp").read_bytes()
    assert tujuan_rej.read_bytes() == (sumber / "bbox/rej/asli-rej.webp").read_bytes()


def test_tanpa_capture_nyata_jatuh_ke_sintetis(seeder, tmp_path):
    """PC baru atau CI: `make demo` tetap harus jadi, bukan gagal."""
    tujuan = tmp_path / "out" / "a.webp"

    asal = seeder.sediakan_gambar(
        tujuan, label="Ripe", nomor=1, rejected=False, nyata={"acc": [], "rej": []}
    )

    assert asal == "sintetis"
    assert cv2.imread(str(tujuan)) is not None


def test_berkas_yang_sudah_ada_tidak_ditulis_ulang(seeder, tmp_path):
    """`make demo` dijalankan berkali-kali; menyalin ratusan gambar tiap kali itu
    pemborosan tanpa hasil berbeda."""
    tujuan = tmp_path / "out" / "a.webp"
    seeder.tulis_gambar_demo(tujuan, label="Ripe", nomor=1)
    sebelum = tujuan.stat().st_mtime_ns

    seeder.sediakan_gambar(
        tujuan, label="Unripe", nomor=99, rejected=True, nyata={"acc": [], "rej": []}
    )

    assert tujuan.stat().st_mtime_ns == sebelum, "berkas ditulis ulang tanpa perlu"
