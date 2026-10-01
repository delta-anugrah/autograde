"""Log sambungan satu PLC: sekali saat putus, sekali saat pulih (batch 3.3).

Dipakai bersama `McProtocolPlcClient` dan `ModbusPlcClient`. Keduanya dipanggil
`PlcWorker` tiap tick (200 ms) dan tiap panggilan dulu menulis WARNING-nya
sendiri, jadi kabel PLC yang dicabut menghasilkan ±10 baris per detik sampai ada
yang menyambungnya lagi.

"Pulih" baru dinyatakan sesudah satu baca/tulis BERHASIL, bukan sesudah connect:
PLC yang menerima koneksi lalu menolak tiap paket akan terbaca connect-putus-
connect-putus, dan itu tetap satu kejadian, bukan satu pasang baris per tick.

Awal putus ditulis ERROR, pulihnya WARNING: PLC yang putus berarti buah lewat tanpa
disortir, dan satu-satunya kanal keluar pabrik (ringkasan Discord, aturan 34) cuma
membawa ERROR. Sekali per kejadian, jadi satu kabel yang dicabut = satu baris Discord.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from ..domain.transisi import PelacakTransisi, teks_lama

logger = logging.getLogger(__name__)


class JejakSambunganPlc:
    def __init__(self, host: str, port: int, *, jam: Callable[[], float] = time.monotonic) -> None:
        self._alamat = f"{host}:{port}"
        self._putus = PelacakTransisi(jam=jam)

    @property
    def putus(self) -> bool:
        return self._putus.putus

    def gagal_sambung(self, alasan: object) -> None:
        if self._putus.gagal():
            logger.error(
                "PLC %s tidak bisa disambung: %s. Dicoba lagi tiap tick; baris berikutnya"
                " baru ditulis saat tersambung lagi",
                self._alamat, alasan,
            )
        else:
            logger.debug("PLC %s masih tidak bisa disambung: %s", self._alamat, alasan)

    def terputus(self, exc: Exception) -> None:
        if self._putus.gagal():
            logger.error("PLC %s terputus (%s), menyambung ulang", self._alamat, exc)
        else:
            logger.debug("PLC %s I/O masih gagal: %s", self._alamat, exc)

    def berhasil(self) -> None:
        lama = self._putus.pulih()
        if lama is not None:
            logger.warning("PLC %s tersambung lagi sesudah %s", self._alamat, teks_lama(lama))
