from __future__ import annotations

import base64
import hashlib
import json
import math
import socket
import time

import psutil
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from .local_repo import LicenseLocalRepo
from .sync_client import SyncClient
from .types import (
    EffectiveLicense,
    LicensePayload,
    LicenseWarning,
)

SECONDS_PER_DAY = 24 * 3600


def _b64url_decode(s: str) -> bytes:
    s += "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


def _compute_device_id() -> str:
    hostname = socket.gethostname()
    macs: list[str] = []
    for addrs in psutil.net_if_addrs().values():
        for addr in addrs:
            if (
                addr.family == psutil.AF_LINK
                and addr.address
                and addr.address != "00:00:00:00:00:00"
            ):
                macs.append(addr.address)
    raw = f"{hostname}|{','.join(sorted(macs))}"
    return hashlib.sha256(raw.encode()).hexdigest()


class LicenseManager:
    def __init__(
        self,
        pubkey_pem: str,
        repo: LicenseLocalRepo,
        sync_client: SyncClient,
    ) -> None:
        self._pubkey_pem = pubkey_pem
        self._repo = repo
        self._sync = sync_client
        self._device_id = _compute_device_id()
        self._public_key: Ed25519PublicKey = self._load_pubkey(pubkey_pem)

    @staticmethod
    def _load_pubkey(pem: str) -> Ed25519PublicKey:
        key = load_pem_public_key(pem.encode())
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("Expected Ed25519 public key")
        return key

    def _verify_jws(self, token_jws: str) -> LicensePayload:
        parts = token_jws.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid JWS format")

        header_b64, payload_b64, sig_b64 = parts
        header = json.loads(_b64url_decode(header_b64))
        payload_dict = json.loads(_b64url_decode(payload_b64))
        signature = _b64url_decode(sig_b64)
        message = f"{header_b64}.{payload_b64}".encode()

        try:
            self._public_key.verify(signature, message)
        except InvalidSignature as exc:
            raise ValueError("Invalid JWS signature") from exc

        p = LicensePayload(
            sub_id=payload_dict["sub_id"],
            status=payload_dict["status"],
            plan=payload_dict["plan"],
            device_id=payload_dict["device_id"],
            nbf=int(payload_dict["nbf"]),
            iat=int(payload_dict["iat"]),
            exp=int(payload_dict["exp"]),
            license_expires_at=int(payload_dict["license_expires_at"]),
            warning_days_before_expiry=int(payload_dict["warning_days_before_expiry"]),
            grace_days_after_expiry=int(payload_dict["grace_days_after_expiry"]),
            slow_response_ms=int(payload_dict["slow_response_ms"]),
            max_offline_days=int(payload_dict["max_offline_days"]),
            server_time=int(payload_dict["server_time"]),
            nonce=payload_dict["nonce"],
            kid=payload_dict["kid"],
        )

        if p.kid != header.get("kid"):
            raise ValueError("kid mismatch")

        return p

    def _max_offline_until(self, p: LicensePayload) -> int:
        return min(p.exp, p.iat + p.max_offline_days * SECONDS_PER_DAY)

    def _warning_for(self, p: LicensePayload, now: int) -> LicenseWarning | None:
        seconds_until_expiry = p.license_expires_at - now
        warning_window = p.warning_days_before_expiry * SECONDS_PER_DAY

        if 0 < seconds_until_expiry <= warning_window:
            return LicenseWarning(
                code="LICENSE_EXPIRING_SOON",
                message="License will expire soon. Please renew your subscription.",
                days_remaining=max(0, math.ceil(seconds_until_expiry / SECONDS_PER_DAY)),
            )

        if p.license_expires_at < now <= p.exp:
            seconds_until_grace_ends = p.exp - now
            return LicenseWarning(
                code="LICENSE_EXPIRED_GRACE",
                message="License has expired. Grace period is active. Please renew your subscription.",
                days_remaining=max(0, math.ceil(seconds_until_grace_ends / SECONDS_PER_DAY)),
            )

        return None

    def _build(self, **kwargs) -> EffectiveLicense:
        return EffectiveLicense(
            status=kwargs["status"],
            reason=kwargs["reason"],
            payload=kwargs.get("payload"),
            max_offline_until=kwargs.get("max_offline_until", 0),
            warning=kwargs.get("warning"),
            should_slow_response=kwargs.get("should_slow_response", False),
            slow_response_ms=kwargs.get("slow_response_ms", 0),
        )

    def _evaluate(self, p: LicensePayload, online: bool, max_seen_server_time: int) -> EffectiveLicense:
        now = int(time.time())
        max_offline_until = self._max_offline_until(p)

        if p.device_id != self._device_id:
            return self._build(status="EXPIRED", reason="device_id mismatch", payload=p, max_offline_until=max_offline_until)

        if now < p.nbf:
            return self._build(status="EXPIRED", reason="not before", payload=p, max_offline_until=max_offline_until)

        if p.server_time < max_seen_server_time:
            return self._build(status="EXPIRED", reason="server_time rollback", payload=p, max_offline_until=max_offline_until)

        if p.status == "CANCEL":
            return self._build(status="EXPIRED", reason="canceled", payload=p, max_offline_until=max_offline_until)

        if p.status == "EXPIRED":
            return self._build(status="EXPIRED", reason="subscription expired", payload=p, max_offline_until=max_offline_until)

        if now > p.exp:
            return self._build(status="EXPIRED", reason="grace period ended", payload=p, max_offline_until=max_offline_until)

        if p.license_expires_at < now <= p.exp:
            return self._build(
                status="GRACE",
                reason="online-expired-grace" if online else "offline-expired-grace",
                payload=p,
                max_offline_until=max_offline_until,
                warning=self._warning_for(p, now),
                should_slow_response=True,
                slow_response_ms=p.slow_response_ms,
            )

        if online:
            return self._build(
                status=p.status,
                reason="online-valid",
                payload=p,
                max_offline_until=max_offline_until,
                warning=self._warning_for(p, now),
            )

        if now <= max_offline_until and p.status in ("ACTIVE", "TRIAL"):
            return self._build(
                status=p.status,
                reason="offline-valid",
                payload=p,
                max_offline_until=max_offline_until,
                warning=self._warning_for(p, now),
            )

        return self._build(status="EXPIRED", reason="offline-expired", payload=p, max_offline_until=max_offline_until)

    async def init(self) -> None:
        await self._repo.init()

    async def _sync_if_online(self) -> LicensePayload | None:
        try:
            token_jws = await self._sync.fetch_latest(self._device_id)
            payload = self._verify_jws(token_jws)
            if payload.device_id != self._device_id:
                raise ValueError("device mismatch")
            await self._repo.write_token(token_jws, payload.server_time)
            return payload
        except Exception:
            return None

    async def get_effective_license(self, online_hint: bool = True) -> EffectiveLicense:
        synced = await self._sync_if_online() if online_hint else None
        state = await self._repo.read()

        if synced:
            payload = synced
        elif state.token_jws:
            try:
                payload = self._verify_jws(state.token_jws)
            except Exception:
                return self._build(status="EXPIRED", reason="invalid cached token", max_offline_until=0)
        else:
            return self._build(status="EXPIRED", reason="no token", max_offline_until=0)

        return self._evaluate(payload, bool(synced), state.max_seen_server_time)
