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
tambahan tiap 10 detik untuk hal yang sama. Keadaan yang TIDAK diceritakan siapa pun
diberi satu WARNING saat masuk dan satu saat pulih: line yang menjawab 503
`log_line_mati` (berkas log line itu tidak bisa dibuka), line yang menjawab 5xx lain
(misalnya log_line.db rusak sesudah dibuka), halaman yang bentuknya asing (versi konsol
dan line berbeda), dan galat tak terduga saat menarik satu line (yang lain tetap ditarik).

Penundaan diukur dengan jam monotonic, bukan jam dinding: PC pabrik yang offline lalu
dikoreksi NTP tidak boleh membuat tab Log diam sejam atau menarik tanpa jeda. Jam dinding
cuma untuk stempel `now` yang disimpan.

ERROR tiap halaman diteruskan ke antrean Discord SEBELUM halaman itu diserap (baris +
kursor, satu transaksi): mati di antara keduanya = halaman yang sama ditarik dan
diteruskan lagi, jadi hitungan Discord bisa lebih tapi galatnya tidak pernah hilang.
Serapan yang gagal tanpa konsol mati tidak menggandakan: hitungan yang sudah diteruskan
tapi belum terserap diingat per line (`_diteruskan`), jadi tarikan ulang cuma meneruskan
tambahannya (batas lainnya di docstring `repositories/log_serap_line.py`).
Antrean Discord yang gagal tidak menahan tab Log: halamannya tetap diserap, dan
kegagalan itu punya satu WARNING masuk + satu pulih sendiri, terpisah dari masalah
menarik. "Kembali tertarik" baru dicatat sesudah seluruh putaran line itu berhasil.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterable, Mapping
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

_LOG_LINE_MATI = "log_line_mati"
_LINE_GALAT_HTTP = "line_galat_http"
_BENTUK_ASING = "bentuk_asing"
_GALAT = "galat"


class _KlienLog(Protocol):
    async def log_line(
        self, line: LineEndpoint, *, setelah: int, generasi: str, batas: int
    ) -> dict: ...


class _PenyimpanLog(Protocol):
    def kursor_line(self, line_code: str) -> KursorLine: ...

    def galat_baru_line(
        self, line_code: str, jawaban: JawabanLog, *, sudah: Mapping[int, int] | None = None
    ) -> tuple[TambahGalat, ...]: ...

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
        monotonik: Callable[[], float] = time.monotonic,
    ) -> None:
        self._lines = list(lines)
        self._client = client
        self._log = log_store
        self._digest = digest
        self._interval_s = interval_s
        self._jam = jam
        self._monotonik = monotonik
        self._tunda_sampai: dict[str, float] = {}
        #: line_code -> jenis masalah yang sudah diperingatkan dan belum pulih.
        self._masalah: dict[str, str] = {}
        #: Line yang galatnya sedang gagal masuk antrean Discord (sudah diperingatkan).
        self._digest_gagal: set[str] = set()
        #: line_code -> (generasi, id baris -> hitungan ERROR yang sudah diteruskan ke
        #: Discord tapi belum terserap). Hilang saat konsol mati: paling sedikit sekali.
        self._diteruskan: dict[str, tuple[str, dict[int, int]]] = {}

    async def run_once(self) -> None:
        for line in self._lines:
            try:
                await self._tarik(line)
            except Exception as exc:  # noqa: BLE001, satu line yang rusak tidak boleh menahan yang lain
                self._tunda(line.line_code, JEDA_GAGAL_S)
                self._masuk_masalah(
                    line.line_code, _GALAT,
                    "Log %s tidak bisa ditarik ke tab Log: %s: %s. Dicoba lagi tiap %.0f detik.",
                    line.line_code, type(exc).__name__, exc, JEDA_GAGAL_S,
                    exc_info=True,
                )

    async def _tarik(self, line: LineEndpoint) -> None:
        kode = line.line_code
        if self._monotonik() < self._tunda_sampai.get(kode, float("-inf")):
            return
        kursor = await asyncio.to_thread(self._log.kursor_line, kode)
        for _ in range(MAKS_HALAMAN):
            jawaban = await self._minta(line, kursor)
            if jawaban is None:
                return
            await self._teruskan_ke_digest(kode, jawaban)
            hasil = await asyncio.to_thread(self._log.serap_line, kode, jawaban, now=self._jam())
            self._lupakan_terserap(kode, jawaban)
            self._laporkan_dibuang(kode, hasil)
            kursor = hasil.kursor
            if not jawaban.lagi:
                break
        # Sesudah SELURUH putaran: halaman pertama lolos lalu halaman kedua gagal lagi
        # bukan pemulihan, dan mencatatnya membuat pasangan WARNING tiap putaran.
        self._pulih(kode)

    async def _minta(self, line: LineEndpoint, kursor: KursorLine) -> JawabanLog | None:
        """Satu halaman yang sudah diperiksa, atau None (line ditunda).

        Line mati, menolak kunci, atau versi lama: DEBUG. 503 `log_line_mati`, 5xx lain,
        dan bentuk jawaban asing: satu WARNING per transisi (lihat docstring modul).
        """
        try:
            data = await self._client.log_line(
                line, setelah=kursor.seq, generasi=kursor.generasi, batas=BATAS_HALAMAN
            )
            return baca_jawaban_log(data)
        except LineUnavailable as exc:
            status = exc.params.get("status")
            self._tunda(line.line_code, JEDA_RUTE_TIDAK_ADA_S if status == 404 else JEDA_GAGAL_S)
            logger.debug("Log %s tidak ditarik: %s", line.line_code, exc)
            if status == 503:
                self._masuk_masalah(
                    line.line_code, _LOG_LINE_MATI,
                    "Log %s tidak bisa dibaca di line itu (log_line.db tidak bisa dibuka, jawaban "
                    "503 log_line_mati): tab Log tidak menerima log line ini sampai line itu "
                    "direstart. Sebabnya tertulis di docker logs line itu.",
                    line.line_code,
                )
            elif isinstance(status, int) and status >= 500:
                self._masuk_masalah(
                    line.line_code, _LINE_GALAT_HTTP,
                    "Log %s tidak bisa ditarik ke tab Log: line menjawab HTTP %s. Dicoba lagi tiap "
                    "%.0f detik; sebabnya tertulis di docker logs line itu.",
                    line.line_code, status, JEDA_GAGAL_S,
                )
        except ValueError as exc:  # badan bukan JSON, atau bentuknya asing
            self._tunda(line.line_code, JEDA_GAGAL_S)
            self._masuk_masalah(
                line.line_code, _BENTUK_ASING,
                "Log %s tidak bisa ditarik ke tab Log: bentuk jawaban line asing (%s). Versi konsol "
                "dan line mungkin berbeda; samakan versinya. Dicoba lagi tiap %.0f detik.",
                line.line_code, exc, JEDA_GAGAL_S,
            )
        return None

    async def _teruskan_ke_digest(self, kode: str, jawaban: JawabanLog) -> None:
        """ERROR baru halaman ini ke antrean Discord, SEBELUM serapan (docstring modul)."""
        if self._digest is None:
            return
        sudah = self._sudah_diteruskan(kode, jawaban.generasi)
        try:
            galat = await asyncio.to_thread(self._log.galat_baru_line, kode, jawaban, sudah=dict(sudah))
            if not galat:
                return
            await asyncio.to_thread(self._digest.antre_line, galat)
            for e in jawaban.entri:
                if e.level == "ERROR":
                    sudah[e.id] = max(sudah.get(e.id, 0), e.count)
        except Exception as exc:  # noqa: BLE001, tab Log didahulukan daripada Discord
            if kode not in self._digest_gagal:
                self._digest_gagal.add(kode)
                logger.warning(
                    "Galat %s tidak bisa masuk antrean lapor Discord: %s: %s. Tab Log tetap "
                    "menerimanya, tapi galat line itu tidak ikut ringkasan Discord sampai "
                    "antreannya pulih.",
                    kode, type(exc).__name__, exc, exc_info=True,
                )
            return
        if kode in self._digest_gagal:
            self._digest_gagal.discard(kode)
            logger.warning("Galat %s kembali masuk antrean lapor Discord", kode)

    def _sudah_diteruskan(self, kode: str, generasi: str) -> dict[int, int]:
        """Hitungan yang sudah diteruskan tapi belum terserap, untuk generasi ini."""
        simpanan = self._diteruskan.get(kode)
        if simpanan is None or simpanan[0] != generasi:
            simpanan = (generasi, {})
            self._diteruskan[kode] = simpanan
        return simpanan[1]

    def _lupakan_terserap(self, kode: str, jawaban: JawabanLog) -> None:
        """Baris yang sudah terserap dihitung dari `event_log` lagi, bukan dari ingatan."""
        simpanan = self._diteruskan.get(kode)
        if simpanan is None or simpanan[0] != jawaban.generasi:
            return
        for e in jawaban.entri:
            simpanan[1].pop(e.id, None)

    @staticmethod
    def _laporkan_dibuang(kode: str, hasil: HasilSerap) -> None:
        if hasil.dibuang_baru:
            logger.warning(
                "%s membuang %d baris log sebelum sempat ditarik konsol (log line penuh "
                "saat konsol tidak menariknya). Galat yang tersisa tetap tampil di tab Log.",
                kode, hasil.dibuang_baru,
            )

    def _tunda(self, kode: str, detik: float) -> None:
        self._tunda_sampai[kode] = self._monotonik() + detik

    def _masuk_masalah(self, kode: str, jenis: str, pesan: str, *args: object, exc_info: bool = False) -> None:
        """Satu WARNING per transisi masuk; masalah yang sama berulang tetap diam."""
        if self._masalah.get(kode) == jenis:
            return
        self._masalah[kode] = jenis
        logger.warning(pesan, *args, exc_info=exc_info)

    def _pulih(self, kode: str) -> None:
        if self._masalah.pop(kode, None) is not None:
            logger.warning("Log %s kembali tertarik ke tab Log", kode)

    async def run_loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001, satu putaran yang gagal tidak boleh mematikan tarikan
                logger.warning("Tarikan log line gagal satu putaran", exc_info=True)
            await asyncio.sleep(self._interval_s)
