"""Tab Riwayat: grading hari-hari sebelumnya untuk layar dan untuk CSV.

Layar dan berkas memakai filter dan query yang SAMA (`domain/riwayat.py`,
`repositories/riwayat_repository.py`), jadi angka di CSV tidak bisa berbeda dari
yang terlihat di layar. Per hari dan per truk dikirim utuh (paling banyak 31
baris / beberapa ribu baris sebulan) dan dibagi halaman di layar; per janjang
dibagi halaman di server karena sebulan bisa jutaan baris.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..domain.riwayat import (
    MAKS_HARI,
    FilterRiwayat,
    aman_untuk_csv,
    buat_filter,
    rasio_ripe,
    ringkas_periode,
)
from ..repositories.riwayat_repository import RiwayatStore
from .console_service import _capture_url, _with_source_label

# Kepala kolom CSV per bahasa layar. Urutannya = urutan nilai di `_baris_*`.
_KEPALA = {
    "hari": {
        "id": ["Tanggal kerja", "Janjang", "Ripe", "Unripe", "JK", "TP", "Tanpa kelas", "ACC",
               "REJ", "Rasio Ripe (%)", "Truk", "Neto (kg)"],
        "en": ["Work date", "Bunches", "Ripe", "Unripe", "JK", "TP", "No class", "ACC", "REJ",
               "Ripe ratio (%)", "Trucks", "Net (kg)"],
    },
    "truk": {
        "id": ["Tanggal kerja", "Plat", "Supplier", "Sumber", "Janjang", "Ripe", "Unripe", "JK",
               "TP", "Tanpa kelas", "ACC", "REJ", "Rasio Ripe (%)", "Neto (kg)", "Mulai",
               "Selesai"],
        "en": ["Work date", "Plate", "Supplier", "Source", "Bunches", "Ripe", "Unripe", "JK",
               "TP", "No class", "ACC", "REJ", "Ripe ratio (%)", "Net (kg)", "First", "Last"],
    },
    "janjang": {
        "id": ["Tanggal kerja", "Waktu", "Line", "Plat", "Supplier", "Sumber", "Kelas", "Hasil",
               "TP", "Jenis", "Foto", "Event ID"],
        "en": ["Work date", "Time", "Line", "Plate", "Supplier", "Source", "Class", "Result",
               "TP", "Capture", "Photo", "Event ID"],
    },
}
_YA = {"id": "ya", "en": "yes"}
_JENIS = {"id": {"auto": "otomatis", "manual": "manual"}, "en": {"auto": "auto", "manual": "manual"}}
_TANPA_TRUK = {"id": "Tanpa truk", "en": "No truck"}

# Baris per potongan yang dialirkan. Kecil cukup supaya unduhan sebulan tidak
# pernah utuh di memori, besar cukup supaya tidak ribuan potongan kecil.
_BARIS_PER_POTONG = 500


def _kg(nilai: float | None) -> float | int | None:
    """Neto tanpa `.0` di belakang angka bulat: `7000`, bukan `7000.0`."""
    if nilai is None:
        return None
    return int(nilai) if float(nilai).is_integer() else round(float(nilai), 3)


class RiwayatService:
    def __init__(
        self, store: RiwayatStore, *, hari_ini: Callable[[], str], zona: str
    ) -> None:
        self._store = store
        self._hari_ini = hari_ini
        self._zona = ZoneInfo(zona)

    def filter(self, **isian: str | None) -> FilterRiwayat:
        """`dari`/`sampai`/`line_code`/`plat`/`hasil` dari permintaan, dibersihkan."""
        return buat_filter(**isian, hari_ini=self._hari_ini())

    # ----------------------------------------------------------------- layar

    def halaman(
        self, f: FilterRiwayat, *, tampilan: str, limit: int, offset: int, ringkasan: bool
    ) -> dict[str, Any]:
        """Satu jawaban untuk layar. `ringkasan` cuma dihitung kalau diminta: layar
        memintanya saat filter berubah, tidak saat pindah halaman atau tampilan."""
        hari = self._store.hari(f) if tampilan == "hari" or ringkasan else None
        if tampilan == "hari":
            items, total = hari, len(hari)
        elif tampilan == "truk":
            items = [_with_source_label(r) for r in self._store.truk(f)]
            total = len(items)
        else:
            baris, total = self._store.janjang(f, limit=limit, offset=offset)
            items = [self._janjang_layar(r) for r in baris]
        jawaban: dict[str, Any] = {
            "dari": f.dari,
            "sampai": f.sampai,
            "hari_ini": self._hari_ini(),
            "maks_hari": MAKS_HARI,
            "tampilan": tampilan,
            "items": items,
            "total": total,
        }
        if ringkasan:
            jawaban["ringkasan"] = ringkas_periode(hari, per_line=bool(f.line_code))
        return jawaban

    @staticmethod
    def _janjang_layar(row: dict[str, Any]) -> dict[str, Any]:
        row["image_url"] = _capture_url(row.get("line_code"), row.get("image_path"))
        return _with_source_label(row)

    # ------------------------------------------------------------------- CSV

    def csv(
        self, f: FilterRiwayat, *, tampilan: str, bahasa: str
    ) -> tuple[str, Iterator[bytes]]:
        """Nama berkas dan isinya, dialirkan per potongan.

        Semua baris filter itu, bukan cuma halaman yang sedang dilihat: yang
        mengunduh CSV hampir selalu mau menjumlahkannya sendiri.
        """
        bahasa = "en" if bahasa == "en" else "id"
        nama = f"riwayat-grading-{tampilan}-{f.dari}_{f.sampai}.csv"
        return nama, self._alirkan(f, tampilan, bahasa)

    def _alirkan(self, f: FilterRiwayat, tampilan: str, bahasa: str) -> Iterator[bytes]:
        if tampilan == "hari":
            sumber: Iterable[list[Any]] = (self._baris_hari(r) for r in self._store.hari(f))
        elif tampilan == "truk":
            sumber = (self._baris_truk(r, bahasa) for r in self._store.truk(f))
        else:
            sumber = (self._baris_janjang(r, bahasa) for r in self._store.semua_janjang(f))
        buffer = io.StringIO()
        penulis = csv.writer(buffer, lineterminator="\r\n")
        # BOM: tanpa itu Excel membaca berkas UTF-8 sebagai ANSI, dan nama supplier
        # beraksen jadi huruf acak.
        yield "﻿".encode()
        penulis.writerow(_KEPALA[tampilan][bahasa])
        for nomor, baris in enumerate(sumber, start=1):
            penulis.writerow([aman_untuk_csv(v) for v in baris])
            if nomor % _BARIS_PER_POTONG == 0:
                yield buffer.getvalue().encode()
                buffer.seek(0)
                buffer.truncate()
        yield buffer.getvalue().encode()

    @staticmethod
    def _angka(r: dict[str, Any]) -> list[Any]:
        return [r["total"], r["ripe"], r["unripe"], r["jk"], r["tp"], r["tanpa_kelas"],
                r["acc"], r["rej"], rasio_ripe(r["acc"], r["total"])]

    def _baris_hari(self, r: dict[str, Any]) -> list[Any]:
        return [r["work_date"], *self._angka(r), r["truk"], _kg(r["neto_kg"])]

    def _baris_truk(self, r: dict[str, Any], bahasa: str) -> list[Any]:
        r = _with_source_label(dict(r))
        plat = r.get("plate_number") or ("" if r.get("truck_id") else _TANPA_TRUK[bahasa])
        return [
            r["work_date"], plat, r.get("supplier_name"), r.get("source_label"),
            *self._angka(r), _kg(r["neto_kg"]),
            self._waktu(r.get("mulai")), self._waktu(r.get("selesai")),
        ]

    def _baris_janjang(self, r: dict[str, Any], bahasa: str) -> list[Any]:
        r = _with_source_label(dict(r))
        tp = r.get("tp_confidence")
        return [
            r["work_date"], self._waktu(r["timestamp"]), r["line_code"], r.get("plate_number"),
            r.get("supplier_name"), r.get("source_label"), r.get("grade_class"),
            r["ripeness_status"], _YA[bahasa] if tp is not None and tp > 0.8 else "",
            _JENIS[bahasa].get(r.get("capture_type"), r.get("capture_type")),
            _capture_url(r.get("line_code"), r.get("image_path")), r["event_id"],
        ]

    def _waktu(self, iso: str | None) -> str | None:
        """Jam pabrik (`FACTORY_TZ`), bukan UTC: yang membaca CSV mencocokkannya
        dengan jam di dinding pabrik. Stempel tanpa zona dianggap UTC, seperti
        kontrak event (`timestamp` UTC-aware)."""
        if not iso:
            return None
        try:
            waktu = datetime.fromisoformat(iso)
        except ValueError:
            return iso
        if waktu.tzinfo is None:
            waktu = waktu.replace(tzinfo=UTC)
        return waktu.astimezone(self._zona).strftime("%Y-%m-%d %H:%M:%S")
