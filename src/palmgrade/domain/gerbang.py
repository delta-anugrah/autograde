"""Truck gate times: scan 1 (arrive) and scan 4 (leave), decided 2026-09-30.

Both stay on the factory PC. AutoERP knows three stages (weigh-in, grading,
weigh-out) and neither of these is one of them, so they are never put in the
visit message: `domain/erp_messages.py` picks its fields one by one.

Only decisions and durations live here. The store fetches rows, these functions
choose, and `GateService` / `ConsoleService` write. Lookups use a time window,
not the working day: a queue can cross midnight.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .working_day import JENDELA_KUNJUNGAN_DETIK

TERCATAT = "tercatat"
SUDAH_TERCATAT = "sudah_tercatat"
MASIH_DI_DALAM = "masih_di_dalam"
BELUM_TIMBANG_KOSONG = "belum_timbang_kosong"
SUDAH_KELUAR = "sudah_keluar"
TIDAK_ADA_TIKET = "tidak_ada_tiket"

#: How far back a weigh-in looks for its truck's arrival: a peak-season queue fits,
#: yesterday's turned-away truck is not read as a twenty-hour wait. The length of a
#: visit, one number for the whole console (`JENDELA_KUNJUNGAN_DETIK`).
JENDELA_KEDATANGAN = timedelta(seconds=JENDELA_KUNJUNGAN_DETIK)
#: How far back scan 4 looks for the ticket it closes. Same reasoning, same number.
JENDELA_KELUAR = timedelta(seconds=JENDELA_KUNJUNGAN_DETIK)


def baca_waktu(teks: str) -> datetime:
    """ISO text → aware datetime. No offset is read as UTC, like `work_date_for`."""
    dt = datetime.fromisoformat(str(teks).strip().replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _waktu_atau_none(teks: str | None) -> datetime | None:
    if not teks:
        return None
    try:
        return baca_waktu(teks)
    except (ValueError, OverflowError):
        return None


def menit_antara(awal: str | None, akhir: str | None) -> int | None:
    """Whole minutes from one ISO time to another, half rounded up like the Lama column.

    The screen's Lama column uses JS `Math.round` (30 s is 1 minute); Python's `round`
    goes half to even (30 s is 0), so the rounding is spelled out here.

    None when either is missing or unreadable, or when the clock went backwards (a
    corrected time, an NTP jump): that is not a duration.
    """
    a, b = _waktu_atau_none(awal), _waktu_atau_none(akhir)
    if a is None or b is None or b < a:
        return None
    return math.floor((b - a).total_seconds() / 60 + 0.5)


def durasi_kunjungan(tiket: dict[str, Any]) -> dict[str, Any]:
    """Queue and total time of one ticket, for the Timbangan table (standard L4).

    Queue = arrive (scan 1) to weigh-in. Without scan 1 it is unknown, not zero:
    `tanpa_scan_1` says so, and the total then counts from the weigh-in (D4).
    """
    datang, masuk = tiket.get("arrived_at"), tiket.get("entered_at")
    return {
        "antre_menit": menit_antara(datang, masuk),
        "total_menit": menit_antara(datang or masuk, tiket.get("left_at")),
        "tanpa_scan_1": bool(masuk) and not datang,
    }


def pilih_kedatangan(
    calon: list[dict[str, Any]], entered_at: str, jendela: timedelta = JENDELA_KEDATANGAN
) -> dict[str, Any] | None:
    """The waiting arrival a weigh-in claims, or None when scan 1 was skipped.

    The newest arrival not after the weigh-in and not older than the window.
    """
    masuk = baca_waktu(entered_at)
    cocok: list[tuple[datetime, dict[str, Any]]] = []
    for row in calon:
        datang = _waktu_atau_none(row.get("arrived_at"))
        if datang is not None and masuk - jendela <= datang <= masuk:
            cocok.append((datang, row))
    if not cocok:
        return None
    return max(cocok, key=lambda pasangan: pasangan[0])[1]


def masih_menunggu(
    calon: list[dict[str, Any]], sekarang: datetime, jendela: timedelta = JENDELA_KEDATANGAN
) -> list[dict[str, Any]]:
    """The unclaimed arrivals a weigh-in now could still claim: the "Menunggu timbang" list.

    The same window as `pilih_kedatangan`, never the work date: a truck that arrived at
    23:50 is still waiting at 00:10, because its 00:10 weigh-in still claims it. A time
    later than now (a PC clock ahead) is kept, and so is an unreadable one: shown with an
    unknown wait, never hidden.
    """
    batas = sekarang - jendela
    hasil = []
    for row in calon:
        datang = _waktu_atau_none(row.get("arrived_at"))
        if datang is None or datang >= batas:
            hasil.append(row)
    return hasil


@dataclass(frozen=True)
class KeputusanKeluar:
    """What scan 4 should do. `weighing` is the ticket it is about, if any."""

    hasil: str
    weighing: dict[str, Any] | None = None


_PALING_TUA = datetime.min.replace(tzinfo=UTC)


def _baru(waktu: datetime | None, sekarang: datetime, jendela: timedelta | None) -> bool:
    """Inside the window. With no window the caller named the ticket, so even one
    without a readable time counts."""
    if jendela is None:
        return True
    if waktu is None:
        return False
    return waktu >= sekarang - jendela


def _terbaru(rows: list[tuple[datetime | None, dict[str, Any]]]) -> dict[str, Any]:
    return max(rows, key=lambda pasangan: pasangan[0] or _PALING_TUA)[1]


def putuskan_keluar(
    tiket: list[dict[str, Any]], at: str, jendela: timedelta | None = JENDELA_KELUAR
) -> KeputusanKeluar:
    """Scan 4 → which ticket gets its leave time, or why none does.

    1. A ticket still waiting for its tare wins: the truck is leaving without its
       empty weighing, the alarm scan 4 exists for (D5). Nothing is written.
    2. Otherwise the newest weighed-out ticket without a leave time is closed.
    3. Otherwise, a weighed-out ticket that already has one → already left.
    4. Otherwise there is no ticket to close.

    `jendela=None` switches the window off: the per-row button names its ticket.
    """
    sekarang = baca_waktu(at)
    terbuka: list[tuple[datetime | None, dict[str, Any]]] = []
    selesai: list[tuple[datetime | None, dict[str, Any]]] = []
    for row in tiket:
        if row.get("tare_kg") is None:
            waktu = _waktu_atau_none(row.get("entered_at"))
            if _baru(waktu, sekarang, jendela):
                terbuka.append((waktu, row))
        else:
            # The scale program may send a tare without `exited_at`, and a corrupt
            # `exited_at` is no better: either way the weigh-in time stands in.
            waktu = _waktu_atau_none(row.get("exited_at")) or _waktu_atau_none(row.get("entered_at"))
            if _baru(waktu, sekarang, jendela):
                selesai.append((waktu, row))

    if terbuka:
        return KeputusanKeluar(BELUM_TIMBANG_KOSONG, _terbaru(terbuka))
    belum_pergi = [(w, row) for w, row in selesai if not row.get("left_at")]
    if belum_pergi:
        return KeputusanKeluar(TERCATAT, _terbaru(belum_pergi))
    if selesai:
        return KeputusanKeluar(SUDAH_KELUAR, _terbaru(selesai))
    return KeputusanKeluar(TIDAK_ADA_TIKET)
