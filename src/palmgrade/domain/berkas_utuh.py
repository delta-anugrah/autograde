"""Kapan sebuah berkas bukti di disk boleh dianggap UTUH (batch 2.6). Murni, tanpa I/O.

Foto dan sidecar dulu ditulis langsung ke nama akhirnya. Listrik padam di tengah
tulisan meninggalkan berkas 0 byte dengan nama yang sah: `BatchUploadWorker`
mengunggahnya ke R2, menandainya `done`, dan retensi menghapus aslinya.

Sekarang penulis menulis ke nama SEMENTARA dulu (`nama_sementara`), lalu
menggantinya ke nama akhir dengan `os.replace` sesudah isinya di-fsync. Nama
sementara diawali titik supaya tetap tidak terlihat oleh pembaca yang sudah ada:
`/captures` menolak berkas tersembunyi (`berkas_captures.boleh_disajikan`), dan
pola `_scan()` (`*/*_ripeness.json`) maupun `list_json_files` (`*.json`) tidak
pernah cocok dengan akhiran `.tmp`.
"""
from __future__ import annotations

AWALAN_SEMENTARA = "."
AKHIRAN_SEMENTARA = ".tmp"


def nama_sementara(nama_akhir: str, acak: str) -> str:
    """Nama berkas sementara untuk `nama_akhir`, di folder yang sama."""
    return f"{AWALAN_SEMENTARA}{nama_akhir}.{acak}{AKHIRAN_SEMENTARA}"


def berkas_sementara(nama: str) -> bool:
    """Sisa tulisan yang belum pernah di-`os.replace` (mis. listrik padam)."""
    return nama.startswith(AWALAN_SEMENTARA) and nama.endswith(AKHIRAN_SEMENTARA)


def alasan_tidak_utuh(nama: str, ukuran: int) -> str | None:
    """Kenapa berkas ini tidak boleh diunggah sebagai bukti. None = utuh."""
    if berkas_sementara(nama):
        return "berkas sementara sisa tulisan yang terputus"
    if ukuran <= 0:
        return "kosong (0 byte), sisa tulisan yang terputus"
    return None
