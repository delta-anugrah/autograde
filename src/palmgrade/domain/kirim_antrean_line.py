"""Aturan mengirim antrean janjang line ke konsol (batch 2.4, 2026-09-28).

Murni, tanpa I/O: dipakai `OutboxStore` (jeda per baris, umur janjang) dan
`OutboxRetryWorker` (arti jawaban konsol, jeda sambungan).

Keputusan user 2026-09-28: antrean ini TIDAK punya batas nyerah. Dulu baris yang
gagal 50 kali (kira-kira 7,3 jam konsol mati) berhenti dicoba selamanya dan
janjangnya tidak pernah sampai ke rekap. Sekarang setiap baris dicoba sampai
terkirim; yang dijaga adalah lajunya, bukan jumlah percobaannya.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

#: Jeda satu baris sesudah konsol MENOLAK baris itu: 5 dtk, berlipat, maks 10 menit.
JEDA_BARIS_DASAR_S = 5.0
JEDA_BARIS_MAKS_S = 600.0
#: Jeda seluruh pengiriman sesudah KONSOL bermasalah: 5 dtk, berlipat, maks 30 dtk.
#: Satu permintaan per jeda: konsol yang mati semalaman dicolek paling banyak dua
#: kali semenit, dan kembalinya ketahuan dalam 30 detik.
JEDA_SAMBUNGAN_DASAR_S = 5.0
JEDA_SAMBUNGAN_MAKS_S = 30.0
#: Tanpa batas nyerah `ke` bisa jutaan, dan 2**jutaan adalah bilangan ratusan ribu
#: digit yang dihitung ulang tiap gagal. 2**30 sudah jauh melewati maks mana pun.
_PANGKAT_MAKS = 30

SEBAB_TAK_TERJANGKAU = "tak_terjangkau"
SEBAB_KUNCI_DITOLAK = "kunci_ditolak"
SEBAB_ALAMAT_SALAH = "alamat_salah"
SEBAB_KONSOL_GALAT = "konsol_galat"

_KUNCI = frozenset({401, 403})
_ALAMAT = frozenset({404, 405})
_KONSOL_SIBUK = frozenset({408, 429})


def jeda_mundur(ke: int, *, dasar: float, maks: float) -> float:
    """Jeda sesudah gagal ke-`ke` (mulai 1): dasar, 2x, 4x, ... sampai `maks`."""
    pangkat = min(max(ke - 1, 0), _PANGKAT_MAKS)
    return min(dasar * (2**pangkat), maks)


class Nasib(Enum):
    TERKIRIM = "terkirim"
    #: Konsol menjawab tapi menolak BARIS ini (400, 422, ...). Baris lain tetap jalan.
    DITOLAK = "ditolak"
    #: Konsol sendiri bermasalah: semua baris akan gagal dengan cara yang sama.
    KONSOL_BERMASALAH = "konsol_bermasalah"


@dataclass(frozen=True)
class Putusan:
    nasib: Nasib
    #: Salah satu `SEBAB_*`, hanya untuk `KONSOL_BERMASALAH`.
    sebab: str | None = None


def nilai_jawaban(status: int, teks: str) -> Putusan:
    """Arti satu jawaban HTTP konsol bagi antrean.

    `already_processed` di badan jawaban = sudah sampai (kontrak palmgrade-api;
    konsol sendiri menjawab 201 untuk event yang sudah ada). 5xx = konsol
    bermasalah, beda dari antrean AutoERP yang menganggap 500 "tersambung": di
    sini 500 hampir selalu berarti disk atau SQLite konsol, dan mencoba ribuan
    baris ke konsol seperti itu cuma membanjiri log di dua sisi. Baris beracun
    yang memang memicu 500 tetap tidak menahan antrean: dia mundur sendiri, dan
    percobaan sambungan berikutnya memakai baris yang lebih jarang dicoba.
    """
    if 200 <= status < 300 or "already_processed" in teks:
        return Putusan(Nasib.TERKIRIM)
    if status in _KUNCI:
        return Putusan(Nasib.KONSOL_BERMASALAH, SEBAB_KUNCI_DITOLAK)
    if status in _ALAMAT or 300 <= status < 400:
        return Putusan(Nasib.KONSOL_BERMASALAH, SEBAB_ALAMAT_SALAH)
    if 400 <= status < 500 and status not in _KONSOL_SIBUK:
        return Putusan(Nasib.DITOLAK)
    return Putusan(Nasib.KONSOL_BERMASALAH, SEBAB_KONSOL_GALAT)


def waktu_janjang(payload: str, cadangan: float) -> float:
    """Kapan janjang itu digrading (epoch detik), dari `timestamp` di payload-nya.

    Mengisi `dibuat_at` baris dari versi sebelum kolom itu ada. `cadangan` (jam
    buka) kalau payload tidak terbaca: umur yang sedikit terlalu muda lebih baik
    daripada baris yang tidak bisa ditampilkan. Tanpa zona dibaca UTC, sama
    dengan `domain/working_day.py`.
    """
    try:
        teks = str(json.loads(payload)["timestamp"]).strip().replace("Z", "+00:00")
        waktu = datetime.fromisoformat(teks)
    except (ValueError, KeyError, TypeError):
        return cadangan
    if waktu.tzinfo is None:
        waktu = waktu.replace(tzinfo=UTC)
    return waktu.timestamp()


@dataclass
class SambunganKonsol:
    """Keadaan jalur line ke konsol menurut percobaan terakhir, dan kapan boleh mencoba lagi.

    `tersambung` None = belum pernah mencoba sejak proses mulai. Jeda di sini
    berlaku untuk SELURUH pengiriman, terpisah dari jeda per baris di `OutboxStore`.
    """

    tersambung: bool | None = None
    putus_sejak: float | None = None
    sebab: str | None = None
    gagal_beruntun: int = 0
    coba_lagi_at: float = 0.0

    def boleh_coba(self, sekarang: float) -> bool:
        return sekarang >= self.coba_lagi_at

    def gagal(self, sekarang: float, *, sebab: str) -> bool:
        """Konsol bermasalah. True kalau ini kabar baru: baru putus, atau sebabnya berganti."""
        kabar_baru = self.putus_sejak is None or sebab != self.sebab
        if self.putus_sejak is None:
            self.putus_sejak = sekarang
        self.tersambung = False
        self.sebab = sebab
        self.gagal_beruntun += 1
        self.coba_lagi_at = sekarang + jeda_mundur(
            self.gagal_beruntun, dasar=JEDA_SAMBUNGAN_DASAR_S, maks=JEDA_SAMBUNGAN_MAKS_S
        )
        return kabar_baru

    def berhasil(self) -> bool:
        """Konsol menjawab. True kalau sebelumnya belum tersambung (baru boot atau baru pulih)."""
        baru = self.tersambung is not True
        self.tersambung = True
        self.putus_sejak = None
        self.sebab = None
        self.gagal_beruntun = 0
        self.coba_lagi_at = 0.0
        return baru

    def bangunkan(self) -> None:
        """Kirim Ulang dari layar: boleh mencoba sekarang, keadaan putus tetap tercatat."""
        self.coba_lagi_at = 0.0
