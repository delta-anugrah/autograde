"""Jawaban AutoERP untuk satu kunjungan yang butuh orang (batch 2.3). Murni, tanpa I/O.

AutoERP tidak pernah menulis ulang tiket yang sudah final (`upsert_visit` →
`_after_finalisation` di autoerp `erpnext/palm_mill/api.py`): angka yang berbeda cuma
meninggalkan komentar dan tanda `grading_revised`, dan jawabannya membawa
`revised: true` + `note`. Tiket yang dibatalkan menjawab `note` tanpa mengambil apa
pun. Dua keadaan itu yang harus terlihat di pabrik, karena rekap yang dibayar tidak
lagi sama dengan yang dihitung kamera. `visit unchanged` (kirim ulang harian untuk
tiket final yang angkanya sama) bukan berita.
"""
from __future__ import annotations

from dataclasses import dataclass

TIKET_FINAL_BERBEDA = "tiket_final_berbeda"
TIKET_DIBATALKAN = "tiket_dibatalkan"

_CATATAN_BATAL = "ticket cancelled"
_CATATAN_REVISI = "revised"

_KEJADIAN = {
    TIKET_FINAL_BERBEDA: (
        "tiket AutoERP {tiket} sudah final saat data terbaru kunjungan ini tiba, "
        "angka yang dibukukan tidak berubah"
    ),
    TIKET_DIBATALKAN: "tiket AutoERP {tiket} sudah dibatalkan, kunjungan ini tidak dibukukan",
}
_TINDAKAN = {
    TIKET_FINAL_BERBEDA: (
        "minta backoffice memeriksa tiket {tiket} di AutoERP (tanda grading_revised dan komentarnya)"
    ),
    TIKET_DIBATALKAN: "minta backoffice memeriksa kenapa tiket {tiket} dibatalkan",
}


@dataclass(frozen=True)
class KonteksKunjungan:
    """Yang dibaca support di satu baris tab Log: truk, line, jam, tiket, kata AutoERP."""

    plat: str
    line: str
    masuk: str
    tiket: str
    catatan: str


def golongkan(note: str | None, *, revised: bool = False) -> str | None:
    """Kode keadaan yang butuh orang, atau None kalau jawabannya bukan berita."""
    teks = (note or "").lower()
    if teks.startswith(_CATATAN_BATAL):
        return TIKET_DIBATALKAN
    if revised or _CATATAN_REVISI in teks:
        return TIKET_FINAL_BERBEDA
    return None


def kabar_baru(note: str | None, *, revised: bool = False, sebelumnya: str | None = None) -> str | None:
    """Kode yang layak satu WARNING: butuh orang DAN belum pernah dijawab persis begini.

    Kirim ulang harian mengirim rekap yang sama lagi, dan AutoERP (yang membandingkan
    dengan angka yang dibukukan, bukan dengan kiriman terakhir) menjawab kalimat yang
    sama lagi. Itu bukan kejadian baru; tandanya di tab Timbangan tetap ada.
    """
    golongan = golongkan(note, revised=revised)
    if golongan is None or (note and note == sebelumnya):
        return None
    return golongan


def jam_masuk(entered_at: str | None) -> str:
    """`2026-09-28T07:41:09+07:00` jadi `2026-09-28 07:41`: jam pabrik apa adanya."""
    if not entered_at:
        return "-"
    return entered_at[:16].replace("T", " ")


def pesan_log(golongan: str, konteks: KonteksKunjungan) -> str:
    """Satu baris tab Log: kode, truk, line, jam timbang masuk, apa yang terjadi, tindakan."""
    return (
        f"[{golongan.upper()}] Truk {konteks.plat}, {konteks.line}, timbang masuk {konteks.masuk}: "
        f"{_KEJADIAN[golongan].format(tiket=konteks.tiket)}. "
        f"Tindakan: {_TINDAKAN[golongan].format(tiket=konteks.tiket)}. "
        f"Jawaban AutoERP: {konteks.catatan}"
    )
