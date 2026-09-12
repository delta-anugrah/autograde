"""Mill working-day boundary (plan §6.1).

The mill runs ~20 hours a day and ACROSS midnight. A UTC day boundary cuts one
shift into two dates, so `tanggal_kerja` is derived from the event's own
timestamp at ingest and then STORED as a column - never derived from
`creation`, `now()`, or a folder name. A late event (outbox retry after a power
cut) still lands on its own day.

Free of heavy dependencies so it can be tested without a camera or torch.
"""
from __future__ import annotations

from datetime import UTC, datetime, tzinfo


def tanggal_kerja_for(timestamp_iso: str, tz: tzinfo) -> str:
    """`YYYY-MM-DD` in the mill's zone. ValueError if the timestamp is unreadable.

    A timestamp with no offset is read as UTC - that is what the camera lines
    send (`datetime.now(timezone.utc).isoformat()` sometimes lost its suffix in
    older data). Raising is deliberate rather than falling back to today: ingest
    answers 400, the line's outbox holds and retries, and the row shows up as
    `outbox_failed` - far better than tonnage quietly sticking to a wrong date.
    """
    raw = timestamp_iso.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)  # ValueError when the shape is not ISO
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(tz).strftime("%Y-%m-%d")
