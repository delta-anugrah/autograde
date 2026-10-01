"""Kontrak log line ke konsol (batch 3.2): bentuk `GET /internal/log` dan cara membacanya.

Line menyimpan WARNING/ERROR-nya sendiri di `state/log_line.db` (container line dibuat
ulang tiap start/restart/pull, dan `docker logs` hilang bersamanya), konsol menariknya
ke `event_log` dengan kursor. Modul ini murni, tanpa I/O: dipakai penulis di line
(`LogLineStore`) dan pembaca di konsol (`TarikLogLineWorker`), jadi dua sisi kawat
tidak bisa menyimpang tanpa test yang merah.

Kursor = (`generasi`, `seq`). `generasi` acak, dibuat sekali saat berkas log line
dibuat: berkas yang dihapus (reset data) memulai generasi baru dan konsol mulai dari
nol lagi, bukan melewatkan baris baru yang nomornya kebetulan lebih kecil. `seq` naik
setiap kali satu baris BERUBAH (baru, atau hitungannya naik karena pesan yang sama
datang lagi), jadi baris yang digabung terbaca ulang dengan hitungan barunya.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Baris log yang disimpan line. Lebih dari ini, baris yang paling lama tidak berubah
#: dibuang. Baris yang sudah ditarik konsol TETAP disimpan (tidak dihapus saat ditarik),
#: jadi batas ini tersentuh juga dalam kerja normal; yang dihitung `dibuang` cuma baris
#: yang tergeser SEBELUM pernah disajikan ke konsol (konsol mati lama DAN line
#: membanjiri log), ditambah kejadian yang dibuang antrean di memori.
BATAS_BARIS_LINE = 2000
#: Traceback dipotong dari DEPAN: yang berguna ada di ekornya (baris exception).
PANJANG_DETAIL_MAKS = 8000
PANJANG_PESAN_MAKS = 2000
PANJANG_SUMBER_MAKS = 200
PANJANG_GENERASI_MAKS = 64
#: Satu halaman `GET /internal/log`. Konsol meminta `BATAS_HALAMAN`, line menolak di atas maks.
BATAS_HALAMAN = 100
BATAS_HALAMAN_MAKS = 500
#: Yang disimpan dan dikirim line: WARNING dan ERROR (CRITICAL sudah jadi ERROR di handler).
LEVEL_SAH = frozenset({"WARNING", "ERROR"})
_TANDA_POTONG = "...(dipotong)\n"


def potong_detail(detail: str | None) -> str | None:
    """Traceback yang terlalu panjang disimpan ekornya saja, dengan tanda dipotong."""
    if not detail or len(detail) <= PANJANG_DETAIL_MAKS:
        return detail
    return _TANDA_POTONG + detail[-(PANJANG_DETAIL_MAKS - len(_TANDA_POTONG)) :]


def potong_pesan(pesan: str) -> str:
    return pesan if len(pesan) <= PANJANG_PESAN_MAKS else pesan[: PANJANG_PESAN_MAKS - 3] + "..."


@dataclass(frozen=True)
class EntriLog:
    """Satu kejadian yang ditulis handler di line, sebelum sampai ke disk."""

    level: str
    source: str
    message: str
    detail: str | None
    at: float


@dataclass(frozen=True)
class EntriTarik:
    """Satu baris log line seperti yang diterima konsol."""

    id: int
    seq: int
    first_at: float
    last_at: float
    level: str
    source: str
    message: str
    detail: str | None
    count: int


@dataclass(frozen=True)
class JawabanLog:
    generasi: str
    entri: tuple[EntriTarik, ...]
    seq_akhir: int
    lagi: bool
    dibuang: int


@dataclass(frozen=True)
class KursorLine:
    """Sampai mana konsol sudah menarik log satu line. Kosong = belum pernah."""

    generasi: str = ""
    seq: int = 0
    dibuang: int = 0


def _bulat(nilai: Any, nama: str, *, minimal: int = 0) -> int:
    if not isinstance(nilai, int) or isinstance(nilai, bool) or nilai < minimal:
        raise ValueError(f"{nama} bukan bilangan bulat >= {minimal}: {nilai!r}")
    return nilai


def _angka(nilai: Any, nama: str) -> float:
    if not isinstance(nilai, (int, float)) or isinstance(nilai, bool):
        raise ValueError(f"{nama} bukan angka: {nilai!r}")
    return float(nilai)


def _teks(nilai: Any, nama: str, maks: int) -> str:
    if not isinstance(nilai, str):
        raise ValueError(f"{nama} bukan teks: {nilai!r}")
    return nilai[:maks]


def _entri(data: Any) -> EntriTarik:
    if not isinstance(data, dict):
        raise ValueError(f"entri bukan objek: {data!r}")
    level = data.get("level")
    if level not in LEVEL_SAH:
        raise ValueError(f"level asing: {level!r}")
    detail = data.get("detail")
    if detail is not None and not isinstance(detail, str):
        raise ValueError(f"detail bukan teks: {detail!r}")
    return EntriTarik(
        id=_bulat(data.get("id"), "id", minimal=1),
        seq=_bulat(data.get("seq"), "seq", minimal=1),
        first_at=_angka(data.get("first_at"), "first_at"),
        last_at=_angka(data.get("last_at"), "last_at"),
        level=level,
        source=_teks(data.get("source"), "source", PANJANG_SUMBER_MAKS),
        message=potong_pesan(_teks(data.get("message"), "message", PANJANG_PESAN_MAKS)),
        detail=potong_detail(detail),
        count=_bulat(data.get("count"), "count", minimal=1),
    )


def baca_jawaban_log(data: Any) -> JawabanLog:
    """Jawaban `GET /internal/log` yang sudah diperiksa. `ValueError` kalau bentuknya asing.

    Konsol tidak menyimpan satu baris pun dari jawaban yang cacat: kursornya tidak maju,
    jadi tarikan berikutnya meminta halaman yang sama lagi.
    """
    if not isinstance(data, dict):
        raise ValueError(f"jawaban log bukan objek: {str(data)[:200]}")
    generasi = _teks(data.get("generasi"), "generasi", PANJANG_GENERASI_MAKS)
    if not generasi:
        raise ValueError("generasi kosong")
    entri = data.get("entri")
    if not isinstance(entri, list):
        raise ValueError("entri bukan daftar")
    lagi = data.get("lagi")
    if not isinstance(lagi, bool):
        raise ValueError(f"lagi bukan boolean: {lagi!r}")
    return JawabanLog(
        generasi=generasi,
        entri=tuple(_entri(e) for e in entri),
        seq_akhir=_bulat(data.get("seq_akhir"), "seq_akhir"),
        lagi=lagi,
        dibuang=_bulat(data.get("dibuang"), "dibuang"),
    )


def mulai_dari(kursor_seq: int, kursor_generasi: str, generasi_line: str) -> int:
    """Seq tempat line mulai membaca: kursor konsol, atau 0 kalau berkasnya generasi lain."""
    return kursor_seq if kursor_generasi == generasi_line else 0
