from __future__ import annotations

import base64
import json
import math
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from .local_repo import LicenseLocalRepo
from .types import (
    EffectiveLicense,
    LicensePayload,
    LicenseWarning,
)

SECONDS_PER_DAY = 24 * 3600


def _b64url_decode(s: str) -> bytes:
    s += "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


class LicenseManager:
    """Verifikasi surat izin yang dicetak API cloud.

    Tokennya datang dari env (`LICENSE_TOKEN`), bukan dari HTTP: PC pabrik
    tidak punya internet, jadi tidak ada yang bisa ditanya saat runtime. Token
    dipasang operator lewat `palmgrade license <token>` dan baru berlaku saat
    container dibuat ulang (env nempel saat itu).

    Kuncinya asimetris: pabrik cuma pegang public key, jadi bisa memeriksa tapi
    tidak bisa mengarang izin sendiri.
    """

    def __init__(
        self,
        pubkey_pem: str,
        repo: LicenseLocalRepo | None,
        token: str = "",
    ) -> None:
        self._pubkey_pem = pubkey_pem
        self._repo = repo
        self._token = (token or "").strip()
        self._public_key: Ed25519PublicKey = self._load_pubkey(pubkey_pem)
        self._max_seen: int = 0

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
            company_id=payload_dict["company_id"],
            company_name=payload_dict["company_name"],
            status=payload_dict["status"],
            nbf=int(payload_dict["nbf"]),
            iat=int(payload_dict["iat"]),
            exp=int(payload_dict["exp"]),
            license_expires_at=int(payload_dict["license_expires_at"]),
            warning_days_before_expiry=int(payload_dict["warning_days_before_expiry"]),
            grace_days_after_expiry=int(payload_dict["grace_days_after_expiry"]),
            server_time=int(payload_dict["server_time"]),
            nonce=payload_dict["nonce"],
            kid=payload_dict["kid"],
        )

        if p.kid != header.get("kid"):
            raise ValueError("kid mismatch")

        return p

    def _warning_for(self, p: LicensePayload, now: int) -> LicenseWarning | None:
        seconds_until_expiry = p.license_expires_at - now
        warning_window = p.warning_days_before_expiry * SECONDS_PER_DAY

        if 0 < seconds_until_expiry <= warning_window:
            return LicenseWarning(
                code="LICENSE_EXPIRING_SOON",
                message="Langganan akan habis. Hubungi Palmgrade untuk memperpanjang.",
                days_remaining=max(0, math.ceil(seconds_until_expiry / SECONDS_PER_DAY)),
            )

        if p.license_expires_at < now <= p.exp:
            seconds_until_grace_ends = p.exp - now
            return LicenseWarning(
                code="LICENSE_EXPIRED_GRACE",
                message="Langganan sudah habis, masa tenggang berjalan. Segera perpanjang.",
                days_remaining=max(0, math.ceil(seconds_until_grace_ends / SECONDS_PER_DAY)),
            )

        return None

    def _build(self, **kwargs) -> EffectiveLicense:
        return EffectiveLicense(
            status=kwargs["status"],
            reason=kwargs["reason"],
            payload=kwargs.get("payload"),
            warning=kwargs.get("warning"),
        )

    def _evaluate(self, p: LicensePayload, max_seen_server_time: int) -> EffectiveLicense:
        now = int(time.time())

        if now < p.nbf:
            return self._build(status="EXPIRED", reason="not before", payload=p)

        if p.server_time < max_seen_server_time:
            return self._build(status="EXPIRED", reason="server_time rollback", payload=p)

        if p.status == "CANCEL":
            return self._build(status="EXPIRED", reason="canceled", payload=p)

        if p.status == "EXPIRED":
            return self._build(status="EXPIRED", reason="subscription expired", payload=p)

        if now > p.exp:
            return self._build(status="EXPIRED", reason="grace period ended", payload=p)

        if p.license_expires_at < now <= p.exp:
            return self._build(
                status="GRACE",
                reason="expired-grace",
                payload=p,
                warning=self._warning_for(p, now),
            )

        return self._build(
            status=p.status,
            reason="valid",
            payload=p,
            warning=self._warning_for(p, now),
        )

    async def init(self) -> None:
        if self._repo:
            await self._repo.init()
            state = await self._repo.read()
            self._max_seen = state.max_seen_server_time

    async def get_effective_license(self) -> EffectiveLicense:
        """Nilai izin saat ini. Murni CPU: token dari env, tidak ada I/O
        jaringan maupun SQLite per panggilan."""
        if not self._token:
            return self._build(status="EXPIRED", reason="no token", payload=None)

        try:
            payload = self._verify_jws(self._token)
        except Exception as exc:
            return self._build(status="EXPIRED", reason=f"invalid token: {exc}", payload=None)

        return self._evaluate(payload, self._max_seen)
