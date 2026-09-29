"""Tulis berkas utuh-atau-tidak-sama-sekali, tahan listrik padam (batch 2.6).

Satu tempat untuk pola yang dulu disalin di `media_env_service` dan
`hapus_data_line.tulis_penanda`, dan yang TIDAK dipakai penulis bukti:

1. tulis ke berkas sementara di folder yang sama (`domain/berkas_utuh`);
2. `fsync` isinya;
3. `os.replace` ke nama akhir: atomik di POSIX, pembaca melihat berkas lama
   utuh atau berkas baru utuh, tidak pernah separuh;
4. `fsync` foldernya, supaya entri nama baru ikut selamat dari listrik padam.

Folder yang baru dibuat ikut di-fsync di induknya: folder truk dan folder
kelas lahir bersama janjang pertamanya, dan folder yang hilang saat listrik
padam membawa fotonya ikut hilang.

Izin berkas mengikuti umask proses (seperti `open(..., "w")`), BUKAN 0600
milik `tempfile.mkstemp`: foto di `artifacts/` dibaca juga oleh konsol (mount
read-only) dan oleh teknisi yang menyalinnya untuk latih ulang model.
"""
from __future__ import annotations

import contextlib
import errno
import logging
import os
import secrets
from pathlib import Path

from ...domain.berkas_utuh import nama_sementara

logger = logging.getLogger(__name__)

# Errno yang berarti "sistem berkas ini menolak fsync folder sama sekali", bukan
# masalah dengan berkas atau disk kita: aman diabaikan, itu perilaku normal
# filesystem tertentu (lihat `_fsync_folder`).
_FSYNC_FOLDER_DITOLAK = (errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EBADF, errno.EACCES)


def tulis_atomik(jalur: Path, isi: bytes) -> None:
    """Tulis `isi` ke `jalur`. Gagal di tengah = `jalur` tidak berubah, sementara dibuang."""
    folder = jalur.parent
    _pastikan_folder(folder)
    sementara = folder / nama_sementara(jalur.name, secrets.token_hex(4))
    dibuat = False
    try:
        fd = os.open(sementara, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        dibuat = True
        with os.fdopen(fd, "wb") as berkas:
            berkas.write(isi)
            berkas.flush()
            os.fsync(berkas.fileno())
        os.replace(sementara, jalur)
    except BaseException:
        # `dibuat` hanya true kalau `os.open` di atas benar-benar berhasil: kalau
        # gagal karena EEXIST (nama sementara kita kebetulan tabrakan dengan
        # penulis lain), berkas itu bukan milik kita, jangan dihapus.
        #
        # Kegagalan pembersihan sendiri TIDAK BOLEH menggantikan galat asli
        # (`raise` di bawah tanpa argumen melempar ulang galat yang sedang
        # ditangani, bukan galat dari `unlink`): disk yang remount read-only di
        # tengah fsync harus tercatat sebagai itu, bukan sebagai galat unlink;
        # dan KeyboardInterrupt/SystemExit tidak boleh berubah jadi OSError,
        # yang bisa tertelan pemanggil yang cuma menangkap OSError. Task 8
        # (media_env fallback) membaca errno EBUSY/EXDEV/EINVAL dari galat asli
        # ini, jadi errno yang tertukar membuatnya salah baca.
        if dibuat:
            with contextlib.suppress(OSError):
                sementara.unlink(missing_ok=True)
        raise
    _fsync_folder(folder)


def _pastikan_folder(folder: Path) -> None:
    baru: list[Path] = []
    cek = folder
    while not cek.exists():
        baru.append(cek)
        cek = cek.parent
    for anak in reversed(baru):
        try:
            anak.mkdir()
        except FileExistsError:
            pass  # penulis lain (capture manual) membuatnya lebih dulu
        _fsync_folder(anak.parent)


def _fsync_folder(folder: Path) -> None:
    """Sebagian sistem berkas menolak fsync folder; isinya sendiri sudah aman.

    Errno di `_FSYNC_FOLDER_DITOLAK` diabaikan diam-diam, itu cara filesystem
    tertentu menolak fsync folder, bukan tanda ada yang salah. Errno LAIN
    (mis. EIO, disk bermasalah) dicatat WARNING menyebut folder dan errno-nya,
    tapi tetap tidak melempar: berkasnya sudah dapat nama akhirnya lewat
    `os.replace`, jadi menggagalkan seluruh `tulis_atomik` di titik ini cuma
    menyembunyikan fakta bahwa isinya sudah aman.
    """
    try:
        fd = os.open(folder, os.O_RDONLY)
    except OSError as e:
        if e.errno not in _FSYNC_FOLDER_DITOLAK:
            logger.warning("buka folder %s untuk fsync gagal (errno %s): %s", folder, e.errno, e)
        return
    try:
        os.fsync(fd)
    except OSError as e:
        if e.errno not in _FSYNC_FOLDER_DITOLAK:
            logger.warning("fsync folder %s gagal (errno %s): %s", folder, e.errno, e)
    finally:
        os.close(fd)
