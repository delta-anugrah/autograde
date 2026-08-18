"""Gerbang lisensi untuk thread grading — satu aturan, satu fungsi murni.

Sengaja modul sendiri, bukan method di `FrameProcessingWorker`: worker itu
meng-import torch/ultralytics, jadi test-nya tidak bisa jalan di CI (yang
sengaja tidak memasang GPU stack). Aturan yang bisa menghentikan seluruh
pabrik harus punya test yang benar-benar dijalankan.
"""

from __future__ import annotations

import time


def grading_blocked(
    license_enabled: bool,
    license_exp: int,
    now: float | None = None,
) -> bool:
    """True kalau deteksi harus berhenti.

    `license_exp` = detik Unix akhir masa tenggang; 0 berarti tidak ada lisensi
    yang bisa diverifikasi. Fail CLOSED: kalau fiturnya menyala tapi tokennya
    tidak terbaca, kamera diam. Kebalikannya berarti token rusak = gratis.

    `license_enabled=False` (PC dev, cloud, PC pabrik yang belum dilisensi)
    tidak menyentuh apa pun — perilakunya persis seperti sebelum fitur ini ada.
    """
    if not license_enabled:
        return False
    if license_exp <= 0:
        return True
    return (time.time() if now is None else now) > license_exp
