"""Folder basis data line, dan pemindahan sekali jalan dari lokasi lama.

Sampai batch 1 (2026-09-28) `outbox.db` dan `license.db` tinggal di
`artifacts/`, folder yang juga disajikan statis di `/captures` tanpa login.
Sekarang tempatnya `state/`, di luar mount itu.

- Isi DISERAP, bukan berkasnya dipindah: `artifacts/` dan `state/` dua bind mount
  berbeda di Docker (`os.replace` gagal dengan EXDEV), dan PC yang sempat
  rollback bisa punya dua berkas yang sama-sama berisi. Serap memakai kunci
  alami (`event_id`, penanda jam tertinggi), jadi mengulang aman: boot yang
  terputus di tengah menyerap lagi tanpa baris ganda.
- `state/` harus benar-benar tersimpan di host. Compose host PC pabrik tidak ikut
  rilis; kalau `/app/state` tidak berada di mount dari host, isinya hilang tiap
  container dibuat ulang. Dalam keadaan itu DB tetap di `artifacts/` (tetap
  tidak tersaji, lihat routes/captures.py) dan alasannya dicatat ERROR.
- Serapan yang GAGAL meninggalkan `artifacts/outbox.db` yang tidak dihitung
  `pending_count()`. Sisa itu harus tetap terlihat (`outbox_lama_tertinggal`:
  `/health/detail`, lalu hambatan Danger Zone) dan tidak boleh ikut terhapus
  hapus-data (`services/hapus_data_line.py`): isinya janjang yang belum pernah
  sampai ke konsol.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Awaitable, Callable
from pathlib import Path, PurePosixPath
from typing import Protocol

logger = logging.getLogger(__name__)

#: Antrean janjang ke konsol, satu-satunya DB line yang isinya belum ada di tempat lain.
OUTBOX_DB = "outbox.db"
#: Berkas DB milik satu proses line.
BERKAS_DB_LINE = (OUTBOX_DB, "license.db")
_PENDAMPING = ("-wal", "-shm", "-journal")
_MOUNTINFO = Path("/proc/self/mountinfo")
_PENANDA_DOCKER = Path("/.dockerenv")
_ESCAPE_OKTAL = re.compile(r"\\([0-7]{3})")


class _SerapOutbox(Protocol):
    def serap(self, lama: Path) -> int: ...


class _SerapLisensi(Protocol):
    async def serap(self, lama: Path) -> int: ...


def ada_mount(mountinfo: str, folder: Path) -> bool:
    """Apakah `folder` tersimpan di mount dari host menurut `/proc/self/mountinfo`.

    Yang menentukan adalah mount TERDALAM yang memuat `folder` (kolom ke-5,
    titik mount). Akar `/` tidak dihitung: di container itu lapisan overlay
    yang dibuang saat container dibuat ulang. Jadi `./state/line-N:/app/state`
    dan `.:/app` (compose dev) sama-sama tersimpan, sedangkan `/app/state` yang
    cuma folder di image tidak.
    """
    target = PurePosixPath(os.path.abspath(folder))
    terdalam: PurePosixPath | None = None
    for baris in mountinfo.splitlines():
        kolom = baris.split()
        if len(kolom) <= 4:
            continue
        titik = PurePosixPath(_ESCAPE_OKTAL.sub(lambda m: chr(int(m.group(1), 8)), kolom[4]))
        if (titik == target or titik in target.parents) and (
            terdalam is None or len(titik.parts) > len(terdalam.parts)
        ):
            terdalam = titik
    return terdalam is not None and terdalam != PurePosixPath("/")


def folder_db_line(
    artifacts_dir: Path,
    state_dir: Path,
    *,
    di_container: bool | None = None,
    mountinfo: str | None = None,
) -> Path:
    """`state_dir`, kecuali di container yang tidak me-mount `state_dir` dari host."""
    if di_container is None:
        di_container = _PENANDA_DOCKER.exists()
    if not di_container:
        return state_dir
    if ada_mount(_baca_mountinfo() if mountinfo is None else mountinfo, state_dir):
        return state_dir
    logger.error(
        "%s tidak di-mount dari host: outbox.db dan license.db tetap di %s supaya tidak "
        "hilang saat container dibuat ulang. Tambahkan ./state/line-N:/app/state di compose "
        "host lalu autograde restart.",
        state_dir, artifacts_dir,
    )
    return artifacts_dir


def db_sudah_pindah(artifacts_dir: Path, folder_db: Path) -> bool:
    """Folder DB line bukan `artifacts/`: berkas DB line di `artifacts/` itu sisa lama."""
    return folder_db.resolve() != artifacts_dir.resolve()


def outbox_lama_tertinggal(artifacts_dir: Path, folder_db: Path) -> bool:
    """`artifacts/outbox.db` masih ada padahal antrean sudah di `folder_db`.

    Artinya penyerapannya gagal: barisnya belum terkirim dan tidak terhitung di
    `outbox_pending`. Boot berikutnya mencoba lagi.
    """
    return db_sudah_pindah(artifacts_dir, folder_db) and (artifacts_dir / OUTBOX_DB).is_file()


async def pindahkan_db_lama(
    artifacts_dir: Path, folder_db: Path, *, outbox: _SerapOutbox, lisensi: _SerapLisensi
) -> dict[str, str]:
    """Serap DB line lama di `artifacts_dir` ke store yang sudah dibuka di `folder_db`.

    Tidak pernah melempar: pemindahan yang gagal meninggalkan berkas lama (tidak
    tersaji, boot berikutnya mencoba lagi); line yang menolak start karenanya
    menghentikan grading.
    """
    if not db_sudah_pindah(artifacts_dir, folder_db):
        return {nama: "tetap" for nama in BERKAS_DB_LINE}
    penyerap: dict[str, Callable[[Path], Awaitable[int]]] = {
        OUTBOX_DB: lambda p: asyncio.to_thread(outbox.serap, p),
        "license.db": lisensi.serap,
    }
    hasil: dict[str, str] = {}
    for nama in BERKAS_DB_LINE:
        lama = artifacts_dir / nama
        if not lama.is_file():
            hasil[nama] = "tidak_ada"
            continue
        try:
            jumlah = await penyerap[nama](lama)
        except Exception:
            logger.exception("%s lama di %s gagal diserap; berkasnya dibiarkan", nama, artifacts_dir)
            hasil[nama] = "gagal"
            continue
        _hapus_bersama_pendamping(lama)
        logger.warning("%s dipindah dari %s ke %s (%d)", nama, artifacts_dir, folder_db, jumlah)
        hasil[nama] = "dipindah"
    return hasil


def _hapus_bersama_pendamping(lama: Path) -> None:
    """Pendamping DULU, berkas utama terakhir.

    `-wal` yang tertinggal sendirian bisa diputar ulang SQLite ke `outbox.db`
    baru yang dibuat versi lama sesudah rollback, dan merusaknya. Berkas utama
    yang tertinggal sendirian (listrik mati di sini) tidak berbahaya: isinya
    sudah terserap, dan boot berikutnya menyerapnya lagi tanpa ganda.
    """
    for jalur in (*(lama.with_name(lama.name + a) for a in _PENDAMPING), lama):
        try:
            jalur.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("%s tidak bisa dihapus: %s", jalur, exc)


def _baca_mountinfo() -> str:
    try:
        return _MOUNTINFO.read_text()
    except OSError:
        return ""
