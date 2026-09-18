from pydantic import BaseModel


class ApiMessage(BaseModel):
    message: str
    detail: str | None = None
    # Dipakai palmgrade-api lewat GET /system/versions. Sengaja menempel di
    # /health yang murah, bukan /health/detail yang menyentuh GPU + outbox.
    version: str = "unknown"


class WorkerStatus(BaseModel):
    name: str
    alive: bool


class HealthDetailSchema(BaseModel):
    status: str
    environment: str
    version: str = "unknown"
    camera_type: str
    camera_connected: bool
    # None kalau PLC_ENABLED=false — itu keadaan normal di cloud dan PC dev,
    # bukan error. Isinya: inputs (motor fault 0-9 + E-stop 10), dropped_pulses,
    # dropped_submissions. Lihat plc.diagnostics().
    plc: dict | None = None
    gpu_available: bool
    gpu_device: str | None
    machine_id: str
    workers: list[WorkerStatus]
    outbox_pending: int = 0
    outbox_failed: int = 0
    # Antrean penulis bukti (`CaptureSaveWorker`). `capture_save_dropped` naik
    # berarti janjang yang SUDAH digrading dan sudah dapat pulse PLC tidak
    # tersimpan sama sekali — tidak ada gambar, tidak ada sidecar, jadi tidak ada
    # yang bisa ditemukan `BatchUploadWorker._scan()` belakangan. Diekspos di
    # sini karena satu baris log tidak akan pernah terbaca di PC yang cuma
    # dijenguk lewat AnyDesk, sementara angka ini sebaris dengan `outbox_*` yang
    # sudah rutin dilihat.
    capture_save_pending: int = 0
    capture_save_dropped: int = 0
    current_assignment_id: str | None = None
    last_successful_api_push: str | None = None
