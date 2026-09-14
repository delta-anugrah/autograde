#!/usr/bin/env python3
"""Operator accounts for the console login (Fase 4).

    make operator                  add an operator, or reset a forgotten PIN
    make operator AKSI=daftar      list the active operators
    make operator AKSI=matikan     switch one off; their sessions end at once

On the factory PC the console runs in Docker: use `make operator-docker` with the same
AKSI. It runs inside the console container, against the database that console actually
reads — the native command there would write a file the container never opens.

Name and PIN are asked for interactively, so the PIN never lands in shell history.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

# scripts/ is not a package and the image sets no PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palmgrade.core.config import Settings  # noqa: E402
from palmgrade.repositories.console_repository import ConsoleStore  # noqa: E402
from palmgrade.services.operator_admin import OperatorAdmin  # noqa: E402


def main(argv: list[str]) -> int:
    aksi = argv[1] if len(argv) > 1 else "tambah"
    settings = Settings()
    admin = OperatorAdmin(ConsoleStore(settings.console_db_path))
    # Printed every time: writing the right accounts into the wrong file is the one
    # mistake this command makes silently.
    print(f"Database konsol: {settings.console_db_path}")

    try:
        if aksi == "tambah":
            nama = input("Nama operator: ")
            pin = getpass.getpass("PIN (6 angka): ")
            ulang = getpass.getpass("Ulangi PIN: ")
            admin.add_or_reset(nama, pin, ulang)
            print("Tersimpan. Sesi lama operator ini, kalau ada, sudah diakhiri.")
        elif aksi == "daftar":
            rows = admin.listing()
            for row in rows:
                print(f"  {row['nama']}")
            if not rows:
                print("  (belum ada operator aktif)")
        elif aksi == "matikan":
            admin.switch_off(input("Nama operator yang dimatikan: "))
            print("Dimatikan. Sesinya berakhir sekarang juga.")
        else:
            print(f"Aksi tidak dikenal: {aksi} (tambah | daftar | matikan)", file=sys.stderr)
            return 2
    except ValueError as exc:
        print(f"Gagal: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
