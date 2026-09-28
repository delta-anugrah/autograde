"""Membandingkan secret mesin: waktu tetap, dan gagal tertutup.

Satu aturan untuk semua lane mesin (konsol ke line, line ke konsol, program
timbangan ke konsol). `!=` membocorkan panjang awalan yang cocok lewat waktu
jawab; `hmac.compare_digest` tidak. Secret yang KOSONG di server tidak pernah
membuka apa pun: `compare_digest(b"", b"")` bernilai True, dan `.env` yang
menulis `WEBHOOK_SECRET=` tanpa nilai tidak boleh berarti pintu terbuka.
"""
from __future__ import annotations

import hmac


def rahasia_cocok(diberikan: str | None, harapan: str) -> bool:
    if not harapan or diberikan is None:
        return False
    return hmac.compare_digest(diberikan.encode("utf-8"), harapan.encode("utf-8"))
