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

    def tiket_terbuka(self, teks_qr: str, tanggal_kerja: str) -> dict[str, Any]:
        """Scan kedua, di gerbang keluar: tiket mana yang sedang menunggu tara.

        Operator scan platnya, sistem yang mencari tiketnya — bukan operator yang
        menyusuri tabel mencari baris truk itu di antara puluhan baris hari ini.

        **Dua tiket terbuka ditolak, tidak ditebak** (keputusan operator 2026-09-15):
        menebak di sini bisa memasangkan tara ke kunjungan yang salah dan mencampur
        tonase dua kunjungan — persis bentuk bug adopsi tiket yang kami laporkan ke
        AutoERP. Layar menampilkan keduanya dan operator memilih sendiri.
        """
        plat = baca_qr(teks_qr)
        terbuka = self.store.weighings_terbuka(truck_id_for(plat), tanggal_kerja)

        if len(terbuka) == 1:
            return {"ditemukan": True, "plate_number": plat, "weighing": terbuka[0]}

        if len(terbuka) > 1:
            logger.info("Scan keluar %s: %d tiket terbuka, minta operator memilih",
                        plat, len(terbuka))
            return {
                "ditemukan": False, "ganda": True,
                "plate_number": plat, "pilihan": terbuka,
            }

        logger.info("Scan keluar %s: tidak ada tiket terbuka hari ini", plat)
        return {"ditemukan": False, "plate_number": plat, "weighing": None}
