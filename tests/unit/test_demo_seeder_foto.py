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

Berkas ini sengaja **tidak** menyentuh cv2: yang diuji di sini aritmetika path,
dan suite unit jalan di CI yang tidak memasang cv2 maupun numpy. Penulisan
gambar sungguhan diuji di `tests/e2e/test_demo_seeder_gambar.py`.
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


def test_path_di_database_menunjuk_berkas_yang_ada(seeder, tmp_path, monkeypatch):
    """Kontrak yang sebenarnya: tiap `image_path` yang ditulis seeder harus bisa
    ditemukan di disk lewat aturan `_capture_url` — kebalikannya harus cocok."""
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))

    from palmgrade.services.console_service import _capture_url

    line = "line-1"
    rel = "captures/results/2026-09-17/091432_B1234XY_abcd1234/bbox/acc/x.webp"
    tujuan = seeder.jalur_gambar_demo(tmp_path, line, rel)

    # Berkasnya ditulis di sini tanpa encoder: yang diuji lokasinya, bukan isinya.
    tujuan.parent.mkdir(parents=True, exist_ok=True)
    tujuan.write_bytes(b"x")

    url = _capture_url(line, rel)
    assert url == f"/captures/{line}/results/2026-09-17/091432_B1234XY_abcd1234/bbox/acc/x.webp"

    # Jalur yang dilayani StaticFiles: artifacts/<line>/ + sisa URL setelah prefix.
    dilayani = tmp_path / line / url.removeprefix(f"/captures/{line}/")
    assert dilayani.exists(), f"URL {url} tidak punya berkas di {dilayani}"


def test_folder_per_line_bukan_artifacts_results(seeder, tmp_path):
    """Jebakan yang paling mahal: satu tingkat terlalu tinggi = 404 senyap.

    `artifacts/results/...` menyimpan gambar berukuran benar yang tidak pernah
    dilayani, karena mount-nya `artifacts/{line_code}`.
    """
    rel = "captures/results/2026-09-17/t/bbox/acc/a.webp"
    tujuan = seeder.jalur_gambar_demo(tmp_path, "line-2", rel)
    assert tujuan == tmp_path / "line-2" / "results/2026-09-17/t/bbox/acc/a.webp"
    assert tujuan.is_relative_to(tmp_path / "line-2")


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


def test_capture_nyata_dikelompokkan_per_verdict(seeder, tmp_path):
    """Pemindai capture nyata tidak boleh mencampur acc ke rej, dan tidak boleh
    ikut mengambil `clean/` (calon data latih) atau `thumb/` (400px)."""
    hari = tmp_path / "line-1" / "results" / "2026-09-17" / "truk"
    for sub, nama in (
        ("bbox/acc", "a.webp"),
        ("bbox/rej", "b.webp"),
        ("clean/acc", "c.webp"),
        ("thumb/acc", "d.webp"),
    ):
        p = hari / sub / nama
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")

    nyata = seeder.kumpulkan_capture_nyata(tmp_path)

    assert [p.name for p in nyata["acc"]] == ["a.webp"]
    assert [p.name for p in nyata["rej"]] == ["b.webp"]


def test_berkas_kosong_tidak_dipakai(seeder, tmp_path):
    """Capture 0 byte ada di disk kalau line mati di tengah tulis. Menyalinnya
    berarti kolom FOTO menjawab 200 dengan gambar rusak — lebih buruk dari 404,
    karena terlihat seperti kerusakan kamera."""
    p = tmp_path / "line-1" / "results" / "2026-09-17" / "t" / "bbox" / "acc" / "kosong.webp"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")

    nyata = seeder.kumpulkan_capture_nyata(tmp_path)

    assert nyata["acc"] == []


def test_artifacts_belum_ada_tidak_meledak(seeder, tmp_path):
    """PC baru: `make demo` jalan sebelum satu line pun pernah hidup."""
    assert seeder.kumpulkan_capture_nyata(tmp_path / "belum-ada") == {"acc": [], "rej": []}
