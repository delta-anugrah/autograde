from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.config import Settings
from ..domain.kesehatan_ai import JEDA_ALIRAN_DETIK
from ..integrations.camera.base import CameraSource
from ..integrations.outbox.outbox_store import OutboxStore
from ..license.gate import grading_blocked
from ..plc import diagnostics as plc_diagnostics
from ..schemas.common_schema import HealthDetailSchema, WorkerStatus
from ..workers.runtime_state import RuntimeState
from .pemantau_disk import ringkas_disk_dari_state
from .penjaga_ai import ringkas_ai_dari_state
from .pindah_db_line import outbox_lama_tertinggal


@dataclass
class HealthService:
    settings: Settings
    state: RuntimeState
    camera: CameraSource
    outbox: OutboxStore
    # `ModelRegistry`, atau None kalau belum dimuat. Diketik `Any` supaya modul
    # ini tidak menarik torch lewat `model_registry`.
    model: Any = None
    # Folder DB line (`get_folder_db_line()`); None = tidak diperiksa.
    folder_db: Path | None = None

    def ringkasan_outbox(self) -> dict[str, Any]:
        """Antrean ke konsol, termasuk sisa `artifacts/outbox.db` yang gagal diserap.

        Sisa itu tidak terhitung `pending_count()`, jadi `outbox_pending` dilapor
        `None` (tidak diketahui), bukan angka yang terbaca "kosong": Danger Zone
        dan `autograde reset-data` di host sama-sama mempercayai angka ini
        sebelum menghapus.
        """
        tertinggal = self.folder_db is not None and outbox_lama_tertinggal(
            self.settings.artifacts_dir, self.folder_db
        )
        return {
            "outbox_pending": None if tertinggal else self.outbox.pending_count(),
            "outbox_failed": self.outbox.failed_count(),
            "outbox_lama_tertinggal": tertinggal,
        }

    def ringkasan_model(self) -> dict[str, Any]:
        if self.model is None:
            return {
                "model_file": None,
                "model_backend": None,
                "model_kelas": [],
                "model_kelas_cocok": None,
                "gpu_sm": None,
            }
        return self.model.ringkasan()

    def ringkasan_kamera(self) -> dict[str, Any]:
        """Laju terukur dan umur gambar terakhir (batch 3.6).

        Kedua angka fps membeku di nilai terakhirnya saat gambar (atau grading)
        berhenti, jadi di sini dilaporkan 0 begitu yang terakhir lebih tua dari
        satu jeda aliran: "14,9 fps" dari lima menit lalu adalah kebohongan
        yang paling mudah dipercaya di kartu Diagnostik.
        """
        s = self.state
        sekarang = s.jam()
        umur_frame = sekarang - s.frame_terakhir_at if s.frame_terakhir_at > 0 else None
        umur_deteksi = sekarang - s.inferensi_selesai_at if s.inferensi_selesai_at > 0 else None

        def segar(umur: float | None) -> bool:
            return umur is not None and umur <= JEDA_ALIRAN_DETIK

        return {
            "fps_kamera": round(s.fps_kamera, 1) if segar(umur_frame) else 0.0,
            "fps_deteksi": round(s.inference_fps, 1) if segar(umur_deteksi) else 0.0,
            "frame_umur_detik": None if umur_frame is None else round(umur_frame, 1),
        }

    def ringkasan_lisensi(self) -> dict[str, Any]:
        """Lisensi LINE ini, dari gerbang yang sama dengan thread grading."""
        return {
            "aktif": bool(self.settings.lic_enabled),
            "grading_diblokir": grading_blocked(self.settings.lic_enabled, self.state.license_exp),
            "berlaku_sampai": self.state.license_exp or None,
        }

    def get_health(self) -> dict[str, Any]:
        return {
            "message": "Ripe Recognition API is ready.",
            "detail": f"Environment: {self.settings.environment}",
            "version": self.settings.app_version,
            # Batch 2.1: `/health` menjawab 503 kalau `ai.mati` (routes/health_ringan.py).
            "ai": ringkas_ai_dari_state(self.state),
        }

    def get_health_detail(self) -> HealthDetailSchema:
        # torch di-import di sini, bukan di level modul: CI unit test sengaja
        # tidak memasang torch/opencv (lihat .github/workflows/ci.yml), dan
        # get_health() harus tetap bisa diuji tanpa itu.
        import torch

        gpu_available = torch.cuda.is_available()
        gpu_device = torch.cuda.get_device_name(0) if gpu_available else None

        workers = [
            WorkerStatus(name=name, alive=thread.is_alive())
            for name, thread, _ in self.state.worker_threads
        ]

        # Penulis bukti dicari lewat daftar worker, bukan disuntik sendiri:
        # `HealthService` dirakit `get_health_service()` yang tidak tahu apa-apa
        # soal worker, dan menambah satu dependensi lagi ke situ cuma untuk dua
        # angka tidak sepadan. Line konsol (`APP_MODE=console`) tidak punya
        # penulis sama sekali, jadi ketiadaannya normal, bukan kesalahan.
        saver = next(
            (w for name, _t, w in self.state.worker_threads if name == "capture_save"), None
        )

        return HealthDetailSchema(
            status="ok",
            environment=self.settings.environment,
            version=self.settings.app_version,
            camera_type=self.settings.camera_type,
            camera_connected=self.camera.connected,
            plc=plc_diagnostics(),
            gpu_available=gpu_available,
            gpu_device=gpu_device,
            machine_id=self.settings.machine_id,
            workers=workers,
            **self.ringkasan_outbox(),
            capture_save_pending=saver.antrean if saver else 0,
            capture_save_dropped=saver.dibuang if saver else 0,
            tp_telat=self.state.tp_telat,
            current_assignment_id=self.state.current_assignment_id,
            last_successful_api_push=self.state.last_successful_api_push,
            **self.ringkasan_model(),
            ai=ringkas_ai_dari_state(self.state, lengkap=True),
            **self.ringkasan_kamera(),
            disk=ringkas_disk_dari_state(self.state),
            lisensi=self.ringkasan_lisensi(),
        )
