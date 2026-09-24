"""Pustaka model: kelas `.pt` dan `.engine` terbaca TANPA torch.

Konsol tidak memasang torch (CI juga tidak), padahal layar Model Deteksi harus
menampilkan kelas tiap model sebelum dipilih. `.pt` Ultralytics adalah zip
berisi `data.pkl`; kelasnya ada di atribut `names` objek model di dalam pickle
itu. Tes di sini membuat checkpoint palsu yang bentuknya sama — kelas dari
modul yang TIDAK ADA saat dibaca, tensor lewat `persistent_id` — sehingga
lulusnya tes membuktikan pembacaan tidak mengimpor apa pun.
"""
from __future__ import annotations

import os
import pickle
import sys
import zipfile
from pathlib import Path

import pytest
from model_palsu import EMPAT, LAMA, MODUL_PALSU, buat_engine, buat_pt

from palmgrade.services import model_library
from palmgrade.services.model_library import ModelLibrary, baca_kelas_pt, baca_meta_engine

REPO_ROOT = Path(__file__).resolve().parents[2]


def atur_mtime(path: Path, detik: float) -> None:
    os.utime(path, (detik, detik))


@pytest.fixture(autouse=True)
def cache_bersih():
    model_library._CACHE.clear()
    yield
    model_library._CACHE.clear()


@pytest.fixture
def folder(tmp_path):
    release = tmp_path / "models" / "release"
    engines = tmp_path / "engines"
    release.mkdir(parents=True)
    engines.mkdir()
    return release, engines


# ─────────────────────────────────────────────── baca_kelas_pt

def test_kelas_pt_terbaca_tanpa_modul_aslinya(tmp_path):
    pt = buat_pt(tmp_path / "best.pt", EMPAT)
    assert MODUL_PALSU not in sys.modules
    assert baca_kelas_pt(pt) == ["JK", "Ripe", "TP", "Unripe"]


def test_kelas_pt_dari_ema_kalau_model_tidak_ada(tmp_path):
    pt = buat_pt(tmp_path / "last.pt", LAMA, kunci="ema")
    assert baca_kelas_pt(pt) == ["ACC", "Rej", "TP"]


def test_kelas_pt_urut_menurut_indeks_bukan_abjad(tmp_path):
    pt = buat_pt(tmp_path / "b.pt", {0: "Unripe", 1: "JK", 10: "TP", 2: "Ripe"})
    assert baca_kelas_pt(pt) == ["Unripe", "JK", "Ripe", "TP"]


def test_kelas_pt_bentuk_list(tmp_path):
    pt = buat_pt(tmp_path / "l.pt", ["JK", "Ripe"])
    assert baca_kelas_pt(pt) == ["JK", "Ripe"]


def test_pt_bukan_zip_none(tmp_path):
    (tmp_path / "r.pt").write_bytes(b"bukan zip")
    assert baca_kelas_pt(tmp_path / "r.pt") is None


def test_pt_kosong_none(tmp_path):
    (tmp_path / "k.pt").touch()
    assert baca_kelas_pt(tmp_path / "k.pt") is None


def test_pt_zip_tanpa_data_pkl_none(tmp_path):
    with zipfile.ZipFile(tmp_path / "z.pt", "w") as z:
        z.writestr("lain.txt", "halo")
    assert baca_kelas_pt(tmp_path / "z.pt") is None


class _Jahat:
    def __init__(self, bukti: Path) -> None:
        self.bukti = bukti

    def __reduce__(self):
        return (os.system, (f"touch {self.bukti}",))


def test_pickle_jahat_tidak_dijalankan(tmp_path):
    bukti = tmp_path / "TERJADI"
    with zipfile.ZipFile(tmp_path / "jahat.pt", "w") as z:
        z.writestr("jahat/data.pkl", pickle.dumps({"model": _Jahat(bukti)}, protocol=2))
    assert baca_kelas_pt(tmp_path / "jahat.pt") is None
    assert not bukti.exists()


# ─────────────────────────────────────────────── baca_meta_engine

def test_meta_engine_memberi_kelas(tmp_path):
    meta = baca_meta_engine(buat_engine(tmp_path / "best.sm86.engine", EMPAT))
    assert meta is not None
    assert meta["kelas"] == ["JK", "Ripe", "TP", "Unripe"]


def test_meta_engine_tanpa_header_none(tmp_path):
    assert baca_meta_engine(buat_engine(tmp_path / "x.sm86.engine", None, sampah=True)) is None


def test_meta_engine_kosong_none(tmp_path):
    (tmp_path / "k.sm86.engine").touch()
    assert baca_meta_engine(tmp_path / "k.sm86.engine") is None


# ─────────────────────────────────────────────── ModelLibrary.daftar

def test_daftar_menandai_cocok_dan_tidak(folder):
    release, engines = folder
    buat_pt(release / "best.pt", EMPAT)
    buat_pt(release / "best_3class_v2.pt", LAMA)
    (release / ".gitkeep").touch()

    daftar = ModelLibrary(release, engines).daftar()

    assert [m["berkas"] for m in daftar] == ["best.pt", "best_3class_v2.pt"]
    baru, lama = daftar
    assert baru["cocok"] is True and baru["alasan"] == ""
    assert baru["kelas"] == ["JK", "Ripe", "TP", "Unripe"]
    assert lama["cocok"] is False
    assert "ACC" in lama["alasan"] and "Ripe" in lama["alasan"]


def test_daftar_pt_rusak_tetap_tampil_tapi_tidak_cocok(folder):
    release, engines = folder
    (release / "rusak.pt").write_bytes(b"sampah")
    [satu] = ModelLibrary(release, engines).daftar()
    assert satu["kelas"] is None
    assert satu["cocok"] is False
    assert "tidak terbaca" in satu["alasan"]


def test_daftar_folder_tidak_ada_kosong(tmp_path):
    assert ModelLibrary(tmp_path / "tidak-ada", tmp_path / "juga-tidak").daftar() == []


def test_engine_per_gpu_dikenali_per_model(folder):
    release, engines = folder
    buat_pt(release / "best.pt", EMPAT)
    buat_pt(release / "best_3class_v2.pt", LAMA)
    atur_mtime(release / "best.pt", 1_000)
    buat_engine(engines / "best.sm86.engine", EMPAT)
    buat_engine(engines / "best.sm75.engine", EMPAT)
    buat_engine(engines / "best_3class_v2.sm86.engine", LAMA)
    atur_mtime(engines / "best.sm86.engine", 2_000)
    atur_mtime(engines / "best.sm75.engine", 2_000)

    baru = ModelLibrary(release, engines).cari("best.pt")

    assert [e["sm"] for e in baru["engine"]] == ["75", "86"]
    assert all(e["basi"] is False for e in baru["engine"])
    assert baru["engine"][1]["kelas"] == ["JK", "Ripe", "TP", "Unripe"]


def test_engine_lebih_tua_dari_pt_basi(folder):
    release, engines = folder
    buat_pt(release / "best.pt", EMPAT)
    buat_engine(engines / "best.sm86.engine", EMPAT)
    atur_mtime(engines / "best.sm86.engine", 1_000)
    atur_mtime(release / "best.pt", 2_000)

    [engine] = ModelLibrary(release, engines).cari("best.pt")["engine"]
    assert engine["basi"] is True


def test_engine_berkelas_lain_basi_walau_lebih_baru(folder):
    # Isi best.pt diganti model lain dengan nama sama, lalu mtime-nya
    # dipertahankan (`cp -p`): yang tersisa cuma kelasnya yang berbeda.
    release, engines = folder
    buat_pt(release / "best.pt", EMPAT)
    buat_engine(engines / "best.sm86.engine", LAMA)
    atur_mtime(release / "best.pt", 1_000)
    atur_mtime(engines / "best.sm86.engine", 2_000)

    [engine] = ModelLibrary(release, engines).cari("best.pt")["engine"]
    assert engine["basi"] is True


def test_engine_tanpa_metadata_tidak_basi_kalau_lebih_baru(folder):
    release, engines = folder
    buat_pt(release / "best.pt", EMPAT)
    buat_engine(engines / "best.sm86.engine", None, sampah=True)
    atur_mtime(release / "best.pt", 1_000)
    atur_mtime(engines / "best.sm86.engine", 2_000)

    [engine] = ModelLibrary(release, engines).cari("best.pt")["engine"]
    assert engine["kelas"] is None
    assert engine["basi"] is False


def test_cari_model_tidak_ada_none(folder):
    release, engines = folder
    assert ModelLibrary(release, engines).cari("hantu.pt") is None


def test_cache_tidak_membaca_ulang_berkas_yang_sama(folder, monkeypatch):
    release, engines = folder
    pt = buat_pt(release / "best.pt", EMPAT)
    panggilan = []
    asli = model_library.baca_kelas_pt

    def hitung(path):
        panggilan.append(path)
        return asli(path)

    monkeypatch.setattr(model_library, "baca_kelas_pt", hitung)

    ModelLibrary(release, engines).daftar()
    ModelLibrary(release, engines).daftar()
    assert len(panggilan) == 1

    buat_pt(pt, LAMA)  # isi berubah -> ukuran berubah -> dibaca ulang
    [satu] = ModelLibrary(release, engines).daftar()
    assert len(panggilan) == 2
    assert satu["kelas"] == ["ACC", "Rej", "TP"]


@pytest.mark.parametrize(
    ("berkas", "kelas"),
    [
        ("best.pt", ["JK", "Ripe", "TP", "Unripe"]),
        ("best_3class_v2.pt", ["ACC", "Rej", "TP"]),
    ],
)
def test_model_asli_di_mesin_ini(berkas, kelas):
    """Checkpoint Ultralytics sungguhan, kalau ada di mesin ini (tidak di CI)."""
    path = REPO_ROOT / "models" / "release" / berkas
    if not path.exists():
        pytest.skip(f"{berkas} tidak ada di mesin ini")
    assert baca_kelas_pt(path) == kelas


def test_nama_berkas_tak_didukung_tampil_tapi_tidak_cocok(folder):
    # Kelasnya benar, namanya yang tidak bisa ditulis ke media.env. Tampil
    # dengan alasannya, bukan lolos ke dropdown lalu ditolak 400 saat simpan.
    release, engines = folder
    buat_pt(release / "a$b.pt", EMPAT)
    [satu] = ModelLibrary(release, engines).daftar()
    assert satu["kelas"] == ["JK", "Ripe", "TP", "Unripe"]
    assert satu["cocok"] is False
    assert "nama" in satu["alasan"]


def test_folder_tidak_ada_tidak_terbaca(tmp_path):
    # Konsol pabrik tanpa mount ./models: folder tidak ada di container.
    assert ModelLibrary(tmp_path / "tidak-ada", tmp_path / "engines").terbaca() is False


def test_folder_kosong_tetap_terbaca(folder):
    release, engines = folder
    assert ModelLibrary(release, engines).terbaca() is True
