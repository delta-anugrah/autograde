"""Mill working-day boundary (plan §6.1).

The mill runs ~20 hours a day and ACROSS midnight. A UTC day boundary cuts one
shift into two dates, so `work_date` is derived from the event's own
timestamp at ingest and then STORED as a column - never derived from
`creation`, `now()`, or a folder name. A late event (outbox retry after a power
cut) still lands on its own day.

Free of heavy dependencies so it can be tested without a camera or torch.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, time, timedelta, tzinfo

from .operator_error import CUTOFF_TIDAK_SAH, InvalidInput

#: A visit, weigh-in to release, never lasts longer; the work date flips at midnight, this does not.
JENDELA_KUNJUNGAN_DETIK = 12 * 60 * 60
#: How long a ticket that HAS its tare waits for its Keluar (scan 4) before the visit counts
#: as finished "tanpa scan 4" (user 2026-10-03), counted from the weigh-out. Longer than the
#: visit window on purpose: a tared ticket's net is final, so waiting longer risks nothing,
#: while an UNTARED ticket kept past 12 h could take tomorrow's tare and pay a wrong net.
JENDELA_TANPA_KELUAR_DETIK = 24 * 60 * 60
#: The working day starts at midnight unless support sets a cutoff (batch 5.11).
CUTOFF_BAWAAN = time(0, 0)
_POLA_CUTOFF = re.compile(r"^(\d{1,2})[:.](\d{2})$")


def awal_kunjungan(sekarang: datetime) -> float:
    """Epoch seconds of the oldest weigh-in a visit still running at `sekarang` can have.

    What "still in the yard" means everywhere on the console: the exit scan's open ticket,
    the Timbangan table carrying yesterday's unfinished visit, the Danger Zone block. A
    truck weighed in at 23:50 is still being sorted at 00:10; its work date is not today.
    """
    return sekarang.timestamp() - JENDELA_KUNJUNGAN_DETIK


def _geser(cutoff: time) -> timedelta:
    return timedelta(hours=cutoff.hour, minutes=cutoff.minute)


def work_date_for(timestamp_iso: str, tz: tzinfo, cutoff: time = CUTOFF_BAWAAN) -> str:
    """`YYYY-MM-DD` in the mill's zone. ValueError if the timestamp is unreadable.

    With a cutoff, the date of `timestamp - cutoff`: at 05:00, 02:30 still belongs to yesterday.

    A timestamp with no offset is read as UTC, that is what the camera lines
    send (`datetime.now(timezone.utc).isoformat()` sometimes lost its suffix in
    older data). Raising is deliberate rather than falling back to today: ingest
    answers 400, the line's outbox holds and keeps retrying it, visible in tab Status
    (Antrean line), far better than tonnage quietly sticking to a wrong date.
    """
    raw = timestamp_iso.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)  # ValueError when the shape is not ISO
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (dt.astimezone(tz) - _geser(cutoff)).strftime("%Y-%m-%d")


def hari_kerja_kini(sekarang: datetime, tz: tzinfo, cutoff: time = CUTOFF_BAWAAN) -> str:
    """The working day running at `sekarang` (the "Hari ini" of the screen)."""
    return (sekarang.astimezone(tz) - _geser(cutoff)).strftime("%Y-%m-%d")


def baca_cutoff(teks: str | None) -> time:
    """`HH:MM` (also `H:MM` and `HH.MM`, as operators type them); empty = midnight.

    Any time of day (user 2026-10-05). After 12:00 most of the working day falls on the next
    calendar date while it keeps the start's date; the screen asks before saving one.
    """
    bersih = (teks or "").strip()
    if not bersih:
        return CUTOFF_BAWAAN
    cocok = _POLA_CUTOFF.match(bersih)
    jam, menit = (int(cocok.group(1)), int(cocok.group(2))) if cocok else (-1, -1)
    if not (0 <= jam <= 23 and 0 <= menit <= 59):
        raise InvalidInput(CUTOFF_TIDAK_SAH, f"cutoff tidak sah: {bersih!r}")
    return time(jam, menit)


def teks_cutoff(cutoff: time) -> str:
    return cutoff.strftime("%H:%M")
