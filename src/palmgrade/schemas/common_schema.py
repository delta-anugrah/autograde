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
    gpu_available: bool
    gpu_device: str | None
    machine_id: str
    workers: list[WorkerStatus]
