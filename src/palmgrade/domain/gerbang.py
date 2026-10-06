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
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .working_day import JENDELA_KUNJUNGAN_DETIK, JENDELA_TANPA_KELUAR_DETIK

TERCATAT = "tercatat"
SUDAH_TERCATAT = "sudah_tercatat"
MASIH_DI_DALAM = "masih_di_dalam"
BELUM_TIMBANG_KOSONG = "belum_timbang_kosong"
SUDAH_KELUAR = "sudah_keluar"
TIDAK_ADA_TIKET = "tidak_ada_tiket"
#: "Batal datang" (2026-10-03): the waiting arrival is gone, or there was none to take back
#: (already claimed by a weigh-in, already cancelled, unknown id).
DIBATALKAN = "dibatalkan"
TIDAK_ADA = "tidak_ada"

#: The four stages of a visit, one per gate step (user 2026-10-02). The Timbangan table
#: shows one as a badge per row, coloured like its step header; the screen never works it out.
TAHAP_DATANG = "datang"
TAHAP_BONGKAR = "bongkar"
TAHAP_TIMBANG_KOSONG = "timbang_kosong"
TAHAP_SELESAI = "selesai"

#: How far back a weigh-in looks for its truck's arrival: a peak-season queue fits,
#: yesterday's turned-away truck is not read as a twenty-hour wait. The length of a
#: visit, one number for the whole console (`JENDELA_KUNJUNGAN_DETIK`).
JENDELA_KEDATANGAN = timedelta(seconds=JENDELA_KUNJUNGAN_DETIK)
#: How far back scan 4 looks for a ticket still waiting for its tare (the alarm it gives).
#: Same reasoning, same number.
JENDELA_KELUAR = timedelta(seconds=JENDELA_KUNJUNGAN_DETIK)
#: How long a WEIGHED-OUT ticket can still get its Keluar, from its weigh-out; after that the
#: visit is finished "tanpa scan 4" (user 2026-10-03). Why it differs: `JENDELA_TANPA_KELUAR_DETIK`.
JENDELA_TANPA_KELUAR = timedelta(seconds=JENDELA_TANPA_KELUAR_DETIK)

#: Console state key for the Scanner QR switch (support, 2026-10-05): "1" shows the four QR
#: fields on the Timbangan tab. Missing or anything else = off, the plate picker only.
KUNCI_SCANNER_QR = "setelan_scanner_qr"


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

    A visit finished "tanpa scan 4" (`tanpa_scan_4` set on the row, see
    `selesai_tanpa_scan_4`) has no leave time: its total runs to the weigh-out instead.
    """
    datang, masuk = tiket.get("arrived_at"), tiket.get("entered_at")
    akhir = tiket.get("left_at")
    if tiket.get("tanpa_scan_4"):
        akhir = tiket.get("exited_at") if _waktu_atau_none(tiket.get("exited_at")) else masuk
    return {
        "antre_menit": menit_antara(datang, masuk),
        "total_menit": menit_antara(datang or masuk, akhir),
        "tanpa_scan_1": bool(masuk) and not datang,
    }


def tahap_tiket(tiket: dict[str, Any]) -> str:
    """Where a ticket's truck is now, for the Status badge (standard L4).

    A ticket exists only after the weigh-in, so it is never "datang": a truck that scanned
    in and is not weighed in yet is an arrival, sent in `waiting`. A tare of 0 kg is still
    a tare: `None`, not falsy, means "not weighed out". A visit finished "tanpa scan 4"
    (the row's `tanpa_scan_4`, from `selesai_tanpa_scan_4`) is done without a leave time.
    """
    if tiket.get("left_at") or tiket.get("tanpa_scan_4"):
        return TAHAP_SELESAI
    if tiket.get("tare_kg") is not None:
        return TAHAP_TIMBANG_KOSONG
    return TAHAP_BONGKAR


def saat_timbang_kosong(tiket: dict[str, Any]) -> datetime | None:
    """When a weighed-out ticket was weighed out. The scale program may send a tare without
    `exited_at`, and a corrupt `exited_at` is no better: either way the weigh-in time stands in."""
    return _waktu_atau_none(tiket.get("exited_at")) or _waktu_atau_none(tiket.get("entered_at"))


def selesai_tanpa_scan_4(
    tiket: dict[str, Any], sekarang: datetime, kembali: Iterable[str | None] = ()
) -> bool:
    """A weighed-out ticket that never got its Keluar and now counts as finished (user 2026-10-03).

    Tared, not left, and either weighed out more than `JENDELA_TANPA_KELUAR` ago, or its
    truck was seen again after that weigh-out: `kembali` holds the times the same truck
    arrived (scan 1) or weighed in. Nothing is written: no `left_at` is made up, so a real
    gate time is never confused with a guessed one. An unreadable weigh-out time is not
    read as old: the Keluar button stays.
    """
    if tiket.get("left_at") or tiket.get("tare_kg") is None:
        return False
    keluar = saat_timbang_kosong(tiket)
    if keluar is None:
        return False
    if keluar < sekarang - JENDELA_TANPA_KELUAR:
        return True
    return any((saat := _waktu_atau_none(teks)) is not None and saat > keluar for teks in kembali)


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
    tiket: list[dict[str, Any]],
    at: str,
    jendela: timedelta | None = JENDELA_KELUAR,
    kembali: Iterable[str | None] = (),
) -> KeputusanKeluar:
    """Scan 4 → which ticket gets its leave time, or why none does.

    1. A ticket still waiting for its tare wins: the truck is leaving without its
       empty weighing, the alarm scan 4 exists for (D5). Nothing is written.
    2. Otherwise the newest weighed-out ticket without a leave time is closed.
    3. Otherwise, a weighed-out ticket that already has one, or that counts as finished
       "tanpa scan 4" (`selesai_tanpa_scan_4`, with `kembali`) → already left. So a new
       visit of the truck never closes the old one.
    4. Otherwise there is no ticket to close.

    `jendela` is the look-back for a ticket without a tare; a weighed-out one is looked
    for over `JENDELA_TANPA_KELUAR`. `jendela=None` switches both off: the per-row button
    names its ticket, and one past 24 h then answers "already left".
    """
    sekarang = baca_waktu(at)
    jendela_tara = None if jendela is None else JENDELA_TANPA_KELUAR
    kembali = list(kembali)
    terbuka: list[tuple[datetime | None, dict[str, Any]]] = []
    selesai: list[tuple[datetime | None, dict[str, Any]]] = []
    for row in tiket:
        if row.get("tare_kg") is None:
            waktu = _waktu_atau_none(row.get("entered_at"))
            if _baru(waktu, sekarang, jendela):
                terbuka.append((waktu, row))
        else:
            waktu = saat_timbang_kosong(row)
            if _baru(waktu, sekarang, jendela_tara):
                selesai.append((waktu, row))

    if terbuka:
        return KeputusanKeluar(BELUM_TIMBANG_KOSONG, _terbaru(terbuka))
    belum_pergi = [(w, row) for w, row in selesai
                   if not row.get("left_at") and not selesai_tanpa_scan_4(row, sekarang, kembali)]
    if belum_pergi:
        return KeputusanKeluar(TERCATAT, _terbaru(belum_pergi))
    if selesai:
        return KeputusanKeluar(SUDAH_KELUAR, _terbaru(selesai))
    return KeputusanKeluar(TIDAK_ADA_TIKET)


# ---- one scan field (user 2026-10-06) ----------------------------------------------------
#: The step a scan records, decided from the truck's state, never typed or picked.
LANGKAH_DATANG = "datang"
LANGKAH_ISI = "timbang_isi"
LANGKAH_KOSONG = "timbang_kosong"
LANGKAH_KELUAR = "keluar"
#: Two tickets of one truck wait for their tare: refused, the operator picks (2026-09-15).
GANDA = "ganda"
#: A scan this soon after the truck's previous step asks the operator first: a scanner that
#: reads one QR twice would otherwise record the next step (a weigh-in with whatever stands
#: on the bridge, or a weigh-out with the weigh-in's own weight).
JEDA_SCAN_ULANG = timedelta(minutes=3)
#: How long after its weigh-out a scan still means "this truck leaves now". A truck leaves the
#: bridge for the gate within minutes; one scanned hours later skipped its Keluar and is back
#: for a new visit, and closing the old ticket with this time would make up a gate time (rule
#: 37: a returning truck finishes the old visit "tanpa scan 4", nothing written).
JENDELA_SCAN_KELUAR = timedelta(hours=2)


@dataclass(frozen=True)
class Langkah:
    """What one scan should record. `weighing` is the ticket it is about (timbang_kosong,
    keluar), `pilihan` the open tickets of a `ganda`, `sebelumnya` when the truck's previous
    step happened (ISO text, for the double-read question)."""

    nama: str
    weighing: dict[str, Any] | None = None
    pilihan: tuple[dict[str, Any], ...] = ()
    sebelumnya: str | None = None


def putuskan_langkah(
    tiket: list[dict[str, Any]],
    kedatangan: list[dict[str, Any]],
    at: str,
    kembali: Iterable[str | None] = (),
) -> Langkah:
    """One truck's tickets and waiting arrivals → the step its scan records now.

    In this order, each reusing the rule its own lane already has:

    1. A ticket waiting for its tare inside the visit window → timbang kosong. Two of them →
       `ganda`, never a guess (same rule as the old exit scan).
    2. A weighed-out ticket not left, not finished "tanpa scan 4" (`putuskan_keluar`) and weighed
       out less than `JENDELA_SCAN_KELUAR` ago → keluar. Older: the truck is back, so datang.
    3. A waiting arrival a weigh-in now would claim → timbang isi (`pilih_kedatangan`).
    4. Otherwise a new visit → datang; `sebelumnya` is the newest leave time, so a double
       read right after Keluar does not open a new visit unasked.
    """
    sekarang = baca_waktu(at)
    terbuka = [
        (waktu, row) for row in tiket
        if row.get("tare_kg") is None
        and _baru(waktu := _waktu_atau_none(row.get("entered_at")), sekarang, JENDELA_KELUAR)
    ]
    if len(terbuka) > 1:
        urut = sorted(terbuka, key=lambda pasangan: pasangan[0] or _PALING_TUA, reverse=True)
        return Langkah(GANDA, pilihan=tuple(row for _, row in urut))
    if terbuka:
        row = terbuka[0][1]
        return Langkah(LANGKAH_KOSONG, row, sebelumnya=row.get("entered_at"))

    keluar = putuskan_keluar(tiket, at, kembali=kembali)
    if keluar.hasil == TERCATAT and keluar.weighing is not None:
        saat = saat_timbang_kosong(keluar.weighing)
        if saat is not None and saat >= sekarang - JENDELA_SCAN_KELUAR:
            return Langkah(LANGKAH_KELUAR, keluar.weighing, sebelumnya=saat.isoformat())

    datang = pilih_kedatangan(kedatangan, at)
    if datang is not None:
        return Langkah(LANGKAH_ISI, sebelumnya=datang.get("arrived_at"))

    pergi = [(w, row["left_at"]) for row in tiket if (w := _waktu_atau_none(row.get("left_at")))]
    return Langkah(LANGKAH_DATANG, sebelumnya=max(pergi)[1] if pergi else None)


def perlu_konfirmasi(langkah: Langkah, at: str) -> int | None:
    """Whole minutes since the truck's previous step when this scan must be confirmed first,
    else None. Never for keluar: a leave time recorded twice too early is harmless, and the
    exit gate is often right next to the bridge. A previous time in the future (a PC clock
    moved back) or unreadable is not a double read."""
    if langkah.nama not in (LANGKAH_DATANG, LANGKAH_ISI, LANGKAH_KOSONG):
        return None
    lalu, kini = _waktu_atau_none(langkah.sebelumnya), _waktu_atau_none(at)
    if lalu is None or kini is None or lalu > kini or kini - lalu >= JEDA_SCAN_ULANG:
        return None
    return menit_antara(langkah.sebelumnya, at)
