"""Isi folder media — apa yang boleh dipilih di layar.

Daftar, bukan kolom ketik. Path yang salah ketik adalah cara paling mudah
membuat line gagal boot (`OpenCVCamera` dan `PhotoCamera` sengaja `raise` saat
berkasnya tidak terbaca), dan daftar menghapus kemungkinannya.

Folder tidak ada atau tidak terbaca memberi daftar KOSONG, bukan galat: layar
kosong bisa dibaca ("belum ada berkas"), layar yang gagal dimuat tidak.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

EKSTENSI_VIDEO: frozenset[str] = frozenset({".mp4", ".avi", ".mkv"})
EKSTENSI_FOTO: frozenset[str] = frozenset({".jpg", ".jpeg", ".png"})


class MediaLibrary:
    """Berkas video dan foto yang tersedia di folder media."""

    def __init__(self, folder: Path) -> None:
        self._folder = Path(folder)

    def daftar_video(self) -> list[str]:
        return self._daftar(EKSTENSI_VIDEO)

    def daftar_foto(self) -> list[str]:
        return self._daftar(EKSTENSI_FOTO)

    def ada(self, nama: str) -> bool:
        """Berkas itu benar-benar ada di folder ini — bukan di atasnya.

        Lapis kedua setelah `bersihkan_sumber`: nama dibandingkan dengan isi
        daftar, bukan di-stat langsung, jadi `../x` tidak pernah menyentuh disk
        di luar folder.
        """
        return nama in set(self._daftar(EKSTENSI_VIDEO | EKSTENSI_FOTO))

    def _daftar(self, ekstensi: frozenset[str]) -> list[str]:
        try:
            isi = list(self._folder.iterdir())
        except (FileNotFoundError, NotADirectoryError):
            return []
        except OSError as exc:
            logger.warning("Folder media tidak terbaca (%s)", exc)
            return []
        return sorted(
            p.name for p in isi if p.is_file() and p.suffix.lower() in ekstensi
        )
