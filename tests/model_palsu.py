"""Checkpoint YOLO dan engine TensorRT PALSU untuk tes — tanpa torch.

Bentuknya meniru berkas asli sejauh yang dibaca `services/model_library`:
`.pt` = zip `<stem>/data.pkl` berisi pickle objek model dari modul yang TIDAK
ADA saat dibaca (didaftarkan sebentar di `sys.modules` hanya selama `dump`),
tensor lewat `persistent_id` seperti storage torch; `.engine` = 4 byte panjang
little-endian + JSON metadata + badan.

Di sini, bukan di satu berkas tes, karena tes unit dan e2e sama-sama butuh
folder model yang meyakinkan. Terimpor sebagai `model_palsu` karena
`tests/conftest.py` membuat pytest menaruh `tests/` di `sys.path`.
"""
from __future__ import annotations

import io
import json
import pickle
import sys
import types
import zipfile
from collections import OrderedDict
from pathlib import Path

EMPAT = {0: "JK", 1: "Ripe", 2: "TP", 3: "Unripe"}
LAMA = {0: "ACC", 1: "Rej", 2: "TP"}

MODUL_PALSU = "ultralytics_palsu_untuk_tes"


class _Tensor:
    """Penanda tensor: di-pickle sebagai persistent id, seperti storage torch."""


class _PicklerTorch(pickle.Pickler):
    def persistent_id(self, obj):
        if isinstance(obj, _Tensor):
            return ("storage", "HalfStorage", "0", "cuda:0", 4)
        return None


def buat_pt(path: Path, names, *, kunci: str = "model") -> Path:
    """Checkpoint berbentuk Ultralytics: zip `<stem>/data.pkl` + storage."""
    modul = types.ModuleType(MODUL_PALSU)

    class DetectionModel:
        pass

    DetectionModel.__module__ = MODUL_PALSU
    DetectionModel.__qualname__ = "DetectionModel"
    modul.DetectionModel = DetectionModel

    model = DetectionModel()
    model.names = names
    model.yaml = {"nc": len(names)}
    model._modules = OrderedDict(conv=_Tensor())

    sys.modules[MODUL_PALSU] = modul
    try:
        buf = io.BytesIO()
        _PicklerTorch(buf, protocol=2).dump(
            {"epoch": -1, kunci: model, "train_args": {"model": "yolov8m.pt"}}
        )
    finally:
        del sys.modules[MODUL_PALSU]

    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{path.stem}/data.pkl", buf.getvalue())
        z.writestr(f"{path.stem}/data/0", b"\0" * 8)
        z.writestr(f"{path.stem}/version", b"3\n")
    return path


def buat_engine(path: Path, names: dict | None, *, sampah: bool = False) -> Path:
    """Engine seperti hasil ekspor Ultralytics: 4 byte panjang LE + JSON + badan."""
    if sampah:
        path.write_bytes(b"\xff\xff\xff\x7f" + b"\x01" * 64)
        return path
    meta = json.dumps({"names": {str(k): v for k, v in names.items()}, "imgsz": [640, 640]})
    path.write_bytes(len(meta).to_bytes(4, "little", signed=True) + meta.encode() + b"\0" * 32)
    return path
