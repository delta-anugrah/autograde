"""Nama image yang diterbitkan tidak boleh mengikuti nama repo, dan nama lama
tidak boleh hilang sebelum PC pabrik pindah.

PC Lampung menarik `ghcr.io/delta-anugrah/palmgrade-vision` — namanya ada di
`/opt/palmgrade/vision/.env` di mesin itu, dan updater-nya membandingkannya
dengan penanda `:latest` di bawah nama yang sama.

Keputusan 2026-09-18: semuanya pindah ke **AutoGrade**, PC Lampung ikut. Tapi
perpindahannya tidak bisa sekali lompat: selama `.env` di mesin itu masih
menyebut nama lama, tag yang cuma terbit ke nama baru membuat `palmgrade pull
vision` menjawab "sudah terbaru" **selamanya** — nol error, dan pabrik diam-diam
berhenti menerima pembaruan. Jadi satu build menerbitkan DUA nama sampai `.env`
di sana diedit.

Berkas ini menjaga tiga hal yang masing-masing menutup kegagalan senyap:
nama baru dipatok, nama lama masih ikut terbit, dan keduanya tidak pernah
mengikuti `github.repository`.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy.yml"

EXPECTED_IMAGE = "delta-anugrah/autograde"
"""Nama yang ditarik tiap mesin baru."""

LEGACY_IMAGE = "delta-anugrah/palmgrade-vision"
"""Nama warisan. Dicabut begitu `.env` PC Lampung menyebut `autograde`."""


def _teks() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _env_block() -> dict:
    # `on:` parses as the boolean True in YAML 1.1, which is harmless here since
    # only `env` is read.
    return yaml.safe_load(_teks())["env"]


def test_the_published_image_name_is_pinned():
    assert _env_block()["IMAGE_NAME"] == EXPECTED_IMAGE


def test_the_legacy_name_is_still_published():
    """Selama `.env` PC Lampung belum diedit, nama lama WAJIB ikut terbit.

    Menghapusnya lebih dulu tidak menghasilkan error di mana pun: pabrik cuma
    berhenti menerima pembaruan, dan itu baru ketahuan saat ada yang bertanya
    kenapa versinya tidak naik-naik.
    """
    assert _env_block()["LEGACY_IMAGE"] == LEGACY_IMAGE


def test_both_names_get_the_version_and_the_latest_marker():
    """`:latest` itu penanda yang dibaca updater untuk tahu ada versi baru.

    Nama yang dapat `vX.Y.Z` tapi tidak dapat `:latest` akan punya image di
    registry yang tidak pernah ditemukan siapa pun.
    """
    teks = _teks()
    for nama in ("IMAGE_NAME", "LEGACY_IMAGE"):
        for tag in ("${{ github.ref_name }}", "latest"):
            baris = f"${{{{ env.REGISTRY }}}}/${{{{ env.{nama} }}}}:{tag}"
            assert baris in teks, f"{nama} tidak diterbitkan dengan tag {tag}"


def test_no_image_name_follows_the_repository_name():
    assert not re.search(r"IMAGE:\s*\$\{\{\s*github\.repository\s*\}\}", _teks()), (
        "mengganti nama repo akan memindahkan image dan memutus PC pabrik dari pembaruan"
    )
