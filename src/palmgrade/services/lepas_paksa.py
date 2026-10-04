"""Lepas paksa (user 2026-10-04): release a truck from a line that does not answer.

The rules are pure (`domain/lepas_paksa.py`); this is the part that asks the line and
records. A mixin of `ConsoleService`, like `PenugasanOtomatis`, because it reuses the
release bookkeeping there and `console_service.py` may not pass 1,000 lines
(`tests/unit/test_ukuran_berkas.py`).

Three paths:

- `force_release`, the button: the normal release first, with a short wait. A line that
  answers is released normally; a line that answers with a refusal is never overruled;
  only a line that gives no answer at all is cleared on the console alone, with the same
  link to the visit ticket and the same AutoERP message as a normal release (rule 18).
- `cocokkan_lepas_paksa`, after every status the line answers (`LineStatusWorker`): a line
  that was only cut off still holds the truck in memory, and hears the release again.
- `kunci_line`: one lock per line, held by `assign_truck` from the line call until the
  console records it, so that re-send never lands between "the line took the new truck"
  and "the console wrote it down".
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..core.config import LineEndpoint
from ..domain.lepas_paksa import (
    KUNCI_LEPAS_PAKSA,
    baca_tertunda,
    boleh_paksa,
    perlu_kirim_ulang,
    teks_tertunda,
)
from ..integrations.notifications.line_client import LineUnavailable
from ..repositories.console_repository import ConsoleStore

logger = logging.getLogger(__name__)

#: How long the button waits for the normal release before it counts the line as silent.
#: Short on purpose: a line that answers does so in milliseconds, and the operator is
#: holding a spinner. A refused connection fails at once and never waits this long.
TIMEOUT_LEPAS_PAKSA_S = 3.0


class LepasPaksa:
    """Provided by `ConsoleService`: the attributes below, `release_truck` and the rest."""

    store: ConsoleStore
    tz: ZoneInfo
    line_client: Any
    release_truck: Callable[..., Awaitable[dict[str, Any]]]
    isi_line_otomatis: Callable[[], Awaitable[list[dict[str, Any]]]]
    _queue_grading: Callable[..., None]
    _require_line: Callable[[str], LineEndpoint]

    # Built on first use, per instance (mixins here carry no __init__).
    _kunci_per_line: dict[str, asyncio.Lock] | None = None
    _tertunda_paksa: dict[str, str] | None = None

    def kunci_line(self, line_code: str) -> asyncio.Lock:
        """The lock `assign_truck` holds while the line takes a truck and the console records it."""
        if self._kunci_per_line is None:
            self._kunci_per_line = {}
        return self._kunci_per_line.setdefault(line_code, asyncio.Lock())

    def _catat_lepas(self, line_code: str, closing: dict[str, Any], *, kirim: bool) -> None:
        """The console's half of a release: the line is free, its grading goes to the visit.

        No `await` between these two (2026-10-01): until the link is written, the truck is
        on no line and linked to nothing, so the unloading queue would offer it again.
        """
        self.store.set_assignment(line_code, "", None)
        self._queue_grading(closing, kirim=kirim)

    async def force_release(self, line_code: str, *, oleh: str) -> dict[str, Any]:
        """Lepas paksa: the normal release, or the console's half alone when the line is silent.

        Raises `LineUnavailable` for a line that answered with a refusal (the route says
        502 with its code), and `ValueError` for an unknown line, as Lepas does.
        """
        self._require_line(line_code)
        closing = self.store.assignments().get(line_code) or {}
        if not closing.get("truck_id"):
            # Released meanwhile (another screen, a weigh-out): nothing left to force.
            return {"line_code": line_code, "truck_id": None, "paksa": False, "dipasang": []}
        try:
            hasil = await asyncio.wait_for(self.release_truck(line_code), TIMEOUT_LEPAS_PAKSA_S)
        except TimeoutError:
            pass  # the line took longer than a live line ever does: silent
        except LineUnavailable as exc:
            if not boleh_paksa(exc.code, exc.params.get("status")):
                raise
        else:
            return {**hasil, "paksa": False, "dipasang": await self.isi_line_otomatis()}
        kini = self.store.assignments().get(line_code) or {}
        if kini.get("assignment_id") != closing.get("assignment_id"):
            # The line changed hands while we waited: that newer state is not ours to clear.
            return {"line_code": line_code, "truck_id": kini.get("truck_id"), "paksa": False, "dipasang": []}
        # Remembered before the console's half: a crash in between leaves a pending release
        # that the next status read simply closes, never a line nobody will tell.
        self._ingat_lepas_paksa(line_code, closing["truck_id"])
        self._catat_lepas(line_code, closing, kirim=True)
        logger.warning(
            "Lepas paksa oleh %s: truk %s dilepas dari %s di konsol saja, line itu tidak menjawab. "
            "Line mengambil penugasan kosong saat menyala lagi; kalau ia cuma terputus, pelepasan "
            "dikirim ulang begitu ia menjawab.",
            oleh, closing.get("plate_number") or closing["truck_id"], line_code,
        )
        return {"line_code": line_code, "truck_id": None, "paksa": True, "dipasang": await self.isi_line_otomatis()}

    async def cocokkan_lepas_paksa(self, line_code: str, status: dict[str, Any]) -> None:
        """A line answered its status: send a forced release again if it still holds that truck.

        Called for every answered status of every line, so it returns at once when nothing
        is pending. While an assign to that line is in flight the line may already hold the
        new truck that the console has not written yet: decided on a later poll instead.
        """
        truk_paksa = self._lepas_tertunda().get(line_code)
        if not truk_paksa:
            return
        kunci = self.kunci_line(line_code)
        if kunci.locked():
            return
        async with kunci:
            pegangan = self.store.assignments().get(line_code) or {}
            if perlu_kirim_ulang(truk_paksa, truk_di_line=status.get("truck_id"), truk_di_konsol=pegangan.get("truck_id")):
                if not await self._kirim_ulang_lepas(line_code):
                    return
                plat = (self.store.truck(truk_paksa) or {}).get("plate_number") or truk_paksa
                logger.warning(
                    "Lepas paksa %s: line menjawab lagi dan masih memegang truk %s; pelepasannya "
                    "dikirim ulang dan diterima line.",
                    line_code, plat,
                )
            self._lupakan_lepas_paksa(line_code)

    async def _kirim_ulang_lepas(self, line_code: str) -> bool:
        """The empty assignment again, with the button's short wait. False = try next poll."""
        try:
            await asyncio.wait_for(
                self.line_client.assign_truck(
                    self._require_line(line_code), assignment_id="", truck_id="",
                    assigned_at=datetime.now(self.tz).isoformat(), ffb_source=None,
                ),
                TIMEOUT_LEPAS_PAKSA_S,
            )
        except (LineUnavailable, TimeoutError) as exc:
            # INFO, not WARNING: the status poll runs every second and this repeats until the
            # line takes it; the forced release itself is already a WARNING in the Log tab.
            logger.info("Lepas paksa %s: kirim ulang belum diterima line, dicoba lagi: %s", line_code, exc)
            return False
        return True

    def _lepas_tertunda(self) -> dict[str, str]:
        """Forced releases a line has not heard yet, read from `console.db` once per process."""
        if self._tertunda_paksa is None:
            self._tertunda_paksa = baca_tertunda(self.store.get_state(KUNCI_LEPAS_PAKSA))
        return self._tertunda_paksa

    def _ingat_lepas_paksa(self, line_code: str, truck_id: str) -> None:
        self._simpan_lepas_paksa({**self._lepas_tertunda(), line_code: truck_id})

    def _lupakan_lepas_paksa(self, line_code: str) -> None:
        self._simpan_lepas_paksa({k: v for k, v in self._lepas_tertunda().items() if k != line_code})

    def _simpan_lepas_paksa(self, tertunda: dict[str, str]) -> None:
        """Kept in `console.db`, not only in memory: a console restart while the line is cut off
        must still send the release once that line answers."""
        self.store.set_state(KUNCI_LEPAS_PAKSA, teks_tertunda(tertunda))
        self._tertunda_paksa = tertunda
