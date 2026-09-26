"""Tab Riwayat: filter grading hari-hari sebelumnya, murni tanpa I/O.

Layar, halaman API, dan unduhan CSV memakai filter yang SAMA dari sini, jadi
angka di layar dan di berkas tidak bisa berbeda karena dua aturan.

Rentang paling panjang 31 hari. Sebulan penuh muat, dan satu permintaan tidak
bisa memaksa konsol memindai data bertahun-tahun: pabrik bisa menggrading
puluhan ribu janjang sehari, dan query itu berjalan di PC yang sama dengan
grading.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .operator_error import (
    RIWAYAT_RENTANG_PANJANG,
    RIWAYAT_RENTANG_TERBALIK,
    RIWAYAT_TANGGAL_TIDAK_SAH,
    InvalidInput,
)
from .plate import normalisasi_plat

MAKS_HARI = 31
HARI_BAWAAN = 7
TAMPILAN = ("hari", "truk", "janjang")
HASIL = ("ripe", "unripe", "jk", "tp")

# Awalan yang membuat Excel/LibreOffice menjalankan isi sel sebagai rumus.
_AWALAN_RUMUS = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True)
class FilterRiwayat:
    """Tanggal kerja `YYYY-MM-DD`, inklusif di kedua ujung.

    `plat` sudah dinormalkan (`BE1234AB`) dan dicocokkan sebagai potongan: operator
    mengetik "be 1234" dan truk "BE 1234 AB" tetap ketemu.
    """

    dari: str
    sampai: str
    line_code: str | None = None
    plat: str | None = None
    hasil: str | None = None


def _tanggal(teks: str) -> date:
    # `fromisoformat` di 3.11 menerima bentuk lain juga ("20260926"); layar cuma
    # pernah mengirim YYYY-MM-DD, jadi bentuknya dipatok dulu.
    try:
        if len(teks) != 10:
            raise ValueError(teks)
        return date.fromisoformat(teks)
    except ValueError:
        raise InvalidInput(
            RIWAYAT_TANGGAL_TIDAK_SAH, f"tanggal tidak sah: {teks!r}", tanggal=teks
        ) from None


def _kosong_jadi_none(teks: str | None) -> str | None:
    teks = (teks or "").strip()
    return teks or None


def buat_filter(
    *,
    dari: str | None = None,
    sampai: str | None = None,
    line_code: str | None = None,
    plat: str | None = None,
    hasil: str | None = None,
    hari_ini: str,
) -> FilterRiwayat:
    """Filter yang sudah dibersihkan, atau `InvalidInput` dengan kode untuk layar.

    Tanpa tanggal sama sekali = 7 hari terakhir sampai hari ini. Cuma `dari` =
    sampai hari ini, tapi tidak lewat dari 31 hari: tanggal tiga bulan lalu tanpa
    ujung akhir lebih masuk akal dibaca sebagai "sebulan sejak itu" daripada ditolak.
    """
    ujung = _tanggal(hari_ini)
    akhir = _tanggal(sampai) if _kosong_jadi_none(sampai) else None
    awal = _tanggal(dari) if _kosong_jadi_none(dari) else None
    if akhir is None:
        akhir = ujung if awal is None else max(awal, min(ujung, awal + timedelta(days=MAKS_HARI - 1)))
    if awal is None:
        awal = akhir - timedelta(days=HARI_BAWAAN - 1)
    if awal > akhir:
        raise InvalidInput(RIWAYAT_RENTANG_TERBALIK, "tanggal awal sesudah tanggal akhir")
    if (akhir - awal).days + 1 > MAKS_HARI:
        raise InvalidInput(
            RIWAYAT_RENTANG_PANJANG, f"rentang lebih dari {MAKS_HARI} hari", maks=MAKS_HARI
        )

    hasil = _kosong_jadi_none(hasil)
    if hasil is not None:
        hasil = hasil.lower()
        if hasil not in HASIL:
            raise ValueError(f"hasil tidak dikenal: {hasil!r}")
    plat = _kosong_jadi_none(plat)
    if plat is not None:
        try:
            plat = normalisasi_plat(plat)
        except ValueError:
            plat = None  # cuma tanda baca: sama dengan tidak menyaring
    return FilterRiwayat(
        dari=awal.isoformat(),
        sampai=akhir.isoformat(),
        line_code=_kosong_jadi_none(line_code),
        plat=plat,
        hasil=hasil,
    )


def aman_untuk_csv(nilai: object) -> object:
    """Isi satu sel CSV. Teks yang diawali tanda rumus diberi `'` di depannya.

    Nama supplier datang dari AutoERP dan plat dari ketikan operator; berkas CSV
    dibuka di Excel kantor, yang menjalankan `=...` sebagai rumus. Angka tetap
    angka supaya bisa dijumlah.
    """
    if nilai is None:
        return ""
    if isinstance(nilai, str) and nilai.startswith(_AWALAN_RUMUS):
        return "'" + nilai
    return nilai


def rasio_ripe(acc: int, total: int) -> int | None:
    """Persen janjang ACC, dibulatkan seperti `Math.round` di layar.

    Dari verdict, bukan kelas: sama dengan kartu line dan tab Rekap, supaya baris
    lama tanpa kelas tidak menyeret rasionya ke nol. `round()` Python memakai
    pembulatan bankir (12,5 jadi 12), jadi CSV akan beda satu persen dari layar.
    """
    if not total:
        return None
    return math.floor(acc * 100 / total + 0.5)


ANGKA = ("total", "acc", "rej", "ripe", "unripe", "jk", "tanpa_kelas", "tp")


def ringkas_periode(hari: list[dict[str, Any]], *, per_line: bool) -> dict[str, Any]:
    """Angka satu periode, dijumlah dari baris per hari (satu pindaian, bukan dua).

    `neto_kg` None saat disaring per line (neto itu berat truk, dan truk tidak
    dibongkar per line) atau kalau belum ada tiket yang timbang keluar: tidak ada
    neto berarti tidak tahu, bukan nol kilo.
    """
    hasil: dict[str, Any] = {k: sum(int(r.get(k) or 0) for r in hari) for k in ANGKA}
    hasil["hari"] = len(hari)
    hasil["truk"] = sum(int(r.get("truk") or 0) for r in hari)
    neto = [r["neto_kg"] for r in hari if r.get("neto_kg") is not None]
    hasil["neto_kg"] = None if per_line or not neto else round(sum(neto), 3)
    return hasil
