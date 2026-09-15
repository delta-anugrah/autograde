#!/usr/bin/env python3
"""Bikin hash sandi untuk dua akun bawaan konsol (Fase 4).

    make hash-sandi

Dipakai sekali per PKS waktu pasang PC pabrik. Menanyakan **dua** sandi sekaligus,
yaitu operator pabrik dan support, karena keduanya memang harus berbeda. Menyerahkan itu
ke ingatan orang yang sedang mengerjakan sepuluh hal lain adalah cara paling rapi untuk
berakhir dengan dua akun bersandi sama.

Yang masuk ke image atau `.env` cuma **hash**-nya. Sandi mentah tidak pernah ditanam: PC
pabrik bisa diakses lewat AnyDesk dan layer image bisa dibaca siapa pun yang pegang
image-nya, jadi satu sandi yang ikut tertanam berarti semua pabrik terbuka sekaligus.

Sandinya diminta interaktif, jadi tidak nyangkut di history shell maupun daftar proses.
Catat sandinya di catatan internal (1Password/sejenisnya): hash ini tidak bisa dibalik,
jadi sandi yang hilang berarti akunnya harus dibuat ulang dengan `make operator`
langsung di PC-nya.
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

_AKUN = (
    ("operator pabrik", EMAIL_BAWAAN, "CONSOLE_DEFAULT_HASH"),
    ("support (developer)", EMAIL_SUPPORT, "CONSOLE_SUPPORT_HASH"),
)


def _tanya_sandi(sebutan: str, email: str) -> str | None:
    """Satu sandi, diketik dua kali. None kalau ditolak."""
    print()
    print(f"Sandi akun {sebutan}: {email}")
    sandi = getpass.getpass("  Sandi (minimal 8 karakter): ")
    ulang = getpass.getpass("  Ulangi sandi: ")
    if sandi != ulang:
        print("Gagal: sandi kedua tidak sama dengan yang pertama", file=sys.stderr)
        return None
    try:
        check_password_format(sandi)
    except OperatorError as exc:
        print(f"Gagal: {exc}", file=sys.stderr)
        return None
    return sandi


def main() -> int:
    print("Hash sandi akun bawaan konsol AutoGrade")
    print("Dua akun, dua sandi berbeda. Catat sandinya di catatan internal:")
    print("hash tidak bisa dibalik.")

    sandi = {}
    for sebutan, email, variabel in _AKUN:
        nilai = _tanya_sandi(sebutan, email)
        if nilai is None:
            return 1
        sandi[variabel] = nilai

    # Sandi yang sama untuk dua akun berarti jalur masuk developer sama dengan jalur
    # operator, dan operator pabrik tahu sandinya. Ditolak, bukan sekadar diperingatkan.
    if len(set(sandi.values())) != len(sandi):
        print(
            "Gagal: sandi operator dan support tidak boleh sama. "
            "Kalau sama, satu bocor membuka dua-duanya.",
            file=sys.stderr,
        )
        return 1

    # Hanya dua akun dan hash-nya. Yang dicetak di sini disalin orang ke `.env` atau ke
    # perintah build, jadi tiap baris tambahan cuma menambah peluang salah salin.
    for sebutan, email, variabel in _AKUN:
        hash_sandi = hash_password(sandi[variabel])
        print()
        print(f"[{sebutan}] {email}")
        print(f"  docker build --build-arg {variabel}='{hash_sandi}' .")
        # Compose memakan `$`, jadi satu `$` ditulis `$$`. Hash yang terpotong di `$`
        # pertama menghasilkan akun yang tidak bisa dibuka siapa pun.
        print(f"  {variabel}={hash_sandi.replace('$', '$$')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
