"""Satu putaran watchdog worker line: thread yang mati dihidupkan lagi.

Dipanggil `main.py` tiap 10 detik. Bebas torch/cv2, jadi perilakunya teruji di CI
(`tests/unit/test_pengawas_worker.py`), bukan cuma bentuk teksnya.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def awasi_sekali(
    worker_threads: list[tuple[str, Any, Any]],
    *,
    sedang_menutup: Callable[[], bool],
    mulai: Callable[[str, Callable[[], None]], threading.Thread],
) -> bool:
    """Hidupkan lagi thread worker yang mati. False = urutan tutup sudah mulai, berhenti.

    Batch 2.2: saat menutup, penulis dan PLC SENGAJA dihentikan; menghidupkannya
    lagi membuka ulang loop penulis di tengah urutan tutup (`run_loop`
    membersihkan tanda berhentinya sendiri). Tanda tutup dibaca SESUDAH thread
    terlihat mati dan SEBELUM dihidupkan: thread yang sudah mati saat tanda itu
    masih padam memang mati sendiri (crash), dan urutan tutup bisa mulai di
    tengah putaran.
    """
    for i, (nama, thread, worker) in enumerate(worker_threads):
        if thread.is_alive():
            continue
        if sedang_menutup():
            return False
        logger.error("Worker thread '%s' died, restarting", nama)
        worker_threads[i] = (nama, mulai(nama, worker.run_loop), worker)
    return True
