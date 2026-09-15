"""Apa yang boleh sampai ke PLC untuk satu janjang.

Logika murni, nol I/O. Dipisah dari worker supaya aturan bisnisnya bisa dites
tanpa menyeret kamera, dan supaya cuma ada SATU tempat yang memutuskan.

Aturannya: buah REJ milik truk Internal tetap masuk ramp, jadi tidak ada pulse
NG. Yang hilang hanya sinyal ke piston — `ripeness_status` yang ditulis ke disk,
dikirim ke konsol, dan dijumlah AutoERP tetap REJ apa adanya. Menukar verdict
jadi ACC akan memalsukan rekap yang dibayar.

Pulse OK juga TIDAK dikirim sebagai gantinya: penghitung OK di PLC akan ikut
berbohong. Konsekuensinya, aturan ini bergantung pada kesepakatan bahwa buah
tanpa sinyal itu diloloskan (dokumen handoff bab 6).
"""
from __future__ import annotations

from .vision_event import verdict_of

INTERNAL = "Internal"


def plc_status_for(ripeness_status: str, ffb_source: str | None) -> str | None:
    """Status yang dikirim ke PLC, atau None kalau janjang ini tidak disinyalkan.

    `verdict_of` dipakai supaya kosakata ACC/REJ tetap satu dengan jalur ingest:
    status asing melempar ValueError di sini, sama seperti di konsol.
    """
    if verdict_of(ripeness_status) == "REJ" and ffb_source == INTERNAL:
        return None
    return ripeness_status
