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
        cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])

