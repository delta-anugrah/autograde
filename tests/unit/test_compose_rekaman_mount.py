"""Folder `videos/` harus di-mount ke tiap line, di dasar DAN di prod.

Tanpa mount, rekaman mendarat di dalam container dan hilang begitu container
dibuat ulang — layar bilang "tersimpan", berkasnya tidak pernah ada di PC
pabrik. Nol galat di mana pun.

⚠️ `docker-compose.prod.yml` memakai `!override`, yang MENGGANTI seluruh daftar
`volumes:` sebuah service, bukan menambahinya. Mount yang cuma ditulis di berkas
dasar akan hilang di pabrik — jebakan yang sudah pernah memakan waktu di sini
(lihat komentar di prod tentang blok `console`).
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DASAR = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
PROD_TEKS = (REPO_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
# `!override` bukan tag YAML standar; dibuang supaya berkasnya bisa di-parse.
PROD = yaml.safe_load(PROD_TEKS.replace("!override", ""))

LINE = ("ripe-line-1", "ripe-line-2", "ripe-line-3")


def _mounts(doc: dict, service: str) -> list[str]:
    return [str(v) for v in (doc.get("services", {}).get(service, {}).get("volumes") or [])]


def _env(doc: dict, service: str) -> list[str]:
    return [str(e) for e in (doc.get("services", {}).get(service, {}).get("environment") or [])]


def test_tiap_line_memount_videos_di_dasar():
    for svc in LINE:
        assert any("videos" in v for v in _mounts(DASAR, svc)), svc


def test_tiap_line_memount_videos_di_prod():
    """Override mengganti daftarnya, jadi mount WAJIB ditulis ulang di sini."""
    for svc in LINE:
        mounts = _mounts(PROD, svc)
        assert mounts, f"{svc} tidak punya blok volumes di prod"
        assert any("videos" in v for v in mounts), svc


def test_videos_dir_disetel_di_dasar():
    """Mount saja tidak cukup: tanpa `REKAMAN_DIR` recorder menulis ke jalur
    bawaan di dalam container, bukan ke folder yang baru saja di-mount."""
    for svc in LINE:
        assert any(e.startswith("REKAMAN_DIR=") for e in _env(DASAR, svc)), svc


def test_line_menulis_bukan_read_only():
    """`:ro` di sini membuat rekaman gagal senyap — recorder menangkap OSError
    dan line tetap jalan, jadi tidak ada yang tahu sampai berkasnya dicari."""
    for svc in LINE:
        for v in _mounts(DASAR, svc):
            if "videos" in v:
                assert not v.endswith(":ro"), f"{svc}: {v}"


def test_konsol_tidak_memount_videos():
    """Konsol cuma mengirim perintah; yang menulis berkas line. Mount di konsol
    akan menyiratkan konsol ikut menulis dan mengundang kode yang salah."""
    assert not any("videos" in v for v in _mounts(DASAR, "console"))
