from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LicenseStatus = Literal["ACTIVE", "TRIAL", "EXPIRED", "CANCEL"]
LicenseEffectiveStatus = Literal["ACTIVE", "TRIAL", "EXPIRED", "CANCEL", "GRACE"]


@dataclass
class LocalState:
    token_jws: str | None
    last_sync_at: int | None
    max_seen_server_time: int
    hash_chain_prev: str | None
    hash_chain_curr: str | None


@dataclass
class LicensePayload:
    sub_id: str
    status: LicenseStatus
    plan: str
    device_id: str
    nbf: int
    iat: int
    exp: int
    license_expires_at: int
    warning_days_before_expiry: int
    grace_days_after_expiry: int
    slow_response_ms: int
    max_offline_days: int
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
    max_offline_until: int
    payload: LicensePayload | None
    warning: LicenseWarning | None
    should_slow_response: bool
    slow_response_ms: int
