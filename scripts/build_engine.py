#!/usr/bin/env python
"""Build a TensorRT FP16 engine from the release .pt — once per GPU.

A TensorRT engine is hardware-locked (tied to GPU compute capability + the
TensorRT version it was built with), so it is tagged by compute capability and
cached in ./engines (a writable volume; models/ is read-only). Re-running is a
no-op if the engine for the current GPU already exists.

Run via `make build-engine`, which executes this as a single one-shot container
BEFORE the 3 line containers start — so the 3 lines never race to build the same
engine (which would blow up VRAM and corrupt the .engine file).

Accuracy note: the engine is FP16, matching the runtime which already uses
`.half()`. Detection results are numerically equivalent to the .pt.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Make `src.palmgrade...` importable when run as `python scripts/build_engine.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch  # noqa: E402

from src.palmgrade.core.config import Settings  # noqa: E402

# Must match the imgsz used at inference (ultralytics default for the pipeline).
IMGSZ = 640


def main() -> int:
    if not torch.cuda.is_available():
        print("[build_engine] CUDA tidak tersedia — TensorRT butuh GPU. Lewati.")
        return 0

    settings = Settings()
    cc_major, cc_minor = torch.cuda.get_device_capability(0)
    cc = f"{cc_major}{cc_minor}"
    gpu_name = torch.cuda.get_device_name(0)

    target = settings.engine_path_for_gpu(cc)
    if target.exists():
        print(f"[build_engine] Engine sudah ada untuk {gpu_name} (sm{cc}): {target} — skip.")
        return 0

    pt_path = settings.ripeness_model_path
    if not pt_path.exists():
        print(f"[build_engine] ERROR: model .pt tidak ditemukan: {pt_path}")
        return 1

    settings.engines_dir.mkdir(parents=True, exist_ok=True)

    # Sabuk pengaman: cegah Ultralytics auto-`pip install` saat export. Auto-install
    # itu yang dulu HANG (narik paket dari PyPI publik). tensorrt-cu12 sudah dipasang
    # di Dockerfile, jadi normalnya gak ke-trigger — ini jaring pengaman supaya
    # build_engine GAGAL-CEPAT dengan error jelas, bukan nyangkut diam-diam.
    #
    # NB: nama var-nya `YOLO_AUTOINSTALL`. Sebelumnya di sini tertulis
    # ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS — bukan var yang dikenal Ultralytics,
    # jadi jaringnya bolong dan auto-install tetap jalan (kejadian di PC pabrik
    # 2026-09-09: nyangkut narik onnxruntime-gpu).
    import os
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")

    # models/ di-mount read-only → ultralytics export menulis di sebelah source .pt,
    # jadi copy dulu .pt ke ./engines (writable), export di situ, lalu rename.
    from ultralytics import YOLO  # import telat supaya pesan CUDA di atas tampil duluan

    work_pt = settings.engines_dir / pt_path.name
    shutil.copy2(pt_path, work_pt)

    # FP16 cuma menang di Turing ke atas (sm75+). Di Pascal — Quadro P4000 = sm61 —
    # cuBLAS/TensorRT jatuh ke pseudo-FP16 (hitung tetap FP32), jadi nol speedup.
    # Diukur di PC pabrik 2026-09-09: FP32 0.92 vs FP16 0.96 TFLOPS. Build FP32 saja.
    half = cc_major >= 7
    precision = "FP16" if half else "FP32"

    print(f"[build_engine] Build TensorRT {precision} engine untuk {gpu_name} (sm{cc}) @ imgsz={IMGSZ} ...")
    print("[build_engine] Sekali jalan, bisa 5-15 menit. Tunggu ya.")

    # workspace=2 GiB: batasi memori sementara TensorRT saat build engine supaya
    # AMAN di GPU VRAM kecil (GTX 1650 4GB di PC prod). Default (None=auto) bisa
    # minta workspace sampai batas device → OOM di 4GB. 2 GiB cukup buat optimize
    # YOLOv8 + sisain headroom buat OS/driver. Turunkan ke 1 kalau masih OOM.
    model = YOLO(str(work_pt))
    exported = model.export(
        # simplify=False: ONNX-simplify butuh onnxruntime-gpu yang TIDAK ada di image
        # (dan bikin Ultralytics auto-install → nyangkut). TensorRT punya optimizer
        # graph sendiri, jadi tahap ini memang tidak dibutuhkan.
        format="engine", half=half, simplify=False, imgsz=IMGSZ, device=0, workspace=2
    )

    shutil.move(str(exported), str(target))

    # bersihkan artefak antara (.pt copy + .onnx)
    work_pt.unlink(missing_ok=True)
    work_pt.with_suffix(".onnx").unlink(missing_ok=True)

    print(f"[build_engine] Selesai: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
