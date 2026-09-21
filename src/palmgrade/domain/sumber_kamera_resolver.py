"""Pilihan layar -> kamera mana yang dibangun, dan path apa yang diberikan.

Pemetaan ini sebelumnya berupa if-else di `main.py`, terjalin dengan
`connect()`, penanganan galat, dan `set_camera()`. Dipisahkan supaya bisa diuji
tanpa menyalakan aplikasi — dan supaya satu-satunya tempat yang tahu "webcam
berarti OpenCVCamera tanpa path" adalah berkas ini.

Nama berkas di-join ke `MEDIA_DIR` DI SINI, satu tempat. Nama itu datang dari
layar; menyerahkannya mentah ke pemanggil berarti tiap pemanggil harus ingat
menggabungkannya, dan yang lupa akan membuka berkas relatif terhadap direktori
kerja container.

Bebas cv2/torch (lihat `sumber_kamera`).
"""
from __future__ import annotations

from dataclasses import dataclass

from .sumber_kamera import CAMERA_TYPE_UNTUK

#: Folder media di dalam container, di-mount read-only dari host.
MEDIA_DIR = "/media"


@dataclass(frozen=True)
class RencanaKamera:
    """Apa yang `main.py` butuhkan untuk membangun kamera, tanpa membangunnya.

    Beku supaya tidak ada yang menambal satu field di tengah jalur boot dan
    membuat dua bagian `main.py` melihat rencana yang berbeda.
    """

    camera_type: str
    video_path: str
    photo_path: str
    loop: bool


def rencana_kamera(
    sumber: str, berkas: str, ulang: bool, media_dir: str = MEDIA_DIR
) -> RencanaKamera:
    """Satu line: pilihan layar -> rencana kamera.

    `ulang` sengaja diabaikan selain untuk `video`: mengulang hanya berarti
    sesuatu bagi `OpenCVCamera` yang membaca berkas. Membiarkannya `True` untuk
    foto akan menyimpan nilai yang tidak pernah dibaca — keadaan yang terlihat
    aktif di layar dan tidak melakukan apa-apa.
    """
    camera_type = CAMERA_TYPE_UNTUK.get(sumber)
    if camera_type is None:
        raise ValueError(f"sumber tidak dikenal: {sumber!r}")

    path = f"{media_dir}/{berkas}" if berkas else ""
    return RencanaKamera(
        camera_type=camera_type,
        video_path=path if sumber == "video" else "",
        photo_path=path if sumber == "foto" else "",
        loop=ulang if sumber == "video" else False,
    )
