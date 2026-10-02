"""Batch 4.4: CI menguji pustaka yang SAMA dengan yang jalan di pabrik.

Sebelum ini `requirements-ci.txt` tanpa versi. Run CI 2026-10-01 memasang
fastapi 0.142, pydantic 2.13, numpy 2.4, cryptography 50 dan apscheduler 3.11,
sementara image pabrik memakai 0.115, 2.11, 1.26, 44 dan 3.10. Test yang hijau
di CI membuktikan kode jalan di pustaka yang tidak pernah dipasang di pabrik,
dan rilis berikutnya dari PyPI bisa memerahkan CI tanpa satu baris kode pun
berubah.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

AKAR = Path(__file__).resolve().parents[2]

# Wheel CI yang menggantikan paket runtime: nama beda, isinya sama.
PADANAN_RUNTIME = {"opencv-python-headless": "opencv-python"}


def _baca(nama: str) -> dict[str, Requirement]:
    hasil: dict[str, Requirement] = {}
    for baris in (AKAR / nama).read_text(encoding="utf-8").splitlines():
        baris = baris.split("#", 1)[0].strip()
        if not baris:
            continue
        req = Requirement(baris)
        hasil[canonicalize_name(req.name)] = req
    return hasil


CI = _baca("requirements-ci.txt")
RUNTIME = _baca("requirements.txt")


def _versi_kunci(req: Requirement) -> str | None:
    spek = list(req.specifier)
    if len(spek) == 1 and spek[0].operator == "==" and "*" not in spek[0].version:
        return spek[0].version
    return None


def test_daftar_ci_terbaca():
    """Kontrol: parser di atas benar-benar menemukan paket. Tanpa ini, berkas
    yang kosong atau salah baca membuat semua test di bawah lulus tanpa isi."""
    assert len(CI) >= 15, sorted(CI)
    assert "fastapi" in CI and "fastapi" in RUNTIME


@pytest.mark.parametrize("nama", sorted(CI))
def test_tiap_paket_ci_dikunci_persis(nama):
    """Tanpa `==` versi yang dipasang CI ditentukan hari run-nya, bukan repo."""
    assert _versi_kunci(CI[nama]), f"{nama}: {CI[nama]} harus `nama==versi`"


# Paket CI yang tidak ada di image pabrik. Daftar tertutup: paket baru di CI harus
# masuk runtime dengan versi sama, atau ditulis di sini dengan sengaja.
KHUSUS_TEST = {"ruff", "pytest", "pyyaml"}


def _nama_runtime(nama: str) -> str:
    return canonicalize_name(PADANAN_RUNTIME.get(nama, nama))


def test_paket_ci_ada_di_runtime_atau_khusus_test():
    asing = {n for n in CI if _nama_runtime(n) not in RUNTIME} - KHUSUS_TEST
    assert not asing, f"{sorted(asing)}: tambahkan ke requirements.txt atau ke KHUSUS_TEST"


@pytest.mark.parametrize("nama", sorted(n for n in CI if n not in KHUSUS_TEST))
def test_versi_ci_sama_dengan_runtime(nama):
    """Paket yang juga dipasang di image pabrik harus versi yang sama. Kalau
    runtime cuma memberi rentang (`aiosqlite>=0.20.0`), versi CI wajib masuk
    rentang itu."""
    req_runtime = RUNTIME[_nama_runtime(nama)]
    versi = _versi_kunci(CI[nama])
    assert versi, nama
    assert req_runtime.specifier.contains(versi, prereleases=True), (
        f"{nama}=={versi} di CI, runtime {req_runtime}: ubah keduanya di PR yang sama"
    )


def test_numpy_dikunci_ke_runtime_walau_cuma_ditarik_opencv():
    """Kontrol negatif terhadap skip di atas: numpy tidak dipakai langsung oleh
    kode console, tapi opencv menariknya. Tanpa kunci CI dapat numpy 2.x,
    pabrik 1.26.4."""
    assert _versi_kunci(CI["numpy"]) == _versi_kunci(RUNTIME["numpy"])


@pytest.mark.parametrize("nama", ["pymcprotocol", "pymodbus"])
def test_pustaka_plc_dipasang_di_ci(nama):
    """Tanpa `pymcprotocol`, `tests/e2e/test_mc_protocol_lane.py` dilewati di
    CI (`importorskip`), jadi bingkai MC Protocol sungguhan tidak pernah diuji
    sebelum sampai ke PLC pabrik."""
    assert nama in CI
    assert _versi_kunci(CI[nama]) == _versi_kunci(RUNTIME[nama])


def test_ci_tidak_menarik_torch():
    """Aturan lama yang tidak berubah: CI ringan, tanpa torch dan tanpa SDK."""
    for terlarang in ("torch", "torchvision", "ultralytics", "tensorrt"):
        assert terlarang not in CI, terlarang


# ── ruff memeriksa seluruh kode ─────────────────────────────────────────────


def _perintah_ruff() -> str:
    ci = yaml.safe_load((AKAR / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    langkah = [
        s for s in ci["jobs"]["lint-and-test"]["steps"] if str(s.get("run", "")).startswith("ruff ")
    ]
    assert len(langkah) == 1, langkah
    return langkah[0]["run"]


def test_ruff_memeriksa_seluruh_src_dan_tests():
    """Sebelumnya ruff cuma memeriksa 55 modul yang sudah dibersihkan; jalur
    panas (`main.py`, worker deteksi, repository capture) tidak pernah dilint.
    Ruff membaca berkas tanpa mengimpornya, jadi torch atau SDK yang tidak
    terpasang di CI bukan alasan mengecualikan modul."""
    argumen = _perintah_ruff().split()[2:]
    assert argumen[:2] == ["src/", "tests/"], argumen
    # Sesudahnya cuma boleh berkas di `scripts/` (dikecualikan pyproject, jadi disebut satu-satu).
    for berkas in argumen[2:]:
        assert berkas.startswith("scripts/") and (AKAR / berkas).is_file(), berkas


def test_ruff_tidak_dimatikan_lewat_exclude():
    """Kontrol negatif: melebarkan perintah tidak ada artinya kalau modulnya
    disembunyikan lewat `extend-exclude` di pyproject."""
    teks = (AKAR / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r"extend-exclude\s*=\s*\[([^\]]*)\]", teks)
    dikecualikan = re.findall(r'"([^"]+)"', m.group(1)) if m else []
    for nama in dikecualikan:
        assert not nama.startswith(("src", "tests")), nama


# ── image tidak memasang paket sendiri saat jalan ───────────────────────────


def test_image_mematikan_pip_install_ultralytics():
    """Ultralytics menjalankan `pip install` untuk paket yang dianggapnya kurang,
    saat model dimuat. Di pabrik itu menutupi `lap` yang hilang di satu line
    dan nyangkut tanpa internet. Nama variabelnya persis `YOLO_AUTOINSTALL`
    (nama lain diabaikan diam-diam, pernah terjadi di `build_engine.py`)."""
    teks = (AKAR / "Dockerfile").read_text(encoding="utf-8")
    baris_env = [b.strip() for b in teks.splitlines() if b.strip().startswith("ENV ")]
    assert "ENV YOLO_AUTOINSTALL=false" in baris_env, baris_env


def test_compose_tidak_menyalakan_lagi_autoinstall():
    """Kontrol negatif: variabel proses di compose menang atas ENV image."""
    for nama in ("docker-compose.yml", "docker-compose.prod.yml"):
        teks = (AKAR / nama).read_text(encoding="utf-8")
        assert "YOLO_AUTOINSTALL=true" not in teks.replace(" ", ""), nama
        assert "YOLO_AUTOINSTALL:true" not in teks.replace(" ", ""), nama
