"""`scripts/tulis_sidik_image.py`: the file list a factory image carries about itself (2026-10-05).

The factory launcher (`autograde.sh`, `periksa_image`) checks a downloaded image before it
installs it: a power cut right after `docker pull` once left files at 0 bytes with no error
(Lampung, 2026-10-03). Python packages and system packages carry their own checksums (pip
RECORD, dpkg); our own code did not, so the image writes this list at build time.

The format is a contract with the launcher in the sawit workspace: `{"skema": 1, "berkas":
{absolute path: sha256 hex}}`.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

AKAR_REPO = Path(__file__).resolve().parents[2]
SCRIPT = AKAR_REPO / "scripts" / "tulis_sidik_image.py"
_spec = importlib.util.spec_from_file_location("tulis_sidik_image", SCRIPT)
tulis_sidik_image = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tulis_sidik_image)


def _sha(isi: bytes) -> str:
    return hashlib.sha256(isi).hexdigest()


def test_tiap_berkas_dengan_sha256_isinya_dan_jalur_mutlak(tmp_path):
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "a.py").write_bytes(b"print(1)\n")
    (tmp_path / "src" / "pkg" / "__init__.py").write_bytes(b"")
    (tmp_path / "entrypoint.sh").write_bytes(b"#!/bin/sh\n")

    berkas = tulis_sidik_image.sidik_berkas([tmp_path / "src"], [tmp_path / "entrypoint.sh"])

    assert berkas == {
        str(tmp_path / "src" / "pkg" / "a.py"): _sha(b"print(1)\n"),
        str(tmp_path / "src" / "pkg" / "__init__.py"): _sha(b""),
        str(tmp_path / "entrypoint.sh"): _sha(b"#!/bin/sh\n"),
    }


def test_cache_python_dan_symlink_dilewati(tmp_path):
    """Both change or point elsewhere at run time; neither is evidence of a broken image."""
    (tmp_path / "src" / "__pycache__").mkdir(parents=True)
    (tmp_path / "src" / "__pycache__" / "a.cpython-311.pyc").write_bytes(b"x")
    (tmp_path / "src" / "b.pyc").write_bytes(b"x")
    (tmp_path / "src" / "c.py").write_bytes(b"c")
    (tmp_path / "src" / "tautan").symlink_to(tmp_path / "src" / "c.py")

    berkas = tulis_sidik_image.sidik_berkas([tmp_path / "src"], [])

    assert list(berkas) == [str(tmp_path / "src" / "c.py")]


def test_folder_yang_tidak_ada_tidak_menggagalkan_build(tmp_path):
    assert tulis_sidik_image.sidik_berkas([tmp_path / "tidak-ada"], [tmp_path / "juga-tidak"]) == {}


def test_berkas_ditulis_dalam_bentuk_kontrak_launcher(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_bytes(b"a")
    keluaran = tmp_path / "out" / ".sidik-image.json"

    tulis_sidik_image.tulis(keluaran, [tmp_path / "src"], [])

    isi = json.loads(keluaran.read_text())
    assert isi == {"skema": 1, "berkas": {str(tmp_path / "src" / "a.py"): _sha(b"a")}}


def test_bawaan_mencakup_kode_aplikasi_dan_entrypoint():
    assert tulis_sidik_image.AKAR == ("/app/src", "/app/config", "/app/scripts")
    assert tulis_sidik_image.TAMBAHAN == ("/entrypoint.sh",)


def test_dockerfile_menulis_daftar_sesudah_berkas_terakhir_disalin():
    """Written before `COPY entrypoint.sh`, the list would miss the entrypoint (or name an
    old one). It must be the last thing that touches the files it lists."""
    baris = (AKAR_REPO / "Dockerfile").read_text().splitlines()
    tulis = next(i for i, b in enumerate(baris) if "scripts/tulis_sidik_image.py" in b)
    salinan = [i for i, b in enumerate(baris) if b.startswith(("COPY ", "ADD "))]

    assert baris[tulis].startswith("RUN python scripts/tulis_sidik_image.py")
    assert tulis > max(salinan)
