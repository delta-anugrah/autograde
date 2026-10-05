"""Camera settings the console shows (spec §3.7, decision D1), as pure data.

The capture thread reads the nodes (`integrations/camera/setelan_hikrobot.py`); this module says which nodes,
in which order, and what the line sends for each. The screen shows the rows as they come (L4).
"""

from __future__ import annotations

from dataclasses import dataclass

from .line_tak_terbaca import sebab_tak_terbaca

FLOAT = "float"
INT = "int"
ENUM = "enum"

#: Floats come from the SDK as float32 (23.981199264526367); three decimals is finer than any camera step.
_DESIMAL = 3


@dataclass(frozen=True)
class NodeSetelan:
    kunci: str          # stable id for the screen and KAMUS
    node: str           # GenICam node name in the camera
    jenis: str          # FLOAT / INT / ENUM
    satuan: str         # shown after the value; "" = none
    bisa_diubah: bool   # phase 2 offers a change only for these


SETELAN_KAMERA: tuple[NodeSetelan, ...] = (
    NodeSetelan("exposure", "ExposureTime", FLOAT, "µs", True),
    NodeSetelan("gain", "Gain", FLOAT, "dB", True),
    # Integer on MV-CS050-10GC (phase 0, Lampung 2026-10-05), not float as the first draft assumed.
    NodeSetelan("black_level", "BlackLevel", INT, "", True),
    NodeSetelan("white_balance", "BalanceWhiteAuto", ENUM, "", True),
    NodeSetelan("frame_rate", "AcquisitionFrameRate", FLOAT, "fps", True),
    # Shown only: turning them on makes the image change bunch by bunch, which shifts grading (spec §3.7).
    NodeSetelan("exposure_auto", "ExposureAuto", ENUM, "", False),
    NodeSetelan("gain_auto", "GainAuto", ENUM, "", False),
)
_PER_KUNCI = {n.kunci: n for n in SETELAN_KAMERA}


@dataclass(frozen=True)
class NilaiSetelan:
    """One node as the camera reports it now. `kode_galat` set = the camera refused it."""

    kunci: str
    nilai: float | int | str | None
    minimum: float | int | None = None
    maksimum: float | int | None = None
    langkah: float | int | None = None
    pilihan: tuple[str, ...] = ()
    kode_galat: str | None = None

    @property
    def didukung(self) -> bool:
        return self.kode_galat is None


def _bulat(v: float | int | str | None) -> float | int | str | None:
    return round(v, _DESIMAL) if isinstance(v, float) else v


def baris_setelan(nilai: list[NilaiSetelan]) -> list[dict]:
    """The rows of `GET /internal/camera/settings`, in catalogue order. Unknown keys are dropped."""
    per_kunci = {n.kunci: n for n in nilai if n.kunci in _PER_KUNCI}
    baris = []
    for node in SETELAN_KAMERA:
        n = per_kunci.get(node.kunci)
        if n is None:
            continue
        baris.append({
            "kunci": node.kunci, "node": node.node, "jenis": node.jenis, "satuan": node.satuan,
            "bisa_diubah": node.bisa_diubah, "didukung": n.didukung,
            "nilai": _bulat(n.nilai), "min": _bulat(n.minimum), "max": _bulat(n.maksimum),
            "langkah": _bulat(n.langkah), "pilihan": list(n.pilihan),
        })
    return baris


SEBAB_BUKAN_KAMERA = "bukan_kamera"
SEBAB_KAMERA_TIDAK_MENJAWAB = "kamera_tidak_menjawab"
#: The line's own answers on this route: 409 = the source is not a Hikrobot camera, 503 = the capture thread did
#: not run the read in time (camera disconnected or reconnecting).
_STATUS_SEBAB = {409: SEBAB_BUKAN_KAMERA, 503: SEBAB_KAMERA_TIDAK_MENJAWAB}


def sebab_setelan_tak_terbaca(kode: str | None, status: int | None) -> str:
    """Why a line's camera settings could not be read, as a code the screen words."""
    return _STATUS_SEBAB.get(status) or sebab_tak_terbaca(kode, status)
