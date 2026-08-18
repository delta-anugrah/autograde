from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LicenseStatus = Literal["ACTIVE", "TRIAL", "EXPIRED", "CANCEL"]
LicenseEffectiveStatus = Literal["ACTIVE", "TRIAL", "EXPIRED", "CANCEL", "GRACE"]


@dataclass
class LicensePayload:
    """Isi surat izin. Harus cocok persis dengan yang dicetak
    `palmgrade-api/src/utils/license.ts` — ini kontrak lintas repo.

    Yang DIBUANG dari versi lama beserta alasannya:
    - `device_id`: fingerprint-nya ikut MAC veth Docker, yang berubah tiap
      container dibuat ulang — jadi ikatan ke perangkat malah mematikan PC yang
      sah tiap `docker compose up`.
    - `max_offline_days`: `exp` sudah membatasi semuanya, dan tidak ada lagi
      sync otomatis yang perlu dipaksa.
    - `slow_response_ms`: respons yang sengaja dilambatkan bikin operator
      mengira sistem rusak, bukan mengira langganan habis.
    - `sub_id` → `company_id`, `plan` dihapus (belum ada paket berbeda).
    """

    company_id: str
    company_name: str
    status: LicenseStatus
    nbf: int
    iat: int
    exp: int
    license_expires_at: int
    warning_days_before_expiry: int
    grace_days_after_expiry: int
    server_time: int
    nonce: str
    kid: str


@dataclass
class LicenseWarning:
    code: Literal["LICENSE_EXPIRING_SOON", "LICENSE_EXPIRED_GRACE"]
    message: str
    days_remaining: int


@dataclass
class EffectiveLicense:
    status: LicenseEffectiveStatus
    reason: str
    payload: LicensePayload | None
    warning: LicenseWarning | None

    @property
    def is_expired(self) -> bool:
        return self.status == "EXPIRED"

    @property
    def grace_ends_at(self) -> int:
        """Detik Unix akhir grace. 0 = tidak ada lisensi valid sama sekali."""
        return self.payload.exp if self.payload and not self.is_expired else 0
