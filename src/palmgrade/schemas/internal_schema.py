from typing import Literal

from pydantic import BaseModel, field_validator


class AssignmentSyncRequest(BaseModel):
    machine_id: str
    assignment_id: str | None
    truck_id: str | None
    assigned_at: str
    # Sumber TBS truk ini menurut AutoERP, dititipkan konsol. None = tidak
    # dikirim (palmgrade-api, konsol lama) atau truk yang sumbernya belum jelas;
    # dua-duanya berarti sortir normal. Sengaja Literal, bukan str: nilai asing
    # lebih baik ditolak 422 daripada diam-diam mematikan pembuangan buah.
    ffb_source: Literal["Internal", "External"] | None = None

    @field_validator("assignment_id", "truck_id")
    @classmethod
    def _kosong_jadi_none(cls, nilai: str | None) -> str | None:
        """Releasing a truck = send an empty string; this contract has no other way.

        It must become `None` here, not pass through as-is: `""` rides along into
        the next event payload and palmgrade-api validates it as a UUID → the
        event is rejected 400 and lands in `outbox_failed`.
        """
        return nilai or None


class AssignmentSyncResponse(BaseModel):
    accepted: bool
    machine_id: str
    truck_id: str | None
    assignment_id: str | None


class ManualRejectCommandRequest(BaseModel):
    machine_id: str
    assignment_id: str
    requested_by: str
    requested_at: str


class ManualRejectCommandResponse(BaseModel):
    accepted: bool
    message: str


class OutboxRequeueResponse(BaseModel):
    requeued: int


class PistonCommandRequest(BaseModel):
    machine_id: str
    open: bool
    requested_by: str = "operator"
    requested_at: str


class LineStatusResponse(BaseModel):
    machine_id: str
    truck_id: str | None
    ffb_source: str | None
    piston: dict | None


class PlcCoilCommandRequest(BaseModel):
    machine_id: str
    coil: int
    requested_by: str = "support"


class PlcCoilCommandResponse(BaseModel):
    fired: bool
    coil: int


class PlcStateResponse(BaseModel):
    """DI snapshot + which coils this line allows hand-firing. Read-only."""

    enabled: bool
    inputs: list[bool] = []
    testable_coils: list[int] = []
