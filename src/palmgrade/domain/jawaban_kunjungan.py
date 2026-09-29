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
from datetime import datetime
from zoneinfo import ZoneInfo

TIKET_FINAL_BERBEDA = "tiket_final_berbeda"
TIKET_DIBATALKAN = "tiket_dibatalkan"
#: Tiket yang belum diketahui nomornya. Bukan "-": di tengah kalimat itu terbaca sebagai jeda.
TANPA_NOMOR = "(tanpa nomor)"

_CATATAN_BATAL = "ticket cancelled"
_CATATAN_REVISI = "revised"
# Potongan `note` AutoERP (`_after_finalisation`) → kata yang dibaca support.
_YANG_BERUBAH = (("grading revised", "grading berubah"), ("weights revised", "berat berubah"))

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
    #: Rekap pabrik SEKARANG (yang baru dikirim), None kalau belum ada janjang.
    janjang: int | None = None
    mentah: int | None = None


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


def jam_masuk(entered_at: str | None, tz: ZoneInfo) -> str:
    """Jam timbang masuk dalam jam pabrik, tanpa detik: sama dengan baris tab Timbangan.

    Tombol Timbang masuk mengirim `new Date().toISOString()` (UTC, `Z`); tanpa konversi
    07:41 WIB tertulis 00:41, dan shift malam mendapat tanggal kemarin. Jam tanpa zona
    sudah jam pabrik. Yang tidak bisa dibaca ditulis apa adanya, bukan dibuang.
    """
    if not entered_at:
        return "-"
    try:
        jam = datetime.fromisoformat(entered_at)
    except ValueError:
        return entered_at[:16].replace("T", " ")
    if jam.tzinfo is not None:
        jam = jam.astimezone(tz)
    return jam.strftime("%Y-%m-%d %H:%M")


def pesan_log(golongan: str, konteks: KonteksKunjungan) -> str:
    """Satu baris tab Log: kode, truk, line, jam timbang masuk, apa yang terjadi, apa yang
    berbeda, rekap pabrik sekarang, tindakan, lalu kalimat AutoERP apa adanya."""
    return (
        f"[{golongan.upper()}] Truk {konteks.plat}, {konteks.line}, timbang masuk {konteks.masuk}: "
        f"{_KEJADIAN[golongan].format(tiket=konteks.tiket)}. "
        f"{_yang_berbeda(konteks.catatan)}{_rekap(konteks)}"
        f"Tindakan: {_TINDAKAN[golongan].format(tiket=konteks.tiket)}. "
        f"Jawaban AutoERP: {konteks.catatan}"
    )


def _yang_berbeda(catatan: str) -> str:
    kata = [indonesia for inggris, indonesia in _YANG_BERUBAH if inggris in catatan.lower()]
    return f"Yang berbeda: {', '.join(kata)}. " if kata else ""


def _rekap(konteks: KonteksKunjungan) -> str:
    if not konteks.janjang:
        return ""
    persen = f"{round((konteks.mentah or 0) / konteks.janjang * 100, 1):g}".replace(".", ",")
    return f"Rekap pabrik sekarang: {konteks.janjang} janjang, mentah {persen}%. "
