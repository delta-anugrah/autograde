"""Nama image yang diterbitkan dipatok, dan tidak pernah mengikuti nama repo.

Keputusan 2026-09-18: semuanya pindah ke **AutoGrade**, PC Lampung ikut, dan nama
lama `palmgrade-vision` **tidak dibawa-bawa lagi**.

Yang membuat berkas ini ada: kegagalannya senyap. PC Lampung membaca
`PALMGRADE_VISION_IMAGE` dari `/opt/palmgrade/vision/.env` miliknya sendiri, dan
updater-nya membandingkan nama itu dengan penanda `:latest` di bawah nama yang
sama. Kalau nama di workflow dan nama di `.env` tidak sama, `palmgrade pull
vision` menjawab "sudah terbaru" **selamanya** — nol error, pabrik cuma berhenti
menerima pembaruan, dan itu baru ketahuan saat ada yang bertanya kenapa versinya
tidak naik-naik.

Mesin itu tidak punya SSH masuk; `.env`-nya diedit tangan lewat AnyDesk. Jadi
urutannya wajib: **`.env` dulu, tag kemudian.**
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy.yml"

EXPECTED_IMAGE = "delta-anugrah/autograde"
"""Satu-satunya nama yang diterbitkan."""

NAMA_LAMA = "palmgrade-vision"
"""Dicabut 2026-09-18. Tidak boleh kembali diam-diam."""


def _teks() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _env_block() -> dict:
    # `on:` parses as the boolean True in YAML 1.1, which is harmless here since
    # only `env` is read.
    return yaml.safe_load(_teks())["env"]


def test_the_published_image_name_is_pinned():
    assert _env_block()["IMAGE_NAME"] == EXPECTED_IMAGE


def test_the_old_name_is_not_published_any_more():
    """Nama lama dicabut atas keputusan operator, bukan ditinggalkan.

    Kalau suatu saat dia kembali — misalnya disalin dari commit lama — itu
    artinya ada dua nama hidup bersamaan lagi, dan tidak ada yang tahu mesin
    mana menarik yang mana.
    """
    env = _env_block()
    assert NAMA_LAMA not in str(env.values()), f"{NAMA_LAMA} kembali di blok env"
    tags = re.search(r"tags:\s*\|(.*?)labels:", _teks(), re.S)
    assert tags, "blok tags tidak ditemukan"
    assert NAMA_LAMA not in tags.group(1), f"{NAMA_LAMA} masih ikut diterbitkan"


def test_the_version_and_the_latest_marker_are_both_published():
    """`:latest` itu penanda yang dibaca updater PC pabrik untuk tahu ada versi
    baru. Nama yang dapat `vX.Y.Z` tapi tidak dapat `:latest` menghasilkan image
    di registry yang tidak pernah ditemukan siapa pun."""
    teks = _teks()
    for tag in ("${{ github.ref_name }}", "latest"):
        baris = f"${{{{ env.REGISTRY }}}}/${{{{ env.IMAGE_NAME }}}}:{tag}"
        assert baris in teks, f"tag {tag} tidak diterbitkan"


def test_the_image_name_does_not_follow_the_repository_name():
    """`${{ github.repository }}` akan memindahkan image begitu repo diganti
    nama, dan memutus PC pabrik dengan cara senyap yang sama."""
    assert not re.search(r"IMAGE_NAME:\s*\$\{\{\s*github\.repository\s*\}\}", _teks())


def test_the_workflow_warns_that_the_env_must_move_first():
    """Urutan `.env` dulu, tag kemudian adalah satu-satunya hal yang mencegah
    pabrik kehilangan pembaruan saat rilis pertama. Itu harus terbaca di berkas
    yang diedit orangnya, bukan cuma di runbook yang mungkin tidak dibuka."""
    teks = _teks()
    assert "PALMGRADE_VISION_IMAGE" in teks, "workflow tidak menyebut env yang harus diedit"
    assert "AnyDesk" in teks, "tidak menyebut mesin itu diedit tangan"
