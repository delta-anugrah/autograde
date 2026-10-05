"""Write the list of our own files, with their sha256, into the image being built.

    RUN python scripts/tulis_sidik_image.py /app/.sidik-image.json

The factory launcher checks a downloaded image before it installs it (`periksa_image` in
`autograde.sh`, sawit workspace): on 2026-10-03 a power cut right after `docker pull` left
files at 0 bytes in Lampung, and Docker reported nothing. Python and system packages carry
their own checksums (pip RECORD, dpkg); our own code does not, so the image carries this.

Format, a contract with that launcher: `{"skema": 1, "berkas": {absolute path: sha256 hex}}`.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path

#: Folders of our own code in the image, and single files outside them.
AKAR = ("/app/src", "/app/config", "/app/scripts")
TAMBAHAN = ("/entrypoint.sh",)
SKEMA = 1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for potong in iter(lambda: f.read(1 << 20), b""):
            h.update(potong)
    return h.hexdigest()


def sidik_berkas(akar: Iterable[Path | str], tambahan: Iterable[Path | str]) -> dict[str, str]:
    """Path → sha256 for every regular file under `akar` plus `tambahan`.

    Python caches and symlinks are left out: both change or point elsewhere at run time,
    and neither says anything about whether the image arrived whole.
    """
    berkas: dict[str, str] = {}
    for folder in akar:
        for r, dirs, names in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for n in sorted(names):
                p = Path(r) / n
                if p.is_symlink() or n.endswith((".pyc", ".pyo")):
                    continue
                berkas[str(p)] = _sha256(p)
    for p in map(Path, tambahan):
        if p.is_file() and not p.is_symlink():
            berkas[str(p)] = _sha256(p)
    return berkas


def tulis(keluaran: Path | str, akar: Iterable[Path | str] = AKAR, tambahan: Iterable[Path | str] = TAMBAHAN) -> int:
    """Write the list to `keluaran`; returns how many files it names."""
    berkas = sidik_berkas(akar, tambahan)
    keluaran = Path(keluaran)
    keluaran.parent.mkdir(parents=True, exist_ok=True)
    keluaran.write_text(json.dumps({"skema": SKEMA, "berkas": berkas}, indent=0, sort_keys=True) + "\n")
    return len(berkas)


if __name__ == "__main__":
    tujuan = sys.argv[1] if len(sys.argv) > 1 else "/app/.sidik-image.json"
    print(f"{tulis(tujuan)} files listed in {tujuan}")
