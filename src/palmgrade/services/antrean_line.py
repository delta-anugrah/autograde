"""Antrean janjang line ke konsol, dilihat dan didorong dari layar support (batch 2.4).

Sisi LINE dari tab Status → Antrean line di konsol: berapa yang menunggu, sejak
kapan, kenapa, dan tombol Kirim Ulang. Tidak mengirim apa pun sendiri; yang
mengirim tetap `OutboxRetryWorker`, yang dicari di `RuntimeState.worker_threads`
seperti `HealthService` mencari penulis bukti.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..core.config import Settings
from ..integrations.outbox.outbox_store import OutboxStore
from ..workers.outbox_retry_worker import NAMA_WORKER, STATUS_TIDAK_DIKETAHUI
from ..workers.runtime_state import RuntimeState
from .pindah_db_line import outbox_lama_tertinggal

logger = logging.getLogger(__name__)


class _WorkerAntrean(Protocol):
    def status(self) -> dict[str, Any]: ...

    def bangunkan(self) -> None: ...


@dataclass
class AntreanLine:
    outbox: OutboxStore
    settings: Settings
    state: RuntimeState
    #: Folder DB line (`get_folder_db_line()`): sisa `artifacts/outbox.db` dicari terhadapnya.
    folder_db: Path

    def ringkasan(self) -> dict[str, Any]:
        """Untuk `GET /internal/outbox`: isi antrean + keadaan sambungan menurut worker.

        `aktif` False = `ENABLE_WEBHOOK=false`: janjang disimpan tapi tidak pernah
        dikirim, dan layar harus bilang begitu, bukan "sedang mengirim".
        """
        worker = self._worker()
        return {
            "line_code": self.settings.line_code,
            "aktif": self.settings.enable_webhook,
            **self.outbox.ringkasan(),
            "lama_tertinggal": outbox_lama_tertinggal(self.settings.artifacts_dir, self.folder_db),
            **(worker.status() if worker is not None else dict(STATUS_TIDAK_DIKETAHUI)),
        }

    def kirim_ulang(self) -> int:
        """Tombol Kirim Ulang: semua baris jatuh tempo sekarang, jeda sambungan dibatalkan."""
        dijadwalkan = self.outbox.kirim_ulang_sekarang()
        worker = self._worker()
        if worker is not None:
            worker.bangunkan()
        # Antrean kosong tidak menjadwalkan apa pun: INFO, bukan peringatan.
        logger.log(
            logging.WARNING if dijadwalkan else logging.INFO,
            "Kirim Ulang dari konsol: %d janjang dijadwalkan kirim sekarang", dijadwalkan,
        )
        return dijadwalkan

    def _worker(self) -> _WorkerAntrean | None:
        return next((w for nama, _t, w in self.state.worker_threads if nama == NAMA_WORKER), None)
