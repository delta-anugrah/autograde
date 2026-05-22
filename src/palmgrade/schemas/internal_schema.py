from pydantic import BaseModel


class AssignmentSyncRequest(BaseModel):
    machine_id: str
    assignment_id: str
    truck_id: str
    assigned_at: str


class AssignmentSyncResponse(BaseModel):
    accepted: bool
    machine_id: str
    truck_id: str
    assignment_id: str


class ManualRejectCommandRequest(BaseModel):
    machine_id: str
    assignment_id: str
    requested_by: str
    requested_at: str


class ManualRejectCommandResponse(BaseModel):
    accepted: bool
    message: str
