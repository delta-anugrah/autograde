"""`APP_VERSION` di-bake ke image; compose tidak boleh menimpanya.

Dockerfile mengisi `ENV APP_VERSION=<tag>` saat build (deploy.yml mengirim
`github.ref_name`). Begitu compose menyebut `APP_VERSION` di daftar
`environment:`, nilai itu MENANG atas yang di-bake — dan karena bentuknya
`${APP_VERSION:-unknown}`, PC pabrik yang `.env`-nya tidak memuat variabel itu
(tidak ada yang mengisinya; `.env` diedit tangan lewat AnyDesk) menampilkan
`unknown` selamanya.

Gejalanya cuma kosmetik sampai support membuka layar Versi lewat AnyDesk untuk
menjawab "PC ini versi berapa?" dan jawabannya tidak pernah ada.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "docker-compose.yml"
COMPOSE_PROD = REPO_ROOT / "docker-compose.prod.yml"

#: Baris `environment:` yang menyetel APP_VERSION — dengan atau tanpa default.
_SETEL_APP_VERSION = re.compile(r"^\s*-\s*APP_VERSION\s*=", re.M)


def test_compose_dasar_tidak_menimpa_app_version():
    isi = COMPOSE.read_text(encoding="utf-8")
    assert not _SETEL_APP_VERSION.search(isi), (
        "docker-compose.yml menyetel APP_VERSION dan menimpa nilai yang di-bake "
        "ke image — layar Versi akan selalu 'unknown' di PC pabrik"
    )


def test_compose_prod_tidak_menimpa_app_version():
    # Override MENGGANTI blok `environment:` dasar, bukan menambahinya, jadi
    # membuangnya di satu berkas saja tidak cukup.
    isi = COMPOSE_PROD.read_text(encoding="utf-8")
    assert not _SETEL_APP_VERSION.search(isi), (
        "docker-compose.prod.yml menyetel APP_VERSION dan menimpa nilai image"
    )


def test_dockerfile_tetap_membake_app_version():
    """Kontrol negatif: membuang baris compose cuma benar selama image-nya
    memang membawa versinya sendiri."""
    isi = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG APP_VERSION" in isi
    assert "ENV APP_VERSION=${APP_VERSION}" in isi


def test_workflow_tetap_mengirim_tag_saat_build():
    """Kontrol negatif kedua: yang mengisi nilainya adalah CI."""
    isi = (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    assert "APP_VERSION=${{ github.ref_name }}" in isi
