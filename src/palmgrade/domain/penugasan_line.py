"""Automatic line assignment (decided 2026-10-01): one truck on the lines at a time.

A new ticket (weigh-in, scan 2) puts its truck on the chosen lines when they are free.
While any of them still holds a truck that has not been weighed out, the new truck waits
in the unloading queue, oldest weigh-in first. The weigh-out (scan 3) and a manual
Lepas free the lines, and the next truck goes on.

Pure rules only: the setting, which lines are free, and whether they are still busy.
The service asks the lines (rule 13: the line accepts first) and the store records.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from .operator_error import LINE_TIDAK_DIKENAL, PENUGASAN_TANPA_LINE, InvalidInput
from .working_day import JENDELA_KUNJUNGAN_DETIK

#: sync_state key. The `setelan_` prefix keeps it through a Danger Zone wipe, like the
#: grading settings (`domain/bahaya.py`, `_AWALAN_SETELAN`).
KUNCI_PENUGASAN = "setelan_penugasan_line"

#: How far back a weighed-in ticket still counts as waiting for the lines. It is the
#: length of a visit (one number, `JENDELA_KUNJUNGAN_DETIK`): long enough for a slow
#: shift, short enough that yesterday's forgotten ticket never lands on today's lines.
JENDELA_ANTREAN_BONGKAR = timedelta(seconds=JENDELA_KUNJUNGAN_DETIK)


@dataclass(frozen=True)
class SetelanPenugasan:
    aktif: bool
    lines: tuple[str, ...]


def setelan_bawaan(line_dikenal: list[str]) -> SetelanPenugasan:
    """Off, every configured line chosen: an update never changes how a mill works on
    the day it lands (decision D13)."""
    return SetelanPenugasan(aktif=False, lines=tuple(line_dikenal))


def baca_setelan(tersimpan: str | None, line_dikenal: list[str]) -> SetelanPenugasan:
    """The stored setting, or the default. A line no longer configured is dropped; a
    setting left with no line, or with an `aktif` that is not JSON true, reads as off.

    Never raises: the `state()` poll reads it every 2 s, so text that is not JSON, JSON
    that is not an object, or a `lines` of the wrong shape all fall back instead.
    """
    if not tersimpan:
        return setelan_bawaan(line_dikenal)
    try:
        nilai = json.loads(tersimpan)
    except ValueError:
        return setelan_bawaan(line_dikenal)
    if not isinstance(nilai, dict):
        return setelan_bawaan(line_dikenal)
    daftar = nilai.get("lines")
    pilihan = {kode for kode in daftar if isinstance(kode, str)} if isinstance(daftar, list) else set()
    lines = tuple(kode for kode in line_dikenal if kode in pilihan)
    # Only a real JSON true turns it on: `bool("false")` is True, and anything this code
    # did not write must read as the safe default, off (D13).
    return SetelanPenugasan(aktif=nilai.get("aktif") is True and bool(lines), lines=lines)


def bersihkan_setelan_penugasan(
    aktif: bool | None, lines: list[str] | None, line_dikenal: list[str]
) -> SetelanPenugasan:
    """What support saved, checked. The order follows the configured lines, not the
    click order, so the toast and the card order agree."""
    pilihan = list(lines or [])
    asing = [kode for kode in pilihan if kode not in line_dikenal]
    if asing:
        raise InvalidInput(LINE_TIDAK_DIKENAL, f"line tidak dikenal: {asing[0]}", line=asing[0])
    urut = tuple(kode for kode in line_dikenal if kode in set(pilihan))
    if aktif and not urut:
        raise InvalidInput(PENUGASAN_TANPA_LINE, "penugasan otomatis butuh minimal satu line")
    return SetelanPenugasan(aktif=bool(aktif), lines=urut)


def simpan_teks(setelan: SetelanPenugasan) -> str:
    return json.dumps({"aktif": setelan.aktif, "lines": list(setelan.lines)})


def line_bebas(lines: tuple[str, ...] | list[str], pegangan: dict[str, dict[str, Any]]) -> list[str]:
    """The chosen lines that hold no truck right now, in the chosen order."""
    return [kode for kode in lines if not (pegangan.get(kode) or {}).get("truck_id")]


def line_sibuk(
    lines: tuple[str, ...] | list[str], pegangan: dict[str, dict[str, Any]], truk_terbuka: set[str]
) -> bool:
    """True when a chosen line still holds a truck that has not been weighed out.

    That truck is still being sorted: putting the next one on now would stamp its
    remaining bunches with the wrong truck (decision D10). A line holding a truck that
    already weighed out (its release failed) does not block: it is simply not free.
    """
    return any((pegangan.get(kode) or {}).get("truck_id") in truk_terbuka for kode in lines)


def menit_menunggu(sejak_epoch: float, sekarang_epoch: float) -> int:
    """Whole minutes a ticket has waited for the lines, never negative."""
    return max(0, int((sekarang_epoch - sejak_epoch) // 60))
