#!/usr/bin/env python3
"""Bikin hash sandi untuk akun bawaan konsol (Fase 4).

    make hash-sandi

Dipakai waktu pasang PC pabrik: sandinya beda per PKS, dan yang masuk ke image atau
`.env` cuma hash-nya — sandi mentah tidak pernah ditanam. PC pabrik bisa diakses lewat
AnyDesk dan layer image bisa dibaca siapa pun yang pegang image-nya, jadi satu sandi
yang ikut tertanam berarti semua pabrik kebuka sekaligus.

Sandinya diminta interaktif, jadi tidak nyangkut di history shell maupun daftar proses.
Catat sandinya di catatan internal (1Password/sejenisnya) — hash ini tidak bisa
dibalik, jadi sandi yang hilang berarti akunnya harus dibuat ulang dengan
`make operator`.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

# scripts/ bukan package, dan image tidak menyetel PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palmgrade.domain.operator_auth import check_password_format, hash_password  # noqa: E402
from palmgrade.domain.operator_error import OperatorError  # noqa: E402
from palmgrade.services.akun_bawaan import EMAIL_BAWAAN, EMAIL_SUPPORT  # noqa: E402


def main() -> int:
    print("Hash sandi akun bawaan konsol AutoGrade")
    print(f"  {EMAIL_BAWAAN:<28} akun operator pabrik")
    print(f"  {EMAIL_SUPPORT:<28} akun support (developer)")
    print()

    sandi = getpass.getpass("Sandi (minimal 8 karakter): ")
    ulang = getpass.getpass("Ulangi sandi: ")
    if sandi != ulang:
        print("Gagal: sandi kedua tidak sama dengan yang pertama", file=sys.stderr)
        return 1
    try:
        check_password_format(sandi)
    except OperatorError as exc:
        print(f"Gagal: {exc}", file=sys.stderr)
        return 1

    hash_sandi = hash_password(sandi)
    print()
    print("Hash-nya (simpan ini, bukan sandinya):")
    print()
    print(f"  {hash_sandi}")
    print()
    print("Pakai di salah satu dari dua tempat:")
    print()
    print("  1. Waktu build image (sandi tidak pernah masuk ke image):")
    print(f"     docker build --build-arg CONSOLE_DEFAULT_HASH='{hash_sandi}' .")
    print()
    print("  2. Di .env PC pabrik — ⚠️ compose memakan `$`, jadi tulis `$$`:")
    print(f"     CONSOLE_DEFAULT_HASH={hash_sandi.replace('$', '$$')}")
    print()
    print("Untuk akun support, pakai CONSOLE_SUPPORT_HASH dengan sandi yang berbeda.")
    print("Catat sandinya di catatan internal: hash ini tidak bisa dibalik.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
