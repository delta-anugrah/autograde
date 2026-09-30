"""Konsol menarik WARNING/ERROR ketiga line ke tab Log (batch 3.2).

Line menyimpan log-nya sendiri di `state/log_line.db` (selamat dari `--force-recreate`);
worker ini memintanya tiap 10 detik lewat `GET /internal/log` dengan kursor yang
disimpan di berkas log konsol (`log_line_kursor`), jadi tidak ada yang hilang atau
ganda saat line restart, konsol restart, atau log line direset.

Sengaja worker sendiri, bukan tambahan `LineStatusWorker`: yang itu melayani strip
status tiap detik dengan timeout 1,5 detik, dan satu halaman log dengan traceback
tidak boleh membuat kartu line terlambat.

Line mati, menolak kunci, atau versi lama tanpa rute ini (404) = diam, ditunda, dicoba
lagi. Keadaan line sudah diceritakan `LineStatusWorker`; tab Log tidak perlu baris
tambahan tiap 10 detik untuk hal yang sama.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterable
from typing import Protocol

from ..core.config import LineEndpoint
from ..domain.log_line import BATAS_HALAMAN, JawabanLog, KursorLine, baca_jawaban_log
from ..integrations.notifications.line_client import LineUnavailable
from ..repositories.log_serap_line import HasilSerap, TambahGalat

logger = logging.getLogger(__name__)

INTERVAL_S = 10.0
#: Halaman per line per putaran: 5 x 100 baris. Tumpukan sesudah konsol mati lama
#: habis dalam beberapa putaran tanpa satu putaran menahan line lain terlalu lama.
MAKS_HALAMAN = 5
JEDA_GAGAL_S = 30.0
#: Line versi lama (belum punya `/internal/log`): tanya lagi 5 menit kemudian, supaya
#: line yang baru di-upgrade terbaca tanpa konsol di-restart.
JEDA_RUTE_TIDAK_ADA_S = 300.0


class _KlienLog(Protocol):
    async def log_line(
        self, line: LineEndpoint, *, setelah: int, generasi: str, batas: int
    ) -> dict: ...


class _PenyimpanLog(Protocol):
    def kursor_line(self, line_code: str) -> KursorLine: ...

    def serap_line(self, line_code: str, jawaban: JawabanLog, *, now: float) -> HasilSerap: ...


class _AntreanDigest(Protocol):
    def antre_line(self, galat: Iterable[TambahGalat]) -> None: ...


class TarikLogLineWorker:
    def __init__(
        self,
        lines: Iterable[LineEndpoint],
        client: _KlienLog,
        log_store: _PenyimpanLog,
        *,
        digest: _AntreanDigest | None = None,
        interval_s: float = INTERVAL_S,
        jam: Callable[[], float] = time.time,
    ) -> None:
        self._lines = list(lines)
        self._client = client
        self._log = log_store
        self._digest = digest
        self._interval_s = interval_s
        self._jam = jam
        self._tunda_sampai: dict[str, float] = {}

    async def run_once(self) -> None:
        for line in self._lines:
            await self._tarik(line)

    async def _tarik(self, line: LineEndpoint) -> None:
        kode = line.line_code
        if self._jam() < self._tunda_sampai.get(kode, 0.0):
            return
        kursor = await asyncio.to_thread(self._log.kursor_line, kode)
        for _ in range(MAKS_HALAMAN):
            jawaban = await self._minta(line, kursor)
            if jawaban is None:
                return
            hasil = await asyncio.to_thread(self._log.serap_line, kode, jawaban, now=self._jam())
            await self._teruskan(kode, hasil)
            kursor = hasil.kursor
            if not jawaban.lagi:
                return

    async def _minta(self, line: LineEndpoint, kursor: KursorLine) -> JawabanLog | None:
        """Satu halaman yang sudah diperiksa, atau None (line ditunda, alasannya DEBUG)."""
        try:
            data = await self._client.log_line(
                line, setelah=kursor.seq, generasi=kursor.generasi, batas=BATAS_HALAMAN
            )
            return baca_jawaban_log(data)
        except LineUnavailable as exc:
            rute_tidak_ada = exc.params.get("status") == 404
            self._tunda(line.line_code, JEDA_RUTE_TIDAK_ADA_S if rute_tidak_ada else JEDA_GAGAL_S)
            logger.debug("Log %s tidak ditarik: %s", line.line_code, exc)
        except ValueError as exc:  # badan bukan JSON, atau bentuknya asing
            self._tunda(line.line_code, JEDA_GAGAL_S)
            logger.debug("Log %s dijawab dengan bentuk asing: %s", line.line_code, exc)
        return None

    async def _teruskan(self, kode: str, hasil: HasilSerap) -> None:
        if hasil.dibuang_baru:
            logger.warning(
                "%s membuang %d baris log sebelum sempat ditarik konsol (log line penuh "
                "saat konsol tidak menariknya). Galat yang tersisa tetap tampil di tab Log.",
                kode, hasil.dibuang_baru,
            )
        if self._digest is not None and hasil.galat_baru:
            await asyncio.to_thread(self._digest.antre_line, hasil.galat_baru)

    def _tunda(self, kode: str, detik: float) -> None:
        self._tunda_sampai[kode] = self._jam() + detik

    async def run_loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001, satu putaran yang gagal tidak boleh mematikan tarikan
                logger.warning("Tarikan log line gagal satu putaran", exc_info=True)
            await asyncio.sleep(self._interval_s)
