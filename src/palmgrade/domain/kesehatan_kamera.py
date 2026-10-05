"""Camera health read from what the camera does, not from a sensor it does not have.

The Lampung cameras (MV-CS050-10GC, firmware V4.0.43) do not implement `DeviceTemperature`
(access mode NI, checked on the camera 2026-10-05). An overheating or failing camera shows
first as a frame rate that stays low, frames lost on the wire, and disconnects, so those are
what the Diagnostics card grades.

Pure: the capture worker feeds readings with its clock, `HealthService` reads the result.
Only the capture thread writes; the readers (`ringkas`, `jumlah`) never change anything and
copy the deque in one C call, so a health request racing a write needs no lock.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

AMAN = "aman"
WASPADA = "waspada"
KRITIS = "kritis"
_URUTAN = (AMAN, WASPADA, KRITIS)

#: Below this share of the camera's own target rate the rate counts as low (18 of 20 fps).
LAJU_TURUN_RASIO = 0.9
#: How long the rate must stay low before the card turns yellow: a truck-sized hiccup is not
#: a camera problem.
LAJU_TURUN_TAHAN_DETIK = 120.0
#: How long it must stay normal again before the warning clears, so it does not flicker.
LAJU_PULIH_TAHAN_DETIK = 60.0

#: Frames lost are counted over this window, not since the line started: a total since
#: boot only grows and keeps a camera that recovered an hour ago looking broken.
JENDELA_FRAME_HILANG_DETIK = 600.0
#: Lost share from which the row turns red; any loss at all is yellow.
FRAME_HILANG_KRITIS_PERSEN = 5.0

#: Disconnects are counted over a rolling day, not since midnight, so a bad night does not
#: vanish from the card at 00:00.
JENDELA_PUTUS_DETIK = 86_400.0
PUTUS_KRITIS = 3


@dataclass(frozen=True)
class StatistikAliran:
    """Stream counters from the camera SDK, cumulative since grabbing started."""

    diterima: int
    hilang: int


class PenilaiLaju:
    """Is the measured frame rate held below the target? Changes only after a hold time."""

    def __init__(self) -> None:
        self.turun = False
        self._rendah_sejak: float | None = None
        self._normal_sejak: float | None = None

    def nilai(self, fps: float, target: float, sekarang: float) -> bool | None:
        """Grade one reading. True when the low spell starts, False when it ends, else None."""
        if target <= 0:
            return None
        if fps < target * LAJU_TURUN_RASIO:
            self._normal_sejak = None
            if self._rendah_sejak is None:
                self._rendah_sejak = sekarang
            if not self.turun and sekarang - self._rendah_sejak >= LAJU_TURUN_TAHAN_DETIK:
                self.turun = True
                return True
            return None
        self._rendah_sejak = None
        if self._normal_sejak is None:
            self._normal_sejak = sekarang
        if self.turun and sekarang - self._normal_sejak >= LAJU_PULIH_TAHAN_DETIK:
            self.turun = False
            return False
        return None


class JendelaFrameHilang:
    """Frames received and lost over the last `JENDELA_FRAME_HILANG_DETIK`."""

    def __init__(self) -> None:
        self._terakhir: StatistikAliran | None = None
        self._selisih: deque[tuple[float, int, int]] = deque()

    def tambah(self, stat: StatistikAliran, sekarang: float) -> None:
        lalu = self._terakhir
        self._terakhir = stat
        if lalu is None:
            return  # the first reading is only a baseline
        if stat.diterima < lalu.diterima or stat.hilang < lalu.hilang:
            # A reconnect opened a new handle and the SDK counts from zero again.
            self._selisih.append((sekarang, stat.diterima, stat.hilang))
        else:
            self._selisih.append((sekarang, stat.diterima - lalu.diterima, stat.hilang - lalu.hilang))
        self._buang_lama(sekarang)

    def ringkas(self, sekarang: float) -> tuple[int, int] | None:
        """(lost, received + lost) in the window; None when there is no reading in it."""
        dalam = [s for s in tuple(self._selisih) if s[0] >= sekarang - JENDELA_FRAME_HILANG_DETIK]
        if not dalam:
            return None
        hilang = sum(h for _t, _d, h in dalam)
        diterima = sum(d for _t, d, _h in dalam)
        return hilang, diterima + hilang

    def _buang_lama(self, sekarang: float) -> None:
        while self._selisih and self._selisih[0][0] < sekarang - JENDELA_FRAME_HILANG_DETIK:
            self._selisih.popleft()


class HitungPutus:
    """Camera disconnects (one per incident, as logged) over the last `JENDELA_PUTUS_DETIK`."""

    def __init__(self) -> None:
        self._waktu: deque[float] = deque()

    def catat(self, sekarang: float) -> None:
        while self._waktu and self._waktu[0] < sekarang - JENDELA_PUTUS_DETIK:
            self._waktu.popleft()
        self._waktu.append(sekarang)

    def jumlah(self, sekarang: float) -> int:
        return sum(1 for t in tuple(self._waktu) if t >= sekarang - JENDELA_PUTUS_DETIK)


def tingkat_frame_hilang(hilang: int, total: int) -> str:
    if hilang <= 0 or total <= 0:
        return AMAN
    return KRITIS if hilang * 100.0 / total >= FRAME_HILANG_KRITIS_PERSEN else WASPADA


def tingkat_putus(jumlah: int) -> str:
    if jumlah <= 0:
        return AMAN
    return KRITIS if jumlah >= PUTUS_KRITIS else WASPADA


def tingkat_terburuk(*tingkat: str) -> str:
    return max(tingkat, key=_URUTAN.index, default=AMAN)


def ringkas_kesehatan_kamera(*, laju_turun: bool, frame_hilang: tuple[int, int] | None, putus: int) -> dict:
    """The camera-health fields of `/health/detail`, each with its level, plus the worst one.

    The screen only colours what it gets here (L4): yellow and red are decided on the line.
    """
    baris_hilang = None
    if frame_hilang is not None:
        hilang, total = frame_hilang
        baris_hilang = {
            "hilang": hilang,
            "total": total,
            "persen": round(hilang * 100.0 / total, 1) if total > 0 else 0.0,
            "tingkat": tingkat_frame_hilang(hilang, total),
        }
    baris_putus = {"jumlah": putus, "tingkat": tingkat_putus(putus)}
    return {
        "fps_kamera_turun": laju_turun,
        "frame_hilang": baris_hilang,
        "putus_kamera": baris_putus,
        "kamera_tingkat": tingkat_terburuk(
            WASPADA if laju_turun else AMAN,
            baris_hilang["tingkat"] if baris_hilang else AMAN,
            baris_putus["tingkat"],
        ),
    }
