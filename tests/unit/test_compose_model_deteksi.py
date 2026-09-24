"""Konsol harus bisa MELIHAT folder model dan engine, read-only, di dua compose.

Layar Model Deteksi membaca `models/release/` (kelas tiap `.pt`) dan
`engines/` (engine per GPU). Di `docker-compose.yml` dev keduanya kebetulan
ikut `.:/app`; di `docker-compose.prod.yml` — yang dipakai PC pabrik —
`volumes: !override` MENGGANTI seluruh daftar dan tidak ada `.:/app`. Tanpa
mount eksplisit layar itu kosong di pabrik tanpa satu pun error: folder yang
tidak ada dibaca sebagai "tidak ada model".

`:ro` wajib. Konsol memilih model, tidak pernah menulisnya.

Dibaca sebagai teks: berkas `prod` memakai tag Compose (`!override`) yang
membuat PyYAML berhenti.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BERKAS = [REPO_ROOT / "docker-compose.yml", REPO_ROOT / "docker-compose.prod.yml"]
WAJIB = ("./models:/app/models:ro", "./engines:/app/engines:ro")


def _volume_konsol(berkas: Path) -> list[str]:
    baris = berkas.read_text(encoding="utf-8").splitlines()
    mulai = next(n for n, b in enumerate(baris) if re.match(r"^\s{2}console:\s*$", b))
    hasil: list[str] = []
    di_volumes = False
    for b in baris[mulai + 1 :]:
        isi = b.strip()
        indent = len(b) - len(b.lstrip())
        if isi and not isi.startswith("#") and indent <= 2:
            break  # service berikutnya
        if re.match(r"^\s{4}volumes:", b):
            di_volumes = True
            continue
        if di_volumes:
            if isi.startswith("- "):
                hasil.append(isi[2:].strip())
            elif isi and not isi.startswith("#") and indent <= 4:
                di_volumes = False
    return hasil


@pytest.mark.parametrize("berkas", BERKAS, ids=lambda p: p.name)
def test_konsol_me_mount_models_dan_engines_read_only(berkas):
    volume = _volume_konsol(berkas)
    assert volume, f"blok volumes konsol tidak ditemukan di {berkas.name}"
    for mount in WAJIB:
        assert mount in volume, f"{berkas.name}: konsol tidak me-mount {mount}"


@pytest.mark.parametrize("berkas", BERKAS, ids=lambda p: p.name)
def test_konsol_tidak_bisa_menulis_models(berkas):
    for v in _volume_konsol(berkas):
        if v.startswith(("./models:", "./engines:")):
            assert v.endswith(":ro"), f"{berkas.name}: {v} harus read-only"
