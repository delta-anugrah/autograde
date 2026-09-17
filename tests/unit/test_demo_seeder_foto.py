"""Seeder demo harus menulis berkas gambarnya, bukan cuma path ke database.

Sebelum ini seeder menulis `image_path` ke `inspections` tanpa pernah membuat
berkasnya. Akibatnya tiap kolom FOTO di tab Grading dijawab **404**: lapisan foto
terbuka kosong dan terlihat seperti gambar rusak. Gagalnya sunyi — tidak ada
error di mana pun, karena dari sisi database barisnya lengkap.

Yang mengikat dua sisi itu adalah `_capture_url` di `services/console_service.py`:

    image_path  captures/results/<hari>/<truk>/bbox/acc/<berkas>.webp
    URL         /captures/<line_code>/results/<hari>/<truk>/bbox/acc/<berkas>.webp
    di disk     <ARTIFACTS_DIR>/<line_code>/results/<hari>/<truk>/bbox/acc/<berkas>.webp

`console_main` memasang `/captures/{line_code}` dari `artifacts/{line_code}`, jadi
berkasnya WAJIB berada di bawah folder per-line — bukan di `artifacts/results/`.
Menaruhnya satu tingkat lebih tinggi menyimpan gambar dengan ukuran benar dan
tetap dijawab 404, persis seperti jebakan di `test_artifacts_per_line.py`.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

AKAR = pathlib.Path(__file__).resolve().parents[2]


def _muat_seeder():
    """`scripts/` bukan package, jadi dimuat lewat path."""
    jalur = AKAR / "scripts" / "seed-console-demo.py"
    spec = importlib.util.spec_from_file_location("seed_console_demo", jalur)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


@pytest.fixture
def seeder():
    return _muat_seeder()


def test_menulis_berkas_webp_yang_bisa_dibaca(seeder, tmp_path):
    """Bukan cuma ada: harus webp yang utuh, karena browser yang menilainya."""
    tujuan = tmp_path / "line-1" / "results" / "2026-09-17" / "truk" / "bbox" / "acc" / "a.webp"

    seeder.tulis_gambar_demo(tujuan, label="Ripe", nomor=1)

    assert tujuan.exists(), "berkas gambar tidak dibuat"
    isi = tujuan.read_bytes()
    assert len(isi) > 0, "berkas gambar kosong"
    # Header RIFF....WEBP — dicek dari byte, bukan dari ekstensi, supaya
    # placeholder yang ternyata PNG bernama .webp tidak lolos.
    assert isi[:4] == b"RIFF" and isi[8:12] == b"WEBP", "bukan berkas WebP"


def test_path_di_database_menunjuk_berkas_yang_ada(seeder, tmp_path, monkeypatch):
    """Kontrak yang sebenarnya: tiap `image_path` yang ditulis seeder harus
    bisa ditemukan di disk lewat aturan `_capture_url`."""
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("DEMO_MODE", "1")

    from palmgrade.services.console_service import _capture_url

    line = "line-1"
    rel = "captures/results/2026-09-17/091432_B1234XY_abcd1234/bbox/acc/x.webp"
    tujuan = seeder.jalur_gambar_demo(tmp_path, line, rel)
    seeder.tulis_gambar_demo(tujuan, label="Ripe", nomor=1)

    url = _capture_url(line, rel)
    assert url == f"/captures/{line}/results/2026-09-17/091432_B1234XY_abcd1234/bbox/acc/x.webp"

    # Jalur yang dilayani StaticFiles: artifacts/<line>/ + sisa URL setelah prefix.
    dilayani = tmp_path / line / url.removeprefix(f"/captures/{line}/")
    assert dilayani.exists(), f"URL {url} tidak punya berkas di {dilayani}"


def test_acc_dan_rej_terpisah(seeder, tmp_path):
    """Verdict adalah folder, bukan field (`capture_layout` aturan 3). Foto REJ
    yang mendarat di `bbox/acc/` membuat demo menceritakan hal yang salah."""
    acc = seeder.jalur_gambar_demo(
        tmp_path, "line-1", "captures/results/2026-09-17/t/bbox/acc/a.webp"
    )
    rej = seeder.jalur_gambar_demo(
        tmp_path, "line-1", "captures/results/2026-09-17/t/bbox/rej/b.webp"
    )
    assert acc.parent.name == "acc"
    assert rej.parent.name == "rej"
    assert acc != rej
