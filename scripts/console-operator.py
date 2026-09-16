#!/usr/bin/env python3
"""Local operator accounts for the console login (Fase 4).

    make operator                        add a local account, or reset a forgotten
                                          password — role `operator` unless PERAN=support
    make operator PERAN=support          same, but the account can open the developer
                                          screens
    make operator AKSI=daftar            list the active accounts and where each came from
    make operator AKSI=matikan           switch one off; their sessions end at once
    make operator AKSI=peran PERAN=support
                                          change an EXISTING account's role, without
                                          touching its password

Only **local** accounts are managed here — the built-in one and the support account,
which exist so a mill that has never reached the internet can still be opened. The real
accounts come from AutoERP (`AutoGrade Operator`) and are reset there; this command
refuses to touch them, because the next pull would undo the change anyway.

On the factory PC the console runs in Docker: use `make operator-docker` with the same
AKSI/PERAN. It runs inside the console container, against the database that console
actually reads — the native command there would write a file the container never opens.

Email, name and password are asked for interactively, so the password never lands in
shell history. PERAN is not a secret, so it travels the same way AKSI does: a Makefile
variable substituted straight into the command line.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

# scripts/ is not a package and the image sets no PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palmgrade.core.config import Settings  # noqa: E402
from palmgrade.domain.peran import PERAN_OPERATOR  # noqa: E402
from palmgrade.repositories.console_repository import ConsoleStore  # noqa: E402
from palmgrade.services.operator_admin import OperatorAdmin  # noqa: E402


def main(argv: list[str]) -> int:
    aksi = argv[1] if len(argv) > 1 else "tambah"
    # Never trusted as-is: OperatorAdmin validates through domain.peran.peran_sah,
    # so a typo here lands on `operator`, not on whatever was typed.
    peran = argv[2] if len(argv) > 2 else PERAN_OPERATOR
    settings = Settings()
    admin = OperatorAdmin(ConsoleStore(settings.console_db_path))
    # Printed every time: writing the right accounts into the wrong file is the one
    # mistake this command makes silently.
    print(f"Database konsol: {settings.console_db_path}")

    try:
        if aksi == "tambah":
            email = input("Email operator: ")
            full_name = input("Nama operator: ")
            sandi = getpass.getpass("Sandi (minimal 8 karakter): ")
            ulang = getpass.getpass("Ulangi sandi: ")
            _, disahkan = admin.add_or_reset(email, full_name, sandi, ulang, peran=peran)
            print("Tersimpan. Sesi lama operator ini, kalau ada, sudah diakhiri.")
            print(f"Peran: {disahkan}")
        elif aksi == "daftar":
            rows = admin.listing()
            for row in rows:
                # `origin` is the answer to "why will this password not change?" —
                # an `erp` account is backoffice's to reset, not this PC's.
                print(f"  {row['email']:<32} {row['full_name']:<24} [{row['origin']}]")
            if not rows:
                print("  (belum ada operator aktif)")
        elif aksi == "matikan":
            admin.switch_off(input("Email operator yang dimatikan: "))
            print("Dimatikan. Sesinya berakhir sekarang juga.")
        elif aksi == "peran":
            email = input("Email operator: ")
            disahkan = admin.set_peran(email, peran)
            print(f"Peran diubah jadi: {disahkan}")
        else:
            print(
                f"Aksi tidak dikenal: {aksi} (tambah | daftar | matikan | peran)",
                file=sys.stderr,
            )
            return 2
    except ValueError as exc:
        print(f"Gagal: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
