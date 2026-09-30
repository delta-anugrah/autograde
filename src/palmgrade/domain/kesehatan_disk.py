"""Sisa disk PC pabrik (batch 3.7): aturan murni, tanpa I/O.

Sebelum ini satu-satunya yang melihat disk adalah penjaga retensi
`BatchUploadWorker._retention_by_disk`, dan dia cuma jalan kalau `R2_BUCKET`
terisi (`run_batch_once` berhenti lebih awal tanpanya, TODO L1). PC tanpa R2
mengisi disk sampai habis tanpa satu peringatan pun, lalu `write_image` gagal
dan grading berhenti tersimpan.

Pemantau ini TIDAK menghapus apa pun: tanpa R2, berkas lokal adalah satu-satunya
salinan bukti grading, jadi yang benar adalah memberi tahu manusia, bukan
membuang. Ambangnya dalam GB, bukan persen: yang menentukan berapa lama lagi
disk penuh adalah laju tulis (GB per hari), bukan ukuran disknya.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

#: Sama dengan penjaga retensi (`upload_disk_min_free_gb * 1024**3`), supaya
#: "15 GB" di sini dan "20 GB" di sana dihitung dengan satuan yang sama.
GB = 1024**3

#: Bawaan `DISK_PERINGATAN_GB`. Di BAWAH lantai penjaga retensi (20 GB): dengan
#: R2 aktif penjaga itu menjaga sisa disk di sekitar 20 GB (turun kurang dari
#: 1 GB di antara dua batch per jam), jadi peringatan tidak boleh menyala di
#: keadaan normal itu. Tanpa R2, 15 GB = sekitar 2,5 hari pada laju terukur
#: Lampung (300 janjang/jam/line, 3 line, foto bbox + clean = 6,2 GB/hari).
PERINGATAN_BAWAAN_GB = 15.0
#: Bawaan `DISK_KRITIS_GB`: kurang dari sehari. SQLite (WAL), log Docker, dan
#: image baru juga butuh ruang di disk yang sama; tindakan harus sekarang.
KRITIS_BAWAAN_GB = 5.0
#: Keluar dari satu tingkat baru saat sisa disk naik sebanyak ini di atas
#: ambangnya. Tanpa jarak ini, retensi yang membuang beberapa ratus MB lalu
#: grading yang mengisinya lagi membuat alert muncul-hilang tiap menit.
HISTERESIS_GB = 1.0

KODE_DISK_HAMPIR_PENUH = "DISK_HAMPIR_PENUH"
KODE_DISK_KRITIS = "DISK_KRITIS"


class TingkatDisk(StrEnum):
    AMAN = "aman"
    PERINGATAN = "peringatan"
    KRITIS = "kritis"
    TIDAK_TERBACA = "tidak_terbaca"


_KODE = {TingkatDisk.PERINGATAN: KODE_DISK_HAMPIR_PENUH, TingkatDisk.KRITIS: KODE_DISK_KRITIS}
_URUTAN = {TingkatDisk.PERINGATAN: 1, TingkatDisk.KRITIS: 2}


@dataclass(frozen=True)
class UkuranDisk:
    """Satu partisi yang ditulis line ini. `bebas` = yang bisa dipakai proses
    biasa (`shutil.disk_usage().free`), bukan termasuk jatah root."""

    jalur: str
    total: int
    bebas: int


def tersempit(ukuran: Iterable[UkuranDisk]) -> UkuranDisk | None:
    """Partisi dengan sisa paling kecil: yang habis duluan yang menghentikan
    grading, walau partisi lain masih lega."""
    return min(ukuran, key=lambda u: u.bebas, default=None)


def nilai_disk(
    bebas_gb: float, *, peringatan_gb: float, kritis_gb: float, sebelumnya: TingkatDisk
) -> TingkatDisk:
    """Tingkat sisa disk. Masuk saat sisa DI BAWAH ambang; keluar baru saat sisa
    melewati ambang + `HISTERESIS_GB`. Ambang `<= 0` = tingkat itu dimatikan."""
    naik = _URUTAN.get(sebelumnya, 0)

    def di_bawah(ambang: float, tingkat: TingkatDisk) -> bool:
        if ambang <= 0:
            return False
        batas = ambang + HISTERESIS_GB if naik >= _URUTAN[tingkat] else ambang
        return bebas_gb < batas

    if di_bawah(kritis_gb, TingkatDisk.KRITIS):
        return TingkatDisk.KRITIS
    if di_bawah(peringatan_gb, TingkatDisk.PERINGATAN):
        return TingkatDisk.PERINGATAN
    return TingkatDisk.AMAN


def ke_kawat(
    tingkat: TingkatDisk,
    ukuran: UkuranDisk | None,
    *,
    peringatan_gb: float,
    kritis_gb: float,
    sejak: float | None,
) -> dict[str, Any]:
    """Blok `disk` untuk `/health/detail` dan `/internal/status`. `sejak` = jam
    dinding mulai tingkat sekarang (None saat aman / tidak terbaca)."""
    return {
        "tingkat": tingkat.value,
        "kode": _KODE.get(tingkat),
        "bebas_gb": None if ukuran is None else round(ukuran.bebas / GB, 1),
        "total_gb": None if ukuran is None else round(ukuran.total / GB, 1),
        "persen_bebas": None if not ukuran or not ukuran.total else round(100 * ukuran.bebas / ukuran.total, 1),
        "jalur": None if ukuran is None else ukuran.jalur,
        "ambang_peringatan_gb": peringatan_gb,
        "ambang_kritis_gb": kritis_gb,
        "sejak": sejak,
    }


def gb_dari_teks(teks: str | None, bawaan: float) -> float | None:
    """`DISK_*_GB` → GB. Kosong = bawaan; `0` = dimatikan. None = bukan angka
    atau negatif (pemanggil yang memutuskan dan mencatat)."""
    if teks is None or not teks.strip():
        return bawaan
    try:
        nilai = float(teks.strip().replace(",", "."))
    except ValueError:
        return None
    return nilai if nilai >= 0 else None


def peringatan_menyala_terus(peringatan_gb: float, *, lantai_retensi_gb: float, r2_aktif: bool) -> bool:
    """True kalau peringatan akan menyala di keadaan NORMAL: penjaga retensi
    (hanya dengan R2) menjaga sisa disk di sekitar lantainya, jadi ambang
    peringatan setinggi lantai itu atau lebih berarti alert permanen."""
    return r2_aktif and lantai_retensi_gb > 0 and peringatan_gb >= lantai_retensi_gb
