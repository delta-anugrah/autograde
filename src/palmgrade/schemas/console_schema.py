"""Bodies of the operator routes (standard B1): the shape only, never the content rules.

Content rules stay in the domain, which answers with codes the screen words one by one
(`bukan_plat`, `bukan_angka`, a wrong password). A model here only fixes which fields a body
may carry and their JSON types; a body of the wrong shape is 400 `input_tidak_sah`.

Every field is optional, so every body the screen sends still passes and the domain still
decides what an empty one means. What is narrower than before: a number where text belongs
(`{"qr": 123}`) used to reach the domain through `str()` and is now 400. Unknown fields are
ignored, as `payload.get()` ignored them.
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


class ArrivalBody(_Body):
    """Scan 1 (2026-09-30). `at` is the browser clock; the domain checks it."""

    qr: str | None = None
    at: str | None = None


class DepartureBody(_Body):
    """Scan 4: the scanner sends `qr`, the per-row button sends `weighing_id`."""

    qr: str | None = None
    weighing_id: str | None = None
    at: str | None = None


class ScanOtomatisBody(_Body):
    """The one scan field (2026-10-06). `konfirmasi` is the operator's yes to a scan that came
    within 3 minutes of the truck's previous step (a double read otherwise)."""

    qr: str | None = None
    at: str | None = None
    konfirmasi: bool | None = None


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


class AutoAssignBody(_Body):
    """Automatic line assignment (support, 2026-10-01). The domain checks the lines.

    The screen always sends both. A missing field reads as off / no lines, so `{}` saves
    "off" (it never crashes and never turns the setting on).
    """

    aktif: bool | None = None
    lines: list[str] | None = None


class ScannerQrBody(_Body):
    """Scanner QR switch (support, 2026-10-05). A missing `aktif` saves off, like
    `AutoAssignBody`: `{}` never turns it on."""

    aktif: bool | None = None


class TimbanganDummyBody(_Body):
    """Timbangan dummy switch (support, 2026-10-07). A missing `aktif` saves off."""

    aktif: bool | None = None


class SlipBody(_Body):
    """The printable slip switch (support, batch 5.9). A missing field saves "off"."""

    aktif: bool = False


class ShiftBody(_Body):
    """The working day cutoff (support, batch 5.11). Text: the domain reads `5:00` too."""

    cutoff: str | None = None


class PasangBody(_Body):
    """Update now (batch 4.6). The version the screen showed, so a status file that moved
    on in between cannot make one press install a version nobody saw."""

    target: str | None = None
