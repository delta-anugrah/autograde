"""One-off: bundle the demo frames DEMO_MODE shows (boxes drawn by the line's own draw_boxes).

Usage: .venv/bin/python scripts/buat-frame-demo.py <folder holding 02.jpg 03.jpeg 04.jpeg 05.jpeg 06.jpeg>
Writes src/palmgrade/static/demo/frame-1.webp .. frame-5.webp and frames.json. The source
photos stay out of git; 01.jpeg is left out on purpose (a photographer's watermark).
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from palmgrade.core.config import Settings
from palmgrade.pipelines.realtime_inspection_pipeline import RealtimeInspectionPipeline

KELAS = ["Ripe", "Unripe", "JK", "TP"]
TINGGI = 720
# Lampung's .env (BORDER_THICKNESS 8, FONT_SCALE 2.5, FONT_THICKNESS 5) after the line shrinks it
# from the 1224x1024 sensor frame to the 720 px stream (factor 0.70, skala_tampilan.gaya_berskala):
# the demo boxes look like the factory screen, not like the thin code defaults.
GAYA = {"border_thickness": 6, "font_scale": 1.76, "font_thickness": 4}
# (source, crop right px, boxes as (class, x%, y%, w%, h%)). 01.jpeg is left out: watermark.
FOTO = [
    ("02.jpg", 0, [("Ripe", 2, 3, 96, 94)]),
    ("03.jpeg", 0, [("Ripe", 12, 3, 80, 92)]),
    ("04.jpeg", 0, [("Unripe", 5, 14, 90, 68)]),
    ("05.jpeg", 40, [("Unripe", 1, 3, 90, 86)]),  # date stamp in the bottom right corner
    ("06.jpeg", 0, [("Ripe", 1, 3, 96, 93)]),
]
OUT = Path(__file__).resolve().parents[1] / "src/palmgrade/static/demo"


def hasil(boxes, w, h):
    kotak = [SimpleNamespace(
        xyxy=np.array([[x * w / 100, y * h / 100, (x + bw) * w / 100, (y + bh) * h / 100]]),
        cls=np.array([KELAS.index(c)]), conf=np.array([0.9]),
    ) for c, x, y, bw, bh in boxes]
    return SimpleNamespace(boxes=kotak, names=dict(enumerate(KELAS)))


def main(src: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    gambar = SimpleNamespace(settings=Settings(**GAYA))  # draw_boxes only reads self.settings
    daftar = []
    for n, (asal, potong, boxes) in enumerate(FOTO, start=1):
        f = cv2.imread(str(src / asal))
        if potong:
            f = f[:, : f.shape[1] - potong]
        s = TINGGI / f.shape[0]
        f = cv2.resize(f, (round(f.shape[1] * s), TINGGI), interpolation=cv2.INTER_CUBIC)
        f = RealtimeInspectionPipeline.draw_boxes(gambar, f, hasil(boxes, f.shape[1], f.shape[0]))
        cv2.imwrite(str(OUT / f"frame-{n}.webp"), f, [cv2.IMWRITE_WEBP_QUALITY, 60])
        daftar.append({"src": f"/demo/frame-{n}.webp", "kelas": [b[0] for b in boxes]})
    (OUT / "frames.json").write_text(json.dumps({"frames": daftar}, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser())
