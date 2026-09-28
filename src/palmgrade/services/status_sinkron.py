"""Last Sync: jejak sambungan konsol ke AutoERP dan R2, ditulis worker, dibaca layar.

Semua jalur yang sudah bicara ke luar ikut mencatat di sini, masing-masing sebagai
SUMBER sendiri: `cek` (tiap menit, `CekSinkronWorker`), `tarik` (data master AutoERP),
`kirim` (antrean ke AutoERP), `manifest` (R2). Satu sambungan putus kalau satu
sumbernya sedang gagal, dan tiap sumber pulih sendiri (`domain/sinkron.py`).

Galat jaringan (tanpa jawaban, gateway mati) dicatat di sumber khusus `jaringan`, yang
dibersihkan jawaban apa pun dari server lewat sumber mana saja: kiriman yang gagal
karena jaringan baru diulang sampai sejam kemudian, dan titiknya tidak boleh merah
selama itu kalau ping sudah menjawab lagi. Penolakan (kunci salah, tarikan ditolak)
tetap merah sampai sumber yang melihatnya berhasil lagi.

Jam sinkron terakhir disimpan di `sync_state` dan DIBACA dari sana tiap kali, jadi
sesudah restart layar tetap menyebut jam itu, dan "hapus semua" di Danger Zone langsung
terlihat. Keadaan sambungan sendiri sengaja TIDAK disimpan: sesudah menyala yang jujur
adalah "memeriksa" sampai cek pertama jalan.

Putus dan pulih masing-masing SATU baris WARNING per sambungan (tab Log cuma
menyimpan WARNING dan ERROR), bukan satu baris per percobaan.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from ..domain.sinkron import SUMBER_JARINGAN, Jejak, awal_gagal, ringkas
from ..repositories.console_repository import ConsoleStore

logger = logging.getLogger(__name__)

_NAMA = {"erp": "AutoERP", "r2": "Cloud Photo (R2)"}
# Baris `sync_state` jam sinkron terakhir. Awalan `sinkron_` digolongkan Danger Zone
# (`domain/bahaya.py`): tetap saat hapus transaksi, ikut terhapus saat hapus semua.
KUNCI_SINKRON = {"erp": "sinkron_autoerp_terakhir", "r2": "sinkron_r2_terakhir"}


class StatusSinkron:
    def __init__(
        self,
        store: ConsoleStore | None,
        *,
        erp_aktif: bool,
        r2_aktif: bool,
        jam: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._jam = jam
        self._aktif = {"erp": erp_aktif, "r2": r2_aktif}
        # Worker AutoERP jalan di loop asyncio, cek R2 di thread: satu kunci kecil.
        self._kunci = threading.Lock()
        self._jejak: dict[str, dict[str, Jejak]] = {nama: defaultdict(Jejak) for nama in KUNCI_SINKRON}
        # Hanya dipakai tanpa store (test lama yang merakit ConsoleService sendiri).
        self._terakhir_memori: dict[str, float | None] = dict.fromkeys(KUNCI_SINKRON)

    def aktif(self, nama: str) -> bool:
        return self._aktif[nama]

    def berhasil(self, nama: str, sumber: str, *, sinkron: bool) -> None:
        """Kontak yang berhasil. `sinkron=True` hanya kalau data benar-benar lewat
        (bukan cek), karena itulah yang ditulis di layar sebagai Last Sync."""
        now = self._jam()
        with self._kunci:
            jejak = self._jejak[nama]
            sebelum = awal_gagal(jejak.values())
            jejak[sumber].berhasil(now)
            # Server menjawab: jaringannya jelas hidup, dari sumber mana pun.
            jejak[SUMBER_JARINGAN].berhasil(now)
            masih = awal_gagal(jejak.values())
        if sinkron:
            self._simpan_terakhir(nama, now)
        if sebelum is not None and masih is None:
            menit = max(1, round((now - sebelum) / 60))
            logger.warning("%s tersambung lagi sesudah %s menit terputus", _NAMA[nama], menit)

    def gagal(self, nama: str, sumber: str, pesan: str, *, jaringan: bool = False) -> None:
        """Kegagalan satu sumber. `jaringan=True` untuk tanpa jawaban / gateway mati:
        dicatat di sumber `jaringan` supaya jawaban berikutnya dari mana pun memulihkannya."""
        with self._kunci:
            jejak = self._jejak[nama]
            sebelum = awal_gagal(jejak.values())
            jejak[SUMBER_JARINGAN if jaringan else sumber].gagal(self._jam(), pesan)
        if sebelum is None:
            logger.warning("%s terputus: %s", _NAMA[nama], pesan)

    def ringkas(self, nama: str, *, antre: int) -> dict[str, Any]:
        terakhir = self._baca_terakhir(nama)
        with self._kunci:
            return ringkas(self._jejak[nama].values(), aktif=self._aktif[nama], antre=antre, terakhir=terakhir)

    def _simpan_terakhir(self, nama: str, now: float) -> None:
        if self._store is None:
            self._terakhir_memori[nama] = now
        else:
            self._store.set_state(KUNCI_SINKRON[nama], f"{now:.3f}")

    def _baca_terakhir(self, nama: str) -> float | None:
        if self._store is None:
            return self._terakhir_memori[nama]
        nilai = self._store.get_state(KUNCI_SINKRON[nama])
        try:
            return float(nilai) if nilai else None
        except ValueError:
            return None
