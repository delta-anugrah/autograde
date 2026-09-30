"""Bodies of the operator routes (standard B1): the shape only, never the content rules.

Content rules stay in the domain, which answers with codes the screen words one by one
(`bukan_plat`, `bukan_angka`, a wrong password). A model here only fixes which fields a body
may carry and their JSON types; a body of the wrong shape is 400 `input_tidak_sah`.

Every field is optional, so a body that passed before still passes and the domain still
decides what an empty one means. Unknown fields are ignored, as `payload.get()` ignored them.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Body(BaseModel):
    model_config = ConfigDict(extra="ignore")


class LoginBody(_Body):
    email: str | None = None
    sandi: str | None = None


class ManualTruckBody(_Body):
    plate_number: str | None = None
    supplier_id: str | None = None
    # Text or number: the service reads either, as it did before.
    capacity: str | float | None = None


class ScanBody(_Body):
    qr: str | None = None


class WeighingBody(_Body):
    """The manual lane of the scale program's shape (`record_weighing`)."""

    plate_number: str | None = None
    ref: str | int | None = None
    entered_at: str | None = None
    exited_at: str | None = None
    # Text on purpose: the screen sends "14820,5" from an Indonesian keypad, and `_kg`
    # reads the comma. A float field would refuse exactly that.
    gross_kg: str | float | None = None
    tare_kg: str | float | None = None
    net_kg: str | float | None = None
