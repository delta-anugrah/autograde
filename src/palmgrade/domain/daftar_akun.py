"""Satu baris akun untuk layar Akun (support) — murni, tanpa I/O.

Layar itu cuma MEMBACA. Akun lokal dibuat di PC itu sendiri
(`scripts/console-operator.py`), akun AutoERP di AutoERP; tidak ada lane web
untuk mengubah akun (aturan 19 CLAUDE.md).

Kolom yang keluar ditulis satu per satu, bukan meneruskan baris apa adanya:
jawabannya keluar dari proses sebagai JSON, dan hash sandi — atau kolom apa pun
yang kelak ditambah ke tabel `operators` — tidak boleh ikut tanpa sengaja. Sandi
aslinya memang tidak bisa dibaca dari hash, tapi hash yang bocor bisa ditebak di
luar pabrik tanpa batas percobaan.
"""
from __future__ import annotations

from typing import Any

from .operator_auth import lockout_seconds_left

AKTIF = "aktif"
MATI = "mati"
TERKUNCI = "terkunci"


def ringkas_akun(baris: dict[str, Any], *, now: float) -> dict[str, Any]:
    """Baris `ConsoleStore.akun_untuk_support` → bentuk yang dibaca layar.

    `keadaan` memakai aturan kunci yang SAMA dengan layar login
    (`lockout_seconds_left`), jadi "terkunci" di sini berarti orang itu memang
    sedang ditolak di pintu masuk. Mati mengalahkan terkunci: akun mati tidak
    bisa masuk sama sekali, dan menulis "terkunci 3 menit" menyuruh orang
    menunggu hal yang tidak akan terjadi.
    """
    tunggu = lockout_seconds_left(
        int(baris.get("fail_count") or 0),
        last_failed_at=baris.get("last_failed_at"),
        now=now,
    )
    if baris.get("status") != "active":
        keadaan = MATI
    elif tunggu > 0:
        keadaan = TERKUNCI
    else:
        keadaan = AKTIF
    return {
        "email": baris["email"],
        "nama": baris["full_name"],
        "role": baris["role"],
        # `erp` / `lokal` — menentukan di mana sandinya diganti kalau lupa.
        "asal": baris["origin"],
        "keadaan": keadaan,
        "terkunci_detik": tunggu if keadaan == TERKUNCI else 0,
        "sedang_masuk": int(baris.get("sesi_aktif") or 0) > 0,
        "dibuat": baris.get("created_at"),
    }
