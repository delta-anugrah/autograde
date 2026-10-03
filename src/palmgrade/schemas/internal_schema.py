from typing import Literal

from pydantic import BaseModel, Field, field_validator


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
        event is rejected 400 and waits in the line queue forever (retried, never delivered).
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


class CameraReconnectRequest(BaseModel):
    """`POST /internal/camera/reconnect` from the console. The name is for the line log only."""

    requested_by: str = Field("?", max_length=200)


class LineStatusResponse(BaseModel):
    machine_id: str
    truck_id: str | None
    ffb_source: str | None
    piston: dict | None
    # Alarm dari blok M yang dibaca line ini (motor fault, E-stop). Kosong =
    # tidak ada alarm ATAU PLC mati; konsol memperlakukan keduanya sama.
    # Default [] supaya konsol lama yang tidak mengenal field ini tetap jalan.
    alarms: list[dict] = []
    # Ringkasan upload foto ke R2 untuk Last Sync konsol (Cloud Photo). None =
    # line belum punya worker upload; konsol lama mengabaikan field ini.
    unggah: dict | None = None
    # Penjaga AI mati (batch 2.1): `PenjagaAi.ringkas()`, tanpa galat mentah.
    # None = penjaga belum dipasang; konsol lama mengabaikan field ini.
    ai: dict | None = None
    # Pemantau disk (batch 3.7): `PemantauDisk.ringkas()`. None = belum dipasang;
    # konsol lama mengabaikan field ini.
    disk: dict | None = None


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
    # Alamat dasar line ini (OK = base, NG = +1, ERROR = +2). Dikirim supaya
    # layar bisa menamai tiap tombol tanpa memaku angka: blok alamat milik
    # panel, dan sudah pernah berubah sekali (coil 0/3/6 -> M1000/1003/1006).
    coil_base: int = 0
    # Awal blok yang DIBACA, supaya layar bisa menyebut alamat M tiap bit.
    di_base: int = 0
    # Huruf device MC Protocol (M / B / Y). Layar menulis alamat persis seperti
    # yang diketik di GX Works2 — alamat yang salah huruf tidak bisa dicocokkan
    # ke ladder. Bawaan "M" supaya konsol versi lama tetap masuk akal.
    device_prefix: str = "M"


class SetelanGradingRequest(BaseModel):
    """Setelan grading dari konsol. Divalidasi lagi di `domain/setelan_grading`
    — Pydantic cuma menjamin bentuknya, bukan kewarasan angkanya."""

    conf_threshold: float
    minimum_size: int
    # Opsional supaya konsol versi lama tetap bisa mengirim setelan. Tanpa ini
    # satu PKS yang konsolnya belum di-update akan ditolak 400 dan berhenti
    # menerima SEMUA setelan, termasuk dua yang sudah lama jalan. 0 = garis mati.
    garis_capture: int = 0
    sumbu_garis: str = "tegak"
    mode_dev: bool = False


class SetelanGradingResponse(BaseModel):
    conf_threshold: float
    minimum_size: int
    garis_capture: int = 0
    sumbu_garis: str = "tegak"
    mode_dev: bool = False
    sumber: str  # "konsol" kalau ditimpa, "env" kalau masih dari .env


class RestartResponse(BaseModel):
    """Jawaban `POST /internal/restart`, dikirim SEBELUM proses keluar."""

    status: str
    jeda_detik: float
