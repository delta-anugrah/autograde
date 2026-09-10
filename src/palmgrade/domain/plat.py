"""Nomor polisi ternormalisasi — kunci silang antar sistem.

Timbangan, ERP dan operator menulis plat yang sama dengan cara berbeda:
"B 1234 XY", "b1234xy", "B-1234-XY". Yang dibandingkan selalu bentuk
ternormalisasinya, tidak pernah teks mentahnya. Teks mentah tetap disimpan apa
adanya supaya yang muncul di layar sama dengan yang tertulis di surat jalan.

Bebas dependensi — dites tanpa kamera/torch.
"""
from __future__ import annotations

import re
import uuid

_BUKAN_ALNUM = re.compile(r"[^A-Za-z0-9]")


def normalisasi_plat(plat: str) -> str:
    """`B 1234 xy` → `B1234XY`. ValueError kalau tidak menyisakan apa pun."""
    hasil = _BUKAN_ALNUM.sub("", plat or "").upper()
    if not hasil:
        raise ValueError("nomor polisi tidak boleh kosong")
    return hasil


def truck_id_for(plat: str) -> str:
    """Id truk lokal, deterministik dari platnya.

    uuid5, bukan uuid4 — rumus yang sama dipakai `domain/vision_event.py`.
    Operator yang mengetik ulang plat yang sama (shift lain, hari lain) harus
    mendapat truk yang sama, bukan baris kembar yang memecah tonasenya.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"truk:{normalisasi_plat(plat)}"))
