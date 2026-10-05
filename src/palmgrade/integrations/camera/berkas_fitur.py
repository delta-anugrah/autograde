"""Which `.mfs` the camera gets at each connect (spec §3.1).

1. `<CAMERA_SETELAN_DIR>/<line_code>.mfs` when it exists: what support saved from the console last.
2. Else the configured file (`CAMERA_FEATURE_FILE`, from `LINE_n_FEATURE_FILE`): the baseline that
   "Kembalikan ke baku" returns to (`models/01102026.mfs` at Lampung, the baked file elsewhere).

Chosen again at every connect, so a file saved while the line runs is used from the next reconnect.
"""

from __future__ import annotations

from pathlib import Path


def berkas_tersimpan(folder: Path | None, line_code: str) -> Path | None:
    """Where this line's saved settings live; None while `CAMERA_SETELAN_DIR` is not set."""
    return None if folder is None else folder / f"{line_code}.mfs"


def pilih_berkas_fitur(folder: Path | None, line_code: str, baku: str | None) -> str | None:
    simpanan = berkas_tersimpan(folder, line_code)
    if simpanan is not None and simpanan.is_file():
        return str(simpanan)
    return baku
