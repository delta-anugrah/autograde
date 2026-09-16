from typing import Literal

from pydantic import BaseModel, field_validator


class AssignmentSyncRequest(BaseModel):
    machine_id: str
    assignment_id: str | None
    truck_id: str | None
    assigned_at: str
    # This truck's FFB source per AutoERP, forwarded by the console. None = not
    # sent (palmgrade-api, an old console) or a truck whose source is not yet
    # known; both mean normal sorting. Deliberately Literal, not str: an
    # unknown value is better refused with 422 than silently disabling reject.
    ffb_source: Literal["Internal", "External"] | None = None
    # Display label for the capture folder name, forwarded by the console.
    # `truck_id` is a uuid5 *of* the plate and cannot be reversed, so without
    # this the folder can only be named after an opaque id. Optional on purpose:
    # an older console omits it, and a line that refused the payload would stop
    # assignment outright during a partial upgrade.
    plate: str | None = None

    @field_validator("assignment_id", "truck_id", "plate")
    @classmethod
    def _empty_becomes_none(cls, value: str | None) -> str | None:
        """Releasing a truck = send an empty string; this contract has no other way.

        It must become `None` here, not pass through as-is: `""` rides along into
        the next event payload and palmgrade-api validates it as a UUID → the
        event is rejected 400 and lands in `outbox_failed`.
        """
        return value or None


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
