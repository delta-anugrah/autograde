"""Benchmark for batch 6.1: reading one frame's boxes, three scans against one transfer.

    .venv/bin/python scripts/bench_baca_kotak.py

Builds real `ultralytics` `Boxes` (tracked, 7 columns) on every device this machine has and
times two ways of reading them:

* old: the reads `FrameProcessingWorker` made before 6.1, `.item()` / `.tolist()` per value in
  three scans of the same frame;
* new: `baca_kotak` (one `boxes.cpu().numpy()`), then the same three scans over plain numbers.

Not a test and never run by CI: it imports torch. The numbers depend on the device. A Mac
gives CPU and MPS (Apple GPU) numbers; the factory PC runs CUDA on an RTX 3060, where each
`.item()` is a wait on the GPU, so run it there before quoting a factory number.
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

import torch
from ultralytics.engine.results import Boxes

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palmgrade.pipelines.kotak_deteksi import baca_kotak  # noqa: E402

NAMA = {0: "JK", 1: "Ripe", 2: "TP", 3: "Unripe"}
BUAH = {"JK", "Ripe", "Unripe"}
UKURAN_FRAME = (2048, 2448)
PUTARAN = 2000
ULANGAN = 5


class _Hasil:
    def __init__(self, boxes: Boxes) -> None:
        self.boxes = boxes
        self.names = NAMA


def _frame(jumlah: int, device: str) -> _Hasil:
    """`jumlah` tracked boxes: mostly bunches, every third one a stalk."""
    baris = []
    for i in range(jumlah):
        x1, y1 = 100.5 + 180 * i, 200.25 + 40 * i
        kelas = 2 if i % 3 == 2 else (1 if i % 2 == 0 else 3)
        baris.append([x1, y1, x1 + 700.75, y1 + 800.5, float(i + 1), 0.8 + 0.01 * i, float(kelas)])
    return _Hasil(Boxes(torch.tensor(baris, dtype=torch.float32, device=device), UKURAN_FRAME))


def tiga_pindai_lama(results: _Hasil) -> int:
    """The reads of the three scans before 6.1, in the same order and number."""
    terbaca = 0
    for box in results.boxes:  # scan 1: bunches in the ROI
        _tid = int(box.id[0].item()) if box.id is not None else -1
        if NAMA[int(box.cls[0].item())] not in BUAH:
            continue
        _kotak = tuple(map(int, box.xyxy[0].tolist()))
        terbaca += 1
    for box in results.boxes:  # scan 2: stalks
        if NAMA[int(box.cls[0].item())] != "TP":
            continue
        _tid = int(box.id[0].item()) if box.id is not None else -1
        _kotak = tuple(map(int, box.xyxy[0].tolist()))
        _conf = float(box.conf[0].item())
        terbaca += 1
    for box in results.boxes:  # scan 3: grading
        _cls = int(box.cls[0].item())
        _tid = int(box.id[0].item()) if box.id is not None else -1
        _conf = float(box.conf[0].item())
        _kotak = tuple(map(int, box.xyxy[0].tolist()))
        terbaca += 1
    return terbaca


def tiga_pindai_baru(results: _Hasil) -> int:
    """One transfer, then the same three scans over plain numbers."""
    kotak_frame = baca_kotak(results)
    terbaca = 0
    for k in kotak_frame:
        if NAMA[k.cls_id] in BUAH:
            terbaca += 1
    for k in kotak_frame:
        if NAMA[k.cls_id] == "TP":
            terbaca += 1
    for _k in kotak_frame:
        terbaca += 1
    return terbaca


def _mikrodetik_per_frame(fungsi, results: _Hasil) -> float:
    """Median of `ULANGAN` runs, each the mean of `PUTARAN` frames."""
    hasil = []
    for _ in range(ULANGAN):
        mulai = time.perf_counter()
        for _ in range(PUTARAN):
            fungsi(results)
        hasil.append((time.perf_counter() - mulai) / PUTARAN * 1e6)
    return statistics.median(hasil)


def _devices() -> list[str]:
    devices = ["cpu"]
    if torch.backends.mps.is_available():
        devices.append("mps")
    if torch.cuda.is_available():
        devices.append("cuda")
    return devices


def main() -> None:
    print(f"torch {torch.__version__}, {PUTARAN} frames x {ULANGAN} runs, median, microseconds per frame")
    print(f"{'device':<7}{'boxes':>6}{'old':>12}{'new':>12}{'saved':>12}{'ratio':>8}")
    for device in _devices():
        for jumlah in (1, 3, 6, 12):
            results = _frame(jumlah, device)
            assert tiga_pindai_lama(results) == tiga_pindai_baru(results)
            lama = _mikrodetik_per_frame(tiga_pindai_lama, results)
            baru = _mikrodetik_per_frame(tiga_pindai_baru, results)
            print(f"{device:<7}{jumlah:>6}{lama:>12.1f}{baru:>12.1f}{lama - baru:>12.1f}{lama / baru:>7.1f}x")


if __name__ == "__main__":
    main()
