"""One frame's detection boxes, read once (batch 6.1).

`results.boxes` lives where the model ran. On the factory PC that is the GPU, and every
`.item()` or `.tolist()` on it waits for the GPU and copies one value across. The detection
loop used to do that per value, per box, in three scans of the same frame. Here the whole
array crosses once and everything after it reads plain Python numbers.

No torch and no cv2 import: `boxes` is only asked for what ultralytics gives it
(`cpu()`, `numpy()`, `xyxy`, `cls`, `conf`, `id`), so the unit suite covers this with a fake.
"""
from __future__ import annotations

from typing import Any, NamedTuple

#: A box the tracker gave no identity to (`boxes.id` is `None` for the whole frame).
TANPA_TRACK = -1


class Kotak(NamedTuple):
    """One detection box. Coordinates are in the frame the model saw, truncated like `int()`."""

    track_id: int
    cls_id: int
    conf: float
    x1: int
    y1: int
    x2: int
    y2: int


def baca_kotak(results: Any) -> list[Kotak]:
    """Every box of `results`, in the order the model listed them."""
    boxes = results.boxes
    if boxes is None or len(boxes) == 0:
        return []
    di_cpu = boxes.cpu().numpy()
    koordinat = di_cpu.xyxy.tolist()
    kelas = di_cpu.cls.tolist()
    keyakinan = di_cpu.conf.tolist()
    track = di_cpu.id.tolist() if di_cpu.id is not None else None
    return [
        Kotak(
            int(track[i]) if track is not None else TANPA_TRACK,
            int(kelas[i]),
            float(keyakinan[i]),
            int(x1), int(y1), int(x2), int(y2),
        )
        for i, (x1, y1, x2, y2) in enumerate(koordinat)
    ]
