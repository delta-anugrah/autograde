from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np


class LocalFileStorage:
    def ensure_dir(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)

    def write_json(self, path: Path, payload: dict[str, Any]) -> None:
        self.ensure_dir(path.parent)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def list_json_files(self, directory: Path) -> list[Path]:
        if not directory.exists():
            return []
        return sorted(directory.glob("*.json"))

    def write_image(self, path: Path, frame: np.ndarray, quality: int = 80) -> None:
        self.ensure_dir(path.parent)
        # Encoder param mengikuti ekstensi: .webp → WEBP_QUALITY, selain itu JPEG_QUALITY.
        # Keduanya skala 0–100, jadi `quality` sama validnya untuk WebP maupun JPEG.
        # cv2.imwrite memilih codec dari ekstensi file; flag yang salah → file korup.
        if path.suffix.lower() == ".webp":
            params = [int(cv2.IMWRITE_WEBP_QUALITY), quality]
        else:
            params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        ok = cv2.imwrite(str(path), frame, params)
        if not ok:
            # O2: jangan diam-diam lanjut — gambar gagal ditulis berarti JSON/event tidak boleh
            # dibuat (mencegah record yatim yang menunjuk file tidak ada). run_loop di
            # FrameProcessingWorker menangkap exception (skip 1 frame + log); manual reject → 500.
            raise OSError(f"cv2.imwrite gagal (disk penuh / permission?): {path}")

    def write_thumbnail(self, path: Path, frame: np.ndarray, *, max_width: int, quality: int) -> None:
        h, w = frame.shape[:2]
        if w > max_width:
            frame = cv2.resize(frame, (max_width, round(h * max_width / w)), interpolation=cv2.INTER_AREA)
        self.write_image(path, frame, quality=quality)

