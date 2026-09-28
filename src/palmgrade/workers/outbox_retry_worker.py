"""Kirim antrean janjang line ke konsol (`BACKEND_URL`), tanpa batas nyerah.

Batch 2.4 (2026-09-28, keputusan user): data tidak boleh hilang. Dulu baris yang
gagal 50 kali (kira-kira 7,3 jam konsol mati) ditandai `failed` dan tidak pernah
dicoba lagi. Sekarang setiap baris dicoba sampai terkirim, dan dua jenis gagal
dibedakan (`domain/kirim_antrean_line.py`):

- KONSOL bermasalah (tidak terjangkau, kunci ditolak, alamat salah, 5xx): semua
  baris akan gagal dengan cara yang sama, jadi yang dicoba cuma SATU baris per
  jeda sambungan (5 dtk naik sampai 30 dtk). Dulu 20 baris dicoba tiap detik
  tanpa jeda dan tiap percobaan satu WARNING: itu yang membuat log penuh saat
  `ENABLE_WEBHOOK=true` dengan tujuan mati (terukur 20 POST/dtk begitu antrean
  lewat beberapa ribu baris).
- BARIS itu ditolak (400): konsol sehat, baris lain jalan terus; baris itu
  mundur sendiri sampai 10 menit dan dicoba terus.

Jawaban "konsol bermasalah" (5xx, kunci, alamat) SESUDAH konsol menerima janjang
lain (2xx) di sambungan yang sama dibaca sebagai masalah BARIS itu, bukan
sambungan: barisnya mundur sendiri, pengurasan lanjut, sambungan tidak diputus,
dan tidak ada WARNING putus. Tanpa itu satu janjang racun yang selalu memicu 500
memutus sambungan, janjang baru berikutnya menyambungkannya lagi, dan sambung
lagi menjadwalkan si racun sekarang juga (review Task 3: 511 POST dan 601
WARNING per jam). Hanya jawaban seperti itu SEBELUM ada 2xx di sambungan ini
(percobaan sambungan, atau kiriman pertama sesudah pulih) yang memutus. Galat
jaringan dan timeout selalu memutus.

Kontak pertama sesudah boot dan transisi putus ke tersambung menjadwalkan SEMUA
baris untuk dikirim sekarang (`kirim_ulang_sekarang`), lalu antrean dikuras
sampai habis dalam putaran yang sama, bukan 20 baris per detik.
"""
from __future__ import annotations

import datetime
import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

from ..core.config import Settings
from ..domain.kirim_antrean_line import (
    JEDA_SAMBUNGAN_MAKS_S,
    SEBAB_TAK_TERJANGKAU,
    Nasib,
    SambunganKonsol,
    nilai_jawaban,
)
from ..integrations.outbox.outbox_store import OutboxStore
from .runtime_state import RuntimeState

logger = logging.getLogger(__name__)

#: Nama di `RuntimeState.worker_threads` (`main.py`); layar Antrean mencarinya di sana.
NAMA_WORKER = "outbox_retry"
#: Bentuk `status()` sebelum ada percobaan apa pun, atau tanpa worker (line lama, test).
STATUS_TIDAK_DIKETAHUI: dict[str, Any] = {
    "tersambung": None,
    "putus_sejak": None,
    "sebab_putus": None,
    "coba_lagi_at": None,
    "galat": None,
    "galat_at": None,
}

_POLL_INTERVAL = 1
_REQUEST_TIMEOUT = 5
_BATCH = 20


class OutboxRetryWorker:
    def __init__(
        self,
        outbox: OutboxStore,
        settings: Settings,
        state: RuntimeState,
        *,
        client: httpx.Client | None = None,
        jam: Callable[[], float] = time.time,
    ) -> None:
        self.outbox = outbox
        self.settings = settings
        self.state = state
        self._client = client if client is not None else httpx.Client(timeout=_REQUEST_TIMEOUT)
        self._jam = jam
        self._headers = {
            "Content-Type": "application/json",
            "x-webhook-secret": settings.webhook_secret,
        }
        # `_sambungan`, galat terakhir, dan hitungan bangun dibaca/ditulis juga dari
        # thread HTTP (`status()`, `bangunkan()`), jadi semuanya di bawah satu kunci.
        self._kunci = threading.Lock()
        self._sambungan = SambunganKonsol()
        self._galat: str | None = None
        self._galat_at: float | None = None
        self._bangun_ke = 0
        self._bangun_awal_putaran = 0
        #: Konsol sudah menerima (2xx) sejak sambungan ini hidup; lihat docstring modul.
        self._terkirim_di_sambungan_ini = False
        #: event_id yang penolakannya sudah di-WARNING di proses ini (sesudahnya DEBUG).
        self._sudah_diperingatkan: set[str] = set()

    def run_loop(self) -> None:
        logger.info("OutboxRetryWorker started, target %s", self.settings.canonical_events_url)
        while True:
            try:
                self._flush_pending()
            except Exception:
                logger.exception("OutboxRetryWorker unhandled error")
            time.sleep(_POLL_INTERVAL)

    def status(self) -> dict[str, Any]:
        """Keadaan untuk layar Antrean konsol (`GET /internal/outbox`). Kunci = `STATUS_TIDAK_DIKETAHUI`."""
        with self._kunci:
            s = self._sambungan
            return {
                "tersambung": s.tersambung,
                "putus_sejak": s.putus_sejak,
                "sebab_putus": s.sebab,
                "coba_lagi_at": s.coba_lagi_at or None,
                "galat": self._galat,
                "galat_at": self._galat_at,
            }

    def bangunkan(self) -> None:
        """Tombol Kirim Ulang: putaran berikutnya (paling lama 1 detik) mencoba, tanpa menunggu jeda.

        Tercatat juga sebagai hitungan: kalau ditekan SELAMA percobaan yang lalu
        gagal, `_konsol_bermasalah` membatalkan jeda yang baru dipasangnya.
        """
        with self._kunci:
            self._bangun_ke += 1
            self._sambungan.bangunkan()

    def _flush_pending(self) -> None:
        """Satu putaran: kuras semua yang jatuh tempo, sampai habis atau konsol bermasalah."""
        if not self.settings.enable_webhook:
            return
        with self._kunci:
            if not self._sambungan.boleh_coba(self._jam()):
                return
            self._bangun_awal_putaran = self._bangun_ke
            tersambung = self._sambungan.tersambung
        if tersambung is not True and not self._uji_sambungan():
            return
        while batch := self.outbox.get_pending(limit=_BATCH):
            for row in batch:
                if not self._kirim(row):
                    return

    def _uji_sambungan(self) -> bool:
        """Sesudah boot atau saat putus: SATU baris, jadwal mundurnya diabaikan.

        Tanpa ini pabrik yang diam (tidak ada janjang baru yang jatuh tempo) baru
        tahu konsol hidup lagi sesudah jadwal mundur barisnya, sampai 10 menit.
        True = konsol menjawab; putaran lanjut menguras antrean.
        """
        row = self.outbox.berikutnya()
        return row is not None and self._kirim(row)

    def _kirim(self, row: dict[str, Any]) -> bool:
        """Kirim satu baris. False = konsol bermasalah, sisa antrean menunggu jeda sambungan."""
        try:
            payload = json.loads(row["payload"])
        except ValueError as exc:
            self._baris_ditolak(row, f"payload rusak: {exc}")
            return True
        try:
            res = self._client.post(self.settings.canonical_events_url, json=payload, headers=self._headers)
        except Exception as exc:  # jaringan, timeout, apa pun sebelum ada jawaban
            self._konsol_bermasalah(row, SEBAB_TAK_TERJANGKAU, f"{type(exc).__name__}: {exc}")
            return False
        putusan = nilai_jawaban(res.status_code, res.text)
        if putusan.nasib is Nasib.TERKIRIM:
            self.outbox.mark_delivered(row["id"])
            self._sudah_diperingatkan.discard(row["event_id"])
            self.state.last_successful_api_push = datetime.datetime.now(datetime.UTC).isoformat()
            self._konsol_menjawab()
            self._terkirim_di_sambungan_ini = True
            return True
        galat = f"HTTP {res.status_code}: {res.text[:200]}"
        if putusan.nasib is Nasib.DITOLAK:
            self._konsol_menjawab()
            self._baris_ditolak(row, galat)
            return True
        if self._terkirim_di_sambungan_ini:
            # Konsol baru saja menerima janjang lain: yang bermasalah baris ini.
            self._baris_ditolak(row, galat)
            return True
        self._konsol_bermasalah(row, putusan.sebab or SEBAB_TAK_TERJANGKAU, galat)
        return False

    def _catat_galat(self, galat: str) -> None:
        with self._kunci:
            self._galat = galat
            self._galat_at = self._jam()

    def _baris_ditolak(self, row: dict[str, Any], galat: str) -> None:
        self.outbox.mark_failed_attempt(row["id"], galat)
        self._catat_galat(galat)
        # Sekali WARNING per baris per proses, sesudahnya DEBUG: baris yang ditolak
        # dicoba terus tiap 10 menit, dan WARNING tiap kali akan mengulang masalah
        # lama yang sama di log sepanjang hari. Bukan `retry_count == 0`: baris
        # yang dihidupkan lagi (percobaan 50) atau dipakai menguji sambungan tidak
        # pernah punya percobaan ke-0 lagi, dan penolakannya jadi tidak terlihat.
        tingkat = logging.DEBUG if row["event_id"] in self._sudah_diperingatkan else logging.WARNING
        self._sudah_diperingatkan.add(row["event_id"])
        logger.log(tingkat, "Konsol menolak janjang %s: %s. Dicoba lagi terus, jeda sampai 10 menit", row["event_id"], galat)

    def _konsol_bermasalah(self, row: dict[str, Any], sebab: str, galat: str) -> None:
        # Jeda dipasang SEBELUM menulis ke store: kalau tulisan itu gagal (disk
        # penuh), putaran berikutnya tetap menunggu jeda, bukan mencoba lagi dan
        # mencetak traceback tiap detik.
        with self._kunci:
            kabar_baru = self._sambungan.gagal(self._jam(), sebab=sebab)
            if self._bangun_ke != self._bangun_awal_putaran:
                self._sambungan.bangunkan()  # Kirim Ulang ditekan selama percobaan ini
        self._terkirim_di_sambungan_ini = False
        self._catat_galat(galat)
        self.outbox.mark_failed_attempt(row["id"], galat)
        if kabar_baru:
            logger.warning(
                "Konsol tidak bisa dikirimi (%s): %s. %d janjang menunggu, dicoba lagi sendiri "
                "paling lama tiap %d detik, tidak ada yang dibuang",
                sebab, galat, self.outbox.pending_count(), int(JEDA_SAMBUNGAN_MAKS_S),
            )
        else:
            logger.debug("Konsol masih bermasalah (%s): %s", sebab, galat)

    def _konsol_menjawab(self) -> None:
        with self._kunci:
            putus_sejak = self._sambungan.putus_sejak
            baru = self._sambungan.berhasil()
        if not baru:
            return
        dijadwalkan = self.outbox.kirim_ulang_sekarang()
        if putus_sejak is None:
            logger.info("Konsol menjawab; %d janjang antre dikirim sekarang", dijadwalkan)
        else:
            logger.warning(
                "Konsol tersambung lagi sesudah %d detik; %d janjang antre dikirim sekarang",
                int(self._jam() - putus_sejak), dijadwalkan,
            )
