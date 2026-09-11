from pydantic import BaseModel, field_validator


class AssignmentSyncRequest(BaseModel):
    machine_id: str
    assignment_id: str | None
    truck_id: str | None
    assigned_at: str

    @field_validator("assignment_id", "truck_id")
    @classmethod
    def _kosong_jadi_none(cls, nilai: str | None) -> str | None:
        """Melepas truk = kirim string kosong; kontrak ini tidak punya cara lain.

        Harus jadi `None` di sini, bukan diteruskan apa adanya: `""` ikut nempel
        ke payload event berikutnya dan palmgrade-api memvalidasinya sebagai UUID
        → event ditolak 400 dan mendarat di `outbox_failed`.
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
