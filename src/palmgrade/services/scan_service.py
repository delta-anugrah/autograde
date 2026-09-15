"""Scan QR di gerbang timbangan: satu plat masuk, satu truk keluar.

Dua tahap scan, dua-duanya di gerbang, dua-duanya menggantikan **ketikan yang
sungguhan ada**: timbang masuk dan timbang keluar. Tahap sortir tidak di-scan —
yang tahu bak sudah kosong itu operator line, bukan supir yang datang membawa HP,
dan tombolnya sudah ada di depan mata operator.

Lapisan ini **cuma mencari**. Dia tidak membuat truk dan tidak menyentuh berat:

- kalau scan ikut membuat truk, satu QR salah baca menambah truk hantu ke master
  data, dan truk itu naik ke AutoERP lewat interface B
- kalau scan ikut menulis berat, ada dua tempat yang bisa menulis angka yang
  dibayar ke petani. Yang mencatat berat tetap `ConsoleService.catat_timbangan`

Truk yang belum terdaftar (truk pinjaman) dijawab "belum ada", dan layar yang
menawarkan input manual. Itu satu-satunya jalur yang masih diketik tangan, dan
memang harus tetap ada: layar HP retak, gelap, atau kena matahari langsung adalah
kasus nyata di gerbang pabrik.
"""

from __future__ import annotations

import logging
from typing import Any

from ..domain.plate import truck_id_for
from ..domain.qr import baca_qr
from ..repositories.console_repository import ConsoleStore

logger = logging.getLogger(__name__)


class ScanService:
    """Pencarian truk dari hasil scan. Tidak menulis apa pun."""

    def __init__(self, store: ConsoleStore) -> None:
        self.store = store

    def cari(self, teks_qr: str) -> dict[str, Any]:
        """Hasil bacaan scanner → truk yang sudah ada, atau "belum ada".

        Id-nya diturunkan dari plat, sama seperti `catat_timbangan` — bukan query
        kolom plat tersendiri. Satu aturan untuk dua jalur: kalau pencarian di sini
        memakai aturan lain, satu kunjungan bisa mendarat di truk yang berbeda dari
        yang dipakai saat menimbang.
        """
        plat = baca_qr(teks_qr)  # menolak yang bukan plat
        truk = self.store.truck(truck_id_for(plat))

        if truk is None:
            logger.info("Scan %s: truk belum terdaftar", plat)
            return {"ditemukan": False, "plate_number": plat, "truck": None}

        return {"ditemukan": True, "plate_number": plat, "truck": truk}
