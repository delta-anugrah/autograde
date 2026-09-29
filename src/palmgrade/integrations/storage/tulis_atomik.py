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

import os
import secrets
from pathlib import Path

from ...domain.berkas_utuh import nama_sementara


def tulis_atomik(jalur: Path, isi: bytes) -> None:
    """Tulis `isi` ke `jalur`. Gagal di tengah = `jalur` tidak berubah, sementara dibuang."""
    folder = jalur.parent
    _pastikan_folder(folder)
    sementara = folder / nama_sementara(jalur.name, secrets.token_hex(4))
    try:
        fd = os.open(sementara, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        with os.fdopen(fd, "wb") as berkas:
            berkas.write(isi)
            berkas.flush()
            os.fsync(berkas.fileno())
        os.replace(sementara, jalur)
    except BaseException:
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
    """Sebagian sistem berkas menolak fsync folder; isinya sendiri sudah aman."""
    try:
        fd = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)
