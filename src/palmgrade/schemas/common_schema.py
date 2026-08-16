from pydantic import BaseModel


class ApiMessage(BaseModel):
    message: str
    detail: str | None = None


class WorkerStatus(BaseModel):
    name: str
    alive: bool


class HealthDetailSchema(BaseModel):
    status: str
    environment: str
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
    current_assignment_id: str | None = None
    last_successful_api_push: str | None = None
