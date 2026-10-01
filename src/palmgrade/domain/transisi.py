"""Log transisi, bukan spam (batch 3.3): kapan sebuah kegagalan pantas ditulis.

Pola yang sama dengan `services/status_sinkron.py` (Last Sync): SATU baris saat
sesuatu mulai gagal, SATU baris saat pulih, dan percobaan di antaranya diam.
Bedanya, `StatusSinkron` menggabungkan beberapa sumber satu sambungan konsol ke
AutoERP/R2 dan menyimpan jam sinkron; yang ini satu sumber saja, tanpa store, untuk
dipakai di mana pun sebuah loop mencoba ulang hal yang sama berkali-kali (PLC tiap
200 ms, kamera tiap 100 ms, master data tiap 5 menit).

Murni: tidak menulis log sendiri. Pemanggil yang memutuskan level dan kalimatnya,
karena "PLC tidak bisa disambung" dan "master data ditolak AutoERP" butuh level dan
traceback yang berbeda. Satu pemilik per objek (satu thread atau satu loop asyncio),
jadi tanpa kunci.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class PelacakTransisi:
    """Tahu apakah sebuah sumber sedang gagal, sejak kapan, dan jenis galatnya."""

    def __init__(self, *, jam: Callable[[], float] = time.monotonic) -> None:
        self._jam = jam
        self._sejak: float | None = None
        self._jenis: str | None = None

    @property
    def putus(self) -> bool:
        return self._sejak is not None

    def gagal(self, jenis: str = "") -> bool:
        """Catat satu kegagalan. True kalau ini AWAL kejadian yang pantas ditulis.

        Awal = sebelumnya sehat, atau jenis galatnya berganti di tengah kejadian yang
        sama (jaringan putus lalu kunci ditolak adalah dua masalah, bukan satu). Jam
        mulai kejadian tidak ikut bergeser saat jenisnya berganti, supaya lama putus
        yang dilaporkan saat pulih tetap jujur.
        """
        if self._sejak is None:
            self._sejak = self._jam()
            self._jenis = jenis
            return True
        if jenis != self._jenis:
            self._jenis = jenis
            return True
        return False

    def pulih(self) -> float | None:
        """Catat satu keberhasilan. Detik lamanya gagal kalau tadinya gagal, else None."""
        if self._sejak is None:
            return None
        lama = max(0.0, self._jam() - self._sejak)
        self._sejak = None
        self._jenis = None
        return lama


def teks_lama(detik: float) -> str:
    """Lama putus untuk dibaca manusia di log: `3 detik`, `12 menit`, `2 jam 5 menit`."""
    utuh = int(max(0.0, detik))
    if utuh < 60:
        return f"{max(1, utuh)} detik"
    menit = utuh // 60
    if menit < 60:
        return f"{menit} menit"
    jam, sisa = divmod(menit, 60)
    return f"{jam} jam {sisa} menit" if sisa else f"{jam} jam"
