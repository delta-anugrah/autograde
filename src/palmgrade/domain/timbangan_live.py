"""Live weighbridge reading from the PLC: the pure rules (no socket, no clock).

The scale indicator feeds the mill's Mitsubishi PLC, and the console reads the weight
from a word register over MC Protocol (direction agreed with Pak Ocit on 2026-10-02).
Which register, 16 or 32 bit, how many decimals and which bits mean "stable" and
"error" are still open questions to him, so every one of them is an `.env` value and
this module only knows how to turn words into kilograms and a reading into a state.

Mitsubishi keeps a 32-bit value (DINT) in two consecutive words, LOW word first:
`D100` holds the low half, `D101` the high half. A 16-bit register tops out at
32,767, which is less than a loaded truck, so the default is two words.

The tile shows this number to the operator only. It never fills a ticket: a weight
that enters the books still goes through `weighings` (rule 15, `net_kg` computed).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The scale is not configured (`SCALE_PLC_REGISTER` empty or invalid).
TIDAK_DIPAKAI = "tidak_dipakai"
#: Configured, nothing answered yet (the first second after boot).
MEMERIKSA = "memeriksa"
#: No answer from the PLC, or the last good reading is too old to show.
PUTUS = "putus"
#: The PLC answers, but its error bit says the indicator itself has a fault.
ERROR = "error"
STABIL = "stabil"
BERGERAK = "bergerak"
#: A reading, with no stable bit configured to say whether it has settled.
TERBACA = "terbaca"

#: A reading older than this is not shown: a frozen number on a live tile is worse
#: than a dash, because the operator would write it down.
BASI_DETIK = 5.0

# Word devices the MC Protocol batch read accepts. W and ZR are hexadecimal on the
# Q series, D and R decimal; the PLC rejects a wrong digit, so accepting hex digits
# here costs nothing.
_POLA_WORD = re.compile(r"^(D|W|R|ZR)[0-9A-F]+$")
# Bit devices. X/Y/B are hexadecimal on the Q series, M/L decimal.
_POLA_BIT = re.compile(r"^(M|L|B|X|Y)[0-9A-F]+$")


def alamat_word(teks: str | None) -> str | None:
    """`" d100 "` -> `"D100"`; empty or not a word device -> None (feature off)."""
    nilai = (teks or "").strip().upper()
    return nilai if _POLA_WORD.match(nilai) else None


def alamat_bit(teks: str | None) -> str | None:
    """`"m2000"` -> `"M2000"`; empty or not a bit device -> None (signal not used)."""
    nilai = (teks or "").strip().upper()
    return nilai if _POLA_BIT.match(nilai) else None


def gabung_kata(kata: list[int]) -> int:
    """One or two words from the PLC -> one signed integer.

    pymcprotocol hands every word back as a signed 16-bit value, so the halves are
    masked before they are joined; the join is then read back as signed 32-bit
    (a scale that drifts just below zero reports -2, not 4,294,967,294).
    """
    if len(kata) == 1:
        return int(kata[0])
    if len(kata) != 2:
        raise ValueError(f"expected 1 or 2 words, got {len(kata)}")
    rendah, tinggi = (int(k) & 0xFFFF for k in kata)
    nilai = (tinggi << 16) | rendah
    return nilai - (1 << 32) if nilai >= (1 << 31) else nilai


def ke_kg(mentah: int, desimal: int) -> int | float:
    """Raw register value -> kilograms, with `desimal` implied decimal places."""
    if desimal <= 0:
        return mentah
    return round(mentah / 10**desimal, desimal)


@dataclass(frozen=True)
class Bacaan:
    """One good read of the PLC. `stabil` is None when no stable bit is configured."""

    kg: int | float
    stabil: bool | None = None
    error: bool = False


def ringkas(
    *,
    dipakai: bool,
    bacaan: Bacaan | None,
    ok_pada: float | None,
    gagal_pada: float | None,
    sekarang: float,
    basi_s: float = BASI_DETIK,
) -> dict:
    """What the tile shows: `{keadaan, kg, umur_detik}`.

    `ok_pada` / `gagal_pada` are monotonic times of the last good and the last failed
    read. `kg` is only given when the number may be shown: never while cut off, never
    while the indicator reports an error, never from a stale reading.
    """
    if not dipakai:
        return {"keadaan": TIDAK_DIPAKAI, "kg": None, "umur_detik": None}
    if bacaan is None or ok_pada is None:
        return {"keadaan": PUTUS if gagal_pada is not None else MEMERIKSA, "kg": None, "umur_detik": None}
    umur = max(0.0, sekarang - ok_pada)
    if (gagal_pada is not None and gagal_pada > ok_pada) or umur > basi_s:
        return {"keadaan": PUTUS, "kg": None, "umur_detik": round(umur, 1)}
    if bacaan.error:
        return {"keadaan": ERROR, "kg": None, "umur_detik": round(umur, 1)}
    if bacaan.stabil is None:
        keadaan = TERBACA
    else:
        keadaan = STABIL if bacaan.stabil else BERGERAK
    return {"keadaan": keadaan, "kg": bacaan.kg, "umur_detik": round(umur, 1)}


#: A reading with no stable bit (`terbaca`) must hold the same kilograms this long before a
#: scan may save it (user 2026-10-06): a truck still rolling onto the bridge changes it.
TAHAN_DETIK = 2.0


def berat_layak(snapshot: dict, tahan_detik: float | None, minimum: float) -> int | float | None:
    """The live kilograms a scan may save as a ticket weight, or None (the operator types it).

    Fit = `stabil`, or `terbaca` held unchanged for `TAHAN_DETIK`; never moving, cut, stale
    or faulted (`ringkas` gives no kg then), and never below `minimum`: an empty bridge reads
    near zero, and a ticket of 40 kg is a mistake, not a weight.
    """
    kg = snapshot.get("kg")
    if kg is None or kg < minimum:
        return None
    if snapshot.get("keadaan") == STABIL:
        return kg
    if snapshot.get("keadaan") == TERBACA and tahan_detik is not None and tahan_detik >= TAHAN_DETIK:
        return kg
    return None
