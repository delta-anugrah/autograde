"""Berkas mana yang boleh dikirim ke browser lewat `/captures`.

`/captures` menyajikan folder `artifacts/` line apa adanya. Sampai batch 1 folder
itu juga berisi `outbox.db` dan `license.db`, jadi siapa pun di LAN bisa
mengunduh antrean janjang dan penjaga jam lisensi. Aturan ini tetap berlaku
sesudah berkasnya dipindah: berkas lama bisa masih ada (rollback, pemindahan
yang gagal), dan penanda Danger Zone juga tinggal di sana.

Nama dibandingkan sesudah `casefold()`, bukan `lower()`: disk Mac tidak
membedakan besar kecil, jadi `OUTBOX.DB` membuka berkas yang sama, dan lipatan
Unicode-nya lebih luas dari `lower()` (`license.db-\u017fhm` dengan s panjang
membuka `license.db-shm`).
"""
from __future__ import annotations

_AKHIRAN_TERLARANG = (".db", ".sqlite", ".sqlite3", "-wal", "-shm", "-journal")


def boleh_disajikan(path: str) -> bool:
    bagian = [b for b in path.replace("\\", "/").split("/") if b]
    if not bagian or any(b.startswith(".") for b in bagian):
        return False
    return not bagian[-1].casefold().endswith(_AKHIRAN_TERLARANG)
