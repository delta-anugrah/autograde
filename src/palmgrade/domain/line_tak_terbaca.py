"""Kenapa konsol tidak bisa membaca satu line, sebagai kode kecil (keputusan user 2026-10-01).

Di luar tab Log tidak boleh ada teks galat sistem di layar. Kartu Diagnostik dan tabel
Antrean line dulu menulis alasan mentahnya apa adanya ("line-1 did not answer: Client
error '404 Not Found' for url ..."). Sekarang backend memilih SATU kode dari kode galat
operator dan status HTTP-nya, layar menerjemahkannya lewat KAMUS (`lineSebab_<kode>`),
dan alasan mentahnya cuma ke tab Log (`LineStatusWorker`, satu WARNING per kejadian).

Murni: dipakai `DevService` (kartu Diagnostik), `PantauAntreanLine` (Antrean line), dan
`LineStatusWorker` (log transisi), yang masing-masing memegang exception-nya sendiri.
"""
from __future__ import annotations

from .operator_error import LINE_TIDAK_MENJAWAB

#: Tidak ada jawaban sama sekali: container mati, sedang restart, atau timeout.
SEBAB_TAK_TERJANGKAU = "tak_terjangkau"
#: Yang menjawab di alamat line itu 404: bukan line AutoGrade, atau line terlalu lama.
SEBAB_BUKAN_LINE = "bukan_line"
#: Line hidup tapi menolak kunci konsol (401/403).
SEBAB_KUNCI_DITOLAK = "kunci_ditolak"
#: Line menjawab dengan galatnya sendiri (5xx).
SEBAB_LINE_GALAT = "line_galat"
#: Selain itu: status yang tidak diharapkan, atau galat tanpa kode operator.
SEBAB_LAIN = "lain"

SEBAB_SEMUA = (
    SEBAB_TAK_TERJANGKAU,
    SEBAB_BUKAN_LINE,
    SEBAB_KUNCI_DITOLAK,
    SEBAB_LINE_GALAT,
    SEBAB_LAIN,
)

_KUNCI = frozenset({401, 403})
_BUKAN_LINE = frozenset({404})


def sebab_tak_terbaca(kode: str | None, status: int | None) -> str:
    """Satu `SEBAB_*` dari kode galat operator (`LineUnavailable.code`) dan status HTTP-nya.

    Status dibaca lebih dulu: `_get_json` mengirim 401/403 sebagai `LINE_MENOLAK` dan
    404/5xx sebagai `LINE_TIDAK_MENJAWAB` yang membawa status, jadi statuslah yang
    membedakan "line mati" dari "line menjawab tapi menolak atau galat". Tanpa status,
    hanya `LINE_TIDAK_MENJAWAB` yang berarti tidak ada jawaban sama sekali.
    """
    if status in _KUNCI:
        return SEBAB_KUNCI_DITOLAK
    if status in _BUKAN_LINE:
        return SEBAB_BUKAN_LINE
    if status is not None and 500 <= status <= 599:
        return SEBAB_LINE_GALAT
    if status is None and kode == LINE_TIDAK_MENJAWAB:
        return SEBAB_TAK_TERJANGKAU
    return SEBAB_LAIN
