from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .tulis_atomik import tulis_atomik


class LocalFileStorage:
    """Foto bukti dan sidecar, ditulis utuh-atau-tidak-sama-sekali (batch 2.6).

    Dulu `cv2.imwrite` dan `write_text` menulis langsung ke nama akhirnya: listrik
    padam di tengah tulisan meninggalkan berkas 0 byte bernama sah, yang lalu
    diunggah ke R2 dan dihapus retensi. Sekarang gambar di-encode di memori
    (`cv2.imencode`), dan keduanya lewat `tulis_atomik`.
    """

    def write_json(self, path: Path, payload: dict[str, Any]) -> None:
        tulis_atomik(path, json.dumps(payload, indent=2).encode("utf-8"))

    def read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def list_json_files(self, directory: Path) -> list[Path]:
        if not directory.exists():
            return []
        return sorted(directory.glob("*.json"))

    def write_image(self, path: Path, frame: np.ndarray, quality: int = 80) -> None:
        # Encoder param mengikuti ekstensi: .webp → WEBP_QUALITY, selain itu JPEG_QUALITY.
        # Keduanya skala 0–100, jadi `quality` sama validnya untuk WebP maupun JPEG.
        # cv2.imencode memilih codec dari ekstensi; flag yang salah → berkas korup.
        ekstensi = path.suffix.lower()
        if ekstensi == ".webp":
            params = [int(cv2.IMWRITE_WEBP_QUALITY), quality]
        else:
            params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        try:
            ok, isi = cv2.imencode(ekstensi, frame, params)
        except cv2.error as exc:
            # OSError, bukan cv2.error: pemanggil (Critical Rule #8) membedakan
            # "gambar tidak tertulis" lewat OSError. Salinan clean/thumb menangkap
            # OSError saja, jadi cv2.error yang lolos akan menggagalkan janjang
            # yang foto bbox-nya sudah aman.
            raise OSError(f"encode {ekstensi} gagal: {path}: {exc}") from exc
        if not ok or isi is None or isi.size == 0:
            # O2: jangan diam-diam lanjut. Gambar gagal = JSON/event tidak boleh
            # dibuat (mencegah record yatim yang menunjuk berkas tidak ada).
            raise OSError(f"encode {ekstensi} menghasilkan 0 byte, tidak ditulis: {path}")
        tulis_atomik(path, isi.tobytes())

    def write_thumbnail(self, path: Path, frame: np.ndarray, *, max_width: int, quality: int) -> None:
        h, w = frame.shape[:2]
        if w > max_width:
            frame = cv2.resize(frame, (max_width, round(h * max_width / w)), interpolation=cv2.INTER_AREA)
        self.write_image(path, frame, quality=quality)
