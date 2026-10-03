"""Automatic line assignment (2026-10-01): the next truck onto the lines, one at a time.

The rules are pure (`domain/penugasan_line.py`); this is the part that asks the lines
and records. Split from `console_service.py` because that file may not pass 1,000 lines
(`tests/unit/test_ukuran_berkas.py`). A mixin, like `LayarLineSupport`, because the
routes, tests and `record_weighing` call these methods on `ConsoleService`.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from ..core.config import LineEndpoint
from ..domain.bahaya import HapusBerjalan
from ..domain.operator_error import (
    BUKAN_ANTREAN,
    LINE_SEMUA_TERPAKAI,
    PENUGASAN_TANPA_LINE,
    InvalidInput,
)
from ..domain.pembaruan import PembaruanBerjalan
from ..domain.penugasan_line import (
    JENDELA_ANTREAN_BONGKAR,
    KUNCI_PENUGASAN,
    SetelanPenugasan,
    baca_setelan,
    bersihkan_setelan_penugasan,
    line_bebas,
    line_sibuk,
    line_tertahan,
    menit_menunggu,
    simpan_teks,
)
from ..integrations.notifications.line_client import LineUnavailable
from ..repositories.console_repository import ConsoleStore

logger = logging.getLogger(__name__)


class PenjagaPembaruan(Protocol):
    """What automatic assignment needs from `PembaruanService` (Update now, rule 38)."""

    def sedang_berjalan(self) -> bool: ...

    def menugaskan(self, line_code: str) -> AbstractAsyncContextManager[None]: ...


class PenugasanOtomatis:
    """Provided by `ConsoleService`: the attributes below, `assign_truck` and `release_truck`."""

    # Update now (rule 38). None where no install can run (tests, tools): assign as before.
    _penjaga_pembaruan: PenjagaPembaruan | None = None

    store: ConsoleStore
    lines: tuple[LineEndpoint, ...]
    tz: ZoneInfo
    _kunci_penugasan: asyncio.Lock
    _truk_ditutup: dict[str, int]
    _kunci_ditutup: threading.Lock
    _tiket_dipasang: set[str]
    _kunci_antrean: threading.Lock
    assign_truck: Callable[[str, str], Awaitable[dict[str, Any]]]
    release_truck: Callable[[str], Awaitable[dict[str, Any]]]

    def pakai_penjaga_pembaruan(self, penjaga: PenjagaPembaruan) -> None:
        """Wired by the composition root (`console_deps.get_console_service`).

        Manual Tugaskan already goes through `penjaga.menugaskan(line)`; the automatic paths
        must too, or a truck weighed in during an install lands on a line about to restart.
        """
        self._penjaga_pembaruan = penjaga

    async def _pembaruan_berjalan(self) -> bool:
        penjaga = self._penjaga_pembaruan
        return bool(penjaga) and await asyncio.to_thread(penjaga.sedang_berjalan)

    def _kode_line(self) -> list[str]:
        return [ln.line_code for ln in self.lines]

    def _setelan_penugasan(self) -> SetelanPenugasan:
        return baca_setelan(self.store.get_state(KUNCI_PENUGASAN), self._kode_line())

    @staticmethod
    def _sejak_antrean() -> float:
        return time.time() - JENDELA_ANTREAN_BONGKAR.total_seconds()

    def assignments(self) -> dict[str, dict[str, Any]]:
        """Every line's current assignment row (a released line keeps an empty truck_id).

        Update now (rule 38) reads it to refuse an install while a truck is on a line. Here,
        not in `console_service.py`, which stays under 1,000 lines.
        """
        return self.store.assignments()

    def penugasan_otomatis(self) -> dict[str, Any]:
        """The setting as the Setelan tab shows it, with the lines it can choose from."""
        setelan = self._setelan_penugasan()
        return {
            "aktif": setelan.aktif,
            "lines": list(setelan.lines),
            "lines_tersedia": [{"line_code": ln.line_code, "name": ln.name} for ln in self.lines],
        }

    def simpan_penugasan_otomatis(
        self, aktif: bool | None, lines: list[str] | None, *, diubah_oleh: str
    ) -> dict[str, Any]:
        setelan = bersihkan_setelan_penugasan(aktif, lines, self._kode_line())
        self.store.set_state(KUNCI_PENUGASAN, simpan_teks(setelan))
        # WARNING with who, like the grading settings: this decides which truck the
        # bunches are counted to, so a strange day must lead back to the change.
        logger.warning(
            "Penugasan line otomatis %s (%s), diubah oleh %s",
            "NYALA" if setelan.aktif else "MATI", ", ".join(setelan.lines) or "-", diubah_oleh,
        )
        return self.penugasan_otomatis()

    async def simpan_penugasan_lalu_isi(
        self, aktif: bool | None, lines: list[str] | None, *, diubah_oleh: str
    ) -> dict[str, Any]:
        """Save, then fill: a truck already waiting while the lines are free goes on now,
        not at the next weighing or Lepas. Off fills nothing (`isi_line_otomatis` checks)."""
        setelan = self.simpan_penugasan_otomatis(aktif, lines, diubah_oleh=diubah_oleh)
        return {**setelan, "dipasang": await self.isi_line_otomatis()}

    def antrean_bongkar(self) -> list[dict[str, Any]]:
        """Trucks weighed in and waiting for the lines, with how long, for the screen."""
        sekarang = time.time()
        return [
            {
                "weighing_id": r["weighing_id"],
                "plate_number": r["plate_number"],
                "menit": menit_menunggu(r["received_at"], sekarang),
            }
            for r in self.store.unloading_queue(self._sejak_antrean())
        ]

    async def isi_line_otomatis(self) -> list[dict[str, Any]]:
        """The oldest waiting truck onto the free chosen lines, when nothing still sorts.

        Called after every weighing (a new ticket, or a weigh-out that just freed the
        lines) and after a manual Lepas. Never raises: it runs inside the money lane,
        and a failure here must not cost the weight. The truck stays in the queue.
        The queue is read inside the lock, so a second caller sees the first one's truck
        on the lines instead of offering it again.

        A truck being weighed out still counts as sorting until every line has let it go:
        its tare is written before the releases, and the next truck put on the lines
        released so far would end up on only some of them (D9). That weigh-out calls this
        again once its releases are done.
        """
        try:
            setelan = self._setelan_penugasan()
            if not setelan.aktif:
                return []
            async with self._kunci_penugasan:
                if await self._pembaruan_berjalan():
                    # The truck stays queued and goes on after the restart (next weighing,
                    # Lepas or Tugaskan sekarang), never onto a line that is about to restart.
                    logger.info("Penugasan otomatis ditahan: pembaruan sedang dipasang")
                    return []
                sejak = self._sejak_antrean()
                antrean = self.store.unloading_queue(sejak)
                if not antrean:
                    return []
                pegangan = self.store.assignments()
                terbuka = self.store.trucks_with_open_ticket(sejak) | self._truk_sedang_ditutup()
                if line_sibuk(setelan.lines, pegangan, terbuka):
                    return []
                return await self._pasang(antrean[0], setelan.lines, pegangan, terbuka, sejak)
        except PembaruanBerjalan:
            # An install started between the check and a line's assign (menugaskan refused).
            logger.info("Penugasan otomatis berhenti: pembaruan mulai dipasang")
            return []
        except Exception:
            logger.exception("Penugasan line otomatis gagal; truk tetap di antrean bongkar")
            return []

    async def pasang_dari_antrean(self, weighing_id: str) -> list[dict[str, Any]]:
        """"Tugaskan sekarang": this queued truck onto the free chosen lines, now.

        No busy check: the operator is looking at the ramp and decided. Free lines only,
        so a truck being sorted is never pushed off a line by this button. The one
        exception is a truck being weighed out right now: its lines are freed one by one,
        and pressing now would put this truck on only some of them (D9).
        """
        setelan = self._setelan_penugasan()
        async with self._kunci_penugasan:
            if await self._pembaruan_berjalan():
                raise PembaruanBerjalan()
            antre = self._di_antrean(weighing_id)
            sejak = self._sejak_antrean()
            if not setelan.lines:
                # Support saved no line at all: "every line is busy" would send the
                # operator looking at the cards instead of at Setelan.
                raise InvalidInput(PENUGASAN_TANPA_LINE, "tidak ada line yang dipilih untuk penugasan")
            pegangan = self.store.assignments()
            ditutup = self._truk_sedang_ditutup()
            if not line_bebas(setelan.lines, pegangan) or line_sibuk(setelan.lines, pegangan, ditutup):
                raise InvalidInput(LINE_SEMUA_TERPAKAI, "semua line masih memegang truk")
            terbuka = self.store.trucks_with_open_ticket(sejak) | ditutup
            return await self._pasang(antre, setelan.lines, pegangan, terbuka, sejak)

    def lewati_antrean(self, weighing_id: str, *, oleh: str) -> None:
        """"Lewati": a truck that will not unload leaves the queue (it is never assigned
        automatically again; the per-line dropdown still can).

        Checked against the queue first: a screen one poll behind may still show a truck
        that just went onto the lines, and marking that ticket must be refused, not done.
        A ticket being put on the lines right now is refused the same way: it is not in
        the queue any more, it just is not on every line yet.
        """
        with self._kunci_antrean:
            if weighing_id in self._tiket_dipasang:
                raise InvalidInput(BUKAN_ANTREAN, "tiket ini sedang ditugaskan ke line")
            self._di_antrean(weighing_id)
            if not self.store.skip_unloading_queue(weighing_id, datetime.now(self.tz).isoformat()):
                raise InvalidInput(BUKAN_ANTREAN, "tiket ini tidak ada di antrean bongkar")
        logger.info("Tiket %s dikeluarkan dari antrean bongkar oleh %s", weighing_id, oleh)

    async def release_truck_by_operator(self, line_code: str) -> dict[str, Any]:
        """Lepas pressed on a card: the same release, then the next truck may go on (D11)."""
        hasil = await self.release_truck(line_code)
        return {**hasil, "dipasang": await self.isi_line_otomatis()}

    def _truk_sedang_ditutup(self) -> set[str]:
        """Trucks whose weigh-out is releasing their lines right now (the weigh-out guard)."""
        with self._kunci_ditutup:
            return set(self._truk_ditutup)

    def _di_antrean(self, weighing_id: str) -> dict[str, Any]:
        """This ticket's row in the unloading queue as it stands now, or `bukan_antrean`."""
        for row in self.store.unloading_queue(self._sejak_antrean()):
            if row["weighing_id"] == weighing_id:
                return row
        raise InvalidInput(BUKAN_ANTREAN, "tiket ini tidak ada di antrean bongkar")

    def _masih_menunggu(self, weighing_id: str) -> bool:
        """Not skipped and not weighed out: this ticket's truck may still go on a line."""
        tiket = self.store.weighing(weighing_id) or {}
        return not tiket.get("unloading_queue_skipped_at") and tiket.get("tare_kg") is None

    def _plat_sudah_keluar(self, pegangan: dict[str, Any], sejak: float) -> str | None:
        """The plate of the truck a line still holds, ONLY when that truck really weighed
        out: its newest ticket in the window carries a tare. A holder with no ticket in the
        window (put on by hand) or an open one is still being sorted: telling the operator
        to Lepas it would move its remaining bunches to the next truck (G5). None also when
        no plate is known: a truck id is never shown as a plate."""
        tiket = self.store.latest_weighing_for_truck_since(pegangan["truck_id"], sejak)
        baris = (self.store.weighing(tiket) or {}) if tiket else {}
        if baris.get("tare_kg") is None:
            return None
        return pegangan.get("plate_number") or baris.get("plate_number") or None

    async def _pasang(
        self,
        antre: dict[str, Any],
        lines: tuple[str, ...],
        pegangan: dict[str, dict[str, Any]],
        terbuka: set[str],
        sejak: float,
    ) -> list[dict[str, Any]]:
        """The queued truck onto the free chosen lines, each on its own (rule 13: the line
        accepts first, then it is recorded). A line that does not answer is reported; the
        others still get the truck. In the chosen order, so the toast reads like the cards.

        A chosen line still holding a truck that weighed out (its weigh-out could not
        release it) is reported `tertahan` with that truck's plate: the operator must Lepas
        it on its card, or it stamps the departed truck on this truck's bunches once it
        answers (G5). Any other holder (still sorting, put on by hand without a ticket, or
        no plate known) is left out silently: the line is simply not free.

        A line is checked again right before its turn: while an earlier line was being
        asked, the operator may have put another truck on it from the card dropdown, and
        that truck is never pushed off. Such a line is left out of the result (it was not
        free), not reported as one to do by hand. The ticket is read again too: once it is
        weighed out (the truck left) no further line gets it. Lewati is refused meanwhile.
        """
        weighing_id = antre["weighing_id"]
        with self._kunci_antrean:
            if not self._masih_menunggu(weighing_id):
                return []
            self._tiket_dipasang.add(weighing_id)
        try:
            tertahan = {
                kode: plat for kode in line_tertahan(lines, pegangan, terbuka)
                if (plat := self._plat_sudah_keluar(pegangan[kode], sejak))
            }
            bebas = set(line_bebas(lines, pegangan))
            hasil = []
            for line_code in lines:
                if line_code in tertahan:
                    hasil.append({
                        "line_code": line_code, "plate_number": antre["plate_number"], "terpasang": False,
                        "tertahan": True, "plate_lama": tertahan[line_code],
                    })
                    continue
                if line_code not in bebas or not self._masih_menunggu(weighing_id):
                    continue
                if (self.store.assignments().get(line_code) or {}).get("truck_id"):
                    continue
                hasil.append(await self._pasang_satu(line_code, antre))
            return hasil
        finally:
            with self._kunci_antrean:
                self._tiket_dipasang.discard(weighing_id)

    async def _pasang_satu(self, line_code: str, antre: dict[str, Any]) -> dict[str, Any]:
        try:
            if (penjaga := self._penjaga_pembaruan) is None:
                await self.assign_truck(line_code, antre["truck_id"])
            else:
                async with penjaga.menugaskan(line_code):
                    await self.assign_truck(line_code, antre["truck_id"])
        except (LineUnavailable, HapusBerjalan) as exc:
            logger.warning(
                "Line %s tidak menerima truk %s otomatis (%s); tugaskan manual di kartunya",
                line_code, antre["plate_number"], exc,
            )
            return {"line_code": line_code, "plate_number": antre["plate_number"], "terpasang": False}
        return {"line_code": line_code, "plate_number": antre["plate_number"], "terpasang": True}
