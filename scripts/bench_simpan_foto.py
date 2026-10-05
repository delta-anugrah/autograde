"""Benchmark for batch 6.2: saving one bunch's photos (bbox + clean + thumbnail).

    .venv/bin/python scripts/bench_simpan_foto.py [--gambar frame.png] [--putaran 7]

Writes real files into a temporary folder through the real `LocalFileStorage` (WebP encode in
cv2, atomic write with fsync) and times, per bunch:

* old: the three writes one after another, as `CaptureWriter.write_pair` did before 6.2;
* new: `CaptureWriter.write_pair` as it is now (clean copy on a helper thread);
* for the record only, not shipped: the clean copy as JPEG, one after another and in parallel.

The frame is `images/sample_sawit.jpg` enlarged to the factory sensor size (2448x2048) with
light sensor noise added, unless `--gambar` names a real full-size frame.

Not a test and never run by CI: it imports cv2. Encode time depends on the CPU and on what
else it is doing. A Mac gives Mac numbers; on the factory PC three lines share the CPU, so
run it there (inside a line container) before quoting a factory number.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

AKAR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AKAR / "src"))

from palmgrade.core.config import Settings  # noqa: E402
from palmgrade.integrations.storage.local_file_storage import LocalFileStorage  # noqa: E402
from palmgrade.services.capture_writer import (  # noqa: E402
    _SAVE_QUALITY,
    _THUMB_QUALITY,
    _THUMB_WIDTH,
    CaptureWriter,
)

UKURAN_SENSOR = (2448, 2048)
MUTU_JPEG_LATIH = 90


def _frame(gambar: Path | None) -> tuple[np.ndarray, np.ndarray]:
    """(clean, annotated) at sensor size."""
    if gambar is not None:
        clean = cv2.imread(str(gambar))
        if clean is None:
            raise SystemExit(f"cannot read {gambar}")
    else:
        kecil = cv2.imread(str(AKAR / "images" / "sample_sawit.jpg"))
        besar = cv2.resize(kecil, UKURAN_SENSOR, interpolation=cv2.INTER_CUBIC)
        derau = np.random.default_rng(1).normal(0, 4, besar.shape)
        clean = np.clip(besar.astype(np.int16) + derau.astype(np.int16), 0, 255).astype(np.uint8)
    annotated = clean.copy()
    t, lebar = clean.shape[:2]
    cv2.rectangle(annotated, (lebar // 4, t // 4), (lebar * 3 // 4, t * 3 // 4), (0, 255, 0), 2)
    cv2.putText(annotated, "Ripe", (lebar // 4, t // 4 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 3)
    return clean, annotated


def _berurutan(storage: LocalFileStorage, folder: Path, clean, annotated, *, clean_ext: str, mutu_clean: int) -> None:
    storage.write_image(folder / "bbox" / "x.webp", annotated, quality=_SAVE_QUALITY)
    storage.write_image(folder / "clean" / f"x{clean_ext}", clean, quality=mutu_clean)
    storage.write_thumbnail(folder / "thumb" / "x.webp", annotated, max_width=_THUMB_WIDTH, quality=_THUMB_QUALITY)


def _paralel(storage: LocalFileStorage, folder: Path, clean, annotated, *, clean_ext: str, mutu_clean: int) -> None:
    di_samping = threading.Thread(
        target=storage.write_image, args=(folder / "clean" / f"x{clean_ext}", clean, mutu_clean)
    )
    di_samping.start()
    storage.write_image(folder / "bbox" / "x.webp", annotated, quality=_SAVE_QUALITY)
    di_samping.join()
    storage.write_thumbnail(folder / "thumb" / "x.webp", annotated, max_width=_THUMB_WIDTH, quality=_THUMB_QUALITY)


def _ukur(fungsi, putaran: int) -> tuple[float, float]:
    """(wall ms, CPU ms of this process) per bunch, median."""
    fungsi()  # warm up: folders exist, codec loaded
    wall, cpu = [], []
    for _ in range(putaran):
        w, c = time.perf_counter(), time.process_time()
        fungsi()
        wall.append(time.perf_counter() - w)
        cpu.append(time.process_time() - c)
    return statistics.median(wall) * 1000, statistics.median(cpu) * 1000


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--gambar", type=Path, default=None, help="a real full-size frame")
    parser.add_argument("--putaran", type=int, default=7)
    argumen = parser.parse_args()

    clean, annotated = _frame(argumen.gambar)
    storage = LocalFileStorage()
    print(f"cv2 {cv2.__version__}, frame {clean.shape[1]}x{clean.shape[0]}, {argumen.putaran} bunches, median\n")

    with tempfile.TemporaryDirectory(prefix="bench-simpan-foto-") as sementara:
        akar = Path(sementara)
        settings = replace(Settings(), repo_root=akar)
        penulis = CaptureWriter(settings, storage)

        def sekarang() -> None:
            penulis.write_pair(
                date_folder="2026-01-01", truck_folder="truk", grade_class="Ripe",
                filename="x.webp", annotated_frame=annotated, clean_frame=clean,
            )

        baris = [
            ("old: bbox, clean, thumb one after another", lambda: _berurutan(
                storage, akar / "lama", clean, annotated, clean_ext=".webp", mutu_clean=_SAVE_QUALITY)),
            ("new: CaptureWriter.write_pair (clean on a helper thread)", sekarang),
            (f"not shipped: clean as JPEG q{_SAVE_QUALITY}, one after another", lambda: _berurutan(
                storage, akar / "jpg", clean, annotated, clean_ext=".jpg", mutu_clean=_SAVE_QUALITY)),
            (f"not shipped: clean as JPEG q{MUTU_JPEG_LATIH}, one after another", lambda: _berurutan(
                storage, akar / "jpg90", clean, annotated, clean_ext=".jpg", mutu_clean=MUTU_JPEG_LATIH)),
            (f"not shipped: clean as JPEG q{_SAVE_QUALITY}, in parallel", lambda: _paralel(
                storage, akar / "jpgp", clean, annotated, clean_ext=".jpg", mutu_clean=_SAVE_QUALITY)),
        ]
        print(f"{'one bunch':<62}{'wall ms':>10}{'CPU ms':>10}")
        for nama, fungsi in baris:
            wall, cpu = _ukur(fungsi, argumen.putaran)
            print(f"{nama:<62}{wall:>10.0f}{cpu:>10.0f}")

        print("\nsize of the clean copy on disk")
        for nama, jalur in (
            (f"WebP q{_SAVE_QUALITY} (today)", akar / "lama" / "clean" / "x.webp"),
            (f"JPEG q{_SAVE_QUALITY}", akar / "jpg" / "clean" / "x.jpg"),
            (f"JPEG q{MUTU_JPEG_LATIH}", akar / "jpg90" / "clean" / "x.jpg"),
        ):
            print(f"  {nama:<20}{jalur.stat().st_size / 1024:>8.0f} KB")


if __name__ == "__main__":
    main()
