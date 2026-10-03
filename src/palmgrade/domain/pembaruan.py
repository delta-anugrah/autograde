"""Batch 4.6: may the staged version be installed now?

Pure rules (standard L2): no files, no clock, no server. The service reads the three
small files in UPDATE_DIR and hands their text here; the route hands the truck
assignments. File contract, shared with the sawit launcher (change both PRs together):
`status.json` written by the launcher, `request.json` by the console, `result.json` by
the host watcher. The console never touches Docker; this file is why it does not need to.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime

from .operator_error import (
    PEMBARUAN_ADA_TRUK,
    PEMBARUAN_BELUM_TERPASANG,
    PEMBARUAN_BERJALAN,
    PEMBARUAN_TIDAK_ADA,
    OperatorError,
)

SKEMA = 1
#: systemd cuts the host watcher at 15 minutes; the screen gives up at 20, so a watcher
#: that never answers cannot leave "installing" on screen forever (plan risk 3).
BATAS_TUNGGU_S = 1200
#: A result older than a day is history, not news for the operator.
TAMPIL_HASIL_S = 86400
HASIL_FINAL = frozenset({"ok", "rolled_back", "failed", "nothing"})
_HASIL_SAH = HASIL_FINAL | {"running"}
#: Release tags only. A 4.2 temporary tag or `latest` is never a version to offer.
_VERSI = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-(?:cpu|edge))?$")


@dataclass(frozen=True)
class StatusLauncher:
    staged: str | None
    watcher: bool


@dataclass(frozen=True)
class Permintaan:
    id: str
    target: str
    at: datetime


@dataclass(frozen=True)
class Hasil:
    id: str
    state: str
    target: str
    installed: str | None
    at: datetime


@dataclass(frozen=True)
class KeadaanPembaruan:
    terpasang: bool
    versi_jalan: str
    siap: str | None
    berjalan: bool
    hasil: dict | None

    def as_dict(self) -> dict:
        return asdict(self)


class PembaruanAdaTruk(OperatorError):
    """Installing restarts the console and all three lines: a truck mid-unload would
    lose the bunches graded during the restart."""

    def __init__(self, bertruk: list[str]) -> None:
        super().__init__(PEMBARUAN_ADA_TRUK, "Masih ada truk di-assign", line=", ".join(bertruk))


class PembaruanTidakAda(OperatorError):
    def __init__(self) -> None:
        super().__init__(PEMBARUAN_TIDAK_ADA, "Tidak ada versi baru yang siap dipasang")


class PembaruanBerjalan(OperatorError):
    def __init__(self) -> None:
        super().__init__(PEMBARUAN_BERJALAN, "Pembaruan sedang dipasang")


class PembaruanBelumTerpasang(OperatorError):
    def __init__(self) -> None:
        super().__init__(PEMBARUAN_BELUM_TERPASANG, "Penunggu pembaruan belum dipasang di PC ini")


def kunci_versi(teks: str | None) -> tuple[int, int, int] | None:
    m = _VERSI.match(teks or "")
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def lebih_baru(baru: str | None, lama: str | None) -> bool:
    """Numbers, not letters: v1.22.10 is newer than v1.22.9 (same rule as `sort -V`)."""
    kb, kl = kunci_versi(baru), kunci_versi(lama)
    return kb is not None and kl is not None and kb > kl


def _objek(teks: str | None) -> dict | None:
    if not teks:
        return None
    try:
        data = json.loads(teks)
    except ValueError:
        # Half-written or hand-edited: treated as absent, never as a crash on screen.
        return None
    if not isinstance(data, dict) or data.get("schema") != SKEMA:
        return None
    return data


def _waktu(teks: object) -> datetime | None:
    if not isinstance(teks, str):
        return None
    try:
        waktu = datetime.fromisoformat(teks)
    except ValueError:
        return None
    return waktu if waktu.tzinfo else None


def urai_status(teks: str | None) -> StatusLauncher | None:
    data = _objek(teks)
    if data is None:
        return None
    staged = data.get("staged")
    return StatusLauncher(staged=staged if kunci_versi(staged) else None, watcher=data.get("watcher") is True)


def urai_permintaan(teks: str | None) -> Permintaan | None:
    data = _objek(teks)
    if data is None:
        return None
    at, id_ = _waktu(data.get("at")), data.get("id")
    if not isinstance(id_, str) or not id_ or at is None or kunci_versi(data.get("target")) is None:
        return None
    return Permintaan(id=id_, target=data["target"], at=at)


def urai_hasil(teks: str | None) -> Hasil | None:
    data = _objek(teks)
    if data is None:
        return None
    at, id_ = _waktu(data.get("at")), data.get("id")
    if not isinstance(id_, str) or data.get("state") not in _HASIL_SAH or at is None:
        return None
    installed = data.get("installed")
    return Hasil(
        id=id_,
        state=data["state"],
        target=str(data.get("target") or ""),
        installed=installed if isinstance(installed, str) else None,
        at=at,
    )


def _hasil_tampil(permintaan: Permintaan | None, jawaban: Hasil | None, basi: bool, sekarang: datetime) -> dict | None:
    if basi and permintaan is not None:
        if (sekarang - permintaan.at).total_seconds() > TAMPIL_HASIL_S:
            return None
        return {"state": "timeout", "target": permintaan.target, "installed": None, "at": permintaan.at.isoformat()}
    if jawaban is None or jawaban.state not in HASIL_FINAL:
        return None
    if (sekarang - jawaban.at).total_seconds() > TAMPIL_HASIL_S:
        return None
    return {
        "state": jawaban.state,
        "target": jawaban.target,
        "installed": jawaban.installed,
        "at": jawaban.at.isoformat(),
    }


def keadaan_pembaruan(
    status: StatusLauncher | None,
    permintaan: Permintaan | None,
    hasil: Hasil | None,
    versi_jalan: str,
    sekarang: datetime,
) -> KeadaanPembaruan:
    """What the screen shows. "Installed" is the console's own APP_VERSION, never the
    file: a technician's `autograde pull` leaves `status.json` stale until the next stage."""
    terpasang = status is not None and status.watcher
    jawaban = hasil if hasil is not None and permintaan is not None and hasil.id == permintaan.id else None
    selesai = jawaban is not None and jawaban.state in HASIL_FINAL
    menunggu = permintaan is not None and not selesai
    basi = menunggu and (sekarang - permintaan.at).total_seconds() >= BATAS_TUNGGU_S
    berjalan = menunggu and not basi
    # A version that already failed the 4.5 gate is not offered again: pressing it
    # again restarts the factory into the same rollback. A technician clears it.
    gagal = selesai and jawaban.state in ("rolled_back", "failed")
    siap = None
    if terpasang and not berjalan and lebih_baru(status.staged, versi_jalan):
        if not (gagal and jawaban.target == status.staged):
            siap = status.staged
    return KeadaanPembaruan(
        terpasang=terpasang,
        versi_jalan=versi_jalan,
        siap=siap,
        berjalan=berjalan,
        hasil=_hasil_tampil(permintaan, jawaban, basi, sekarang),
    )


def line_bertruk(assignments: dict[str, dict]) -> list[str]:
    """Lines with a truck on them. A released line keeps its row with an empty truck_id."""
    return sorted(kode for kode, baris in assignments.items() if (baris or {}).get("truck_id"))


def boleh_pasang(keadaan: KeadaanPembaruan, target: str, bertruk: list[str]) -> None:
    """Raise the reason the install is refused; return None when it may go ahead."""
    if not keadaan.terpasang:
        raise PembaruanBelumTerpasang()
    if keadaan.berjalan:
        raise PembaruanBerjalan()
    if keadaan.siap is None or target != keadaan.siap:
        raise PembaruanTidakAda()
    if bertruk:
        raise PembaruanAdaTruk(bertruk)


def isi_permintaan(id_: str, target: str, oleh: str, sekarang: datetime) -> dict:
    return {"schema": SKEMA, "id": id_, "target": target, "by": oleh, "at": sekarang.isoformat()}
