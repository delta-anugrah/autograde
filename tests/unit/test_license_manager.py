"""Unit tests untuk LicenseManager — verifikasi JWS Ed25519 + state machine efektif.

License guard ini offline-first: token JWS (Ed25519) di-cache lokal, lalu di-evaluasi
tiap request. Kalau logic-nya salah, kamera bisa mati di prod (false-EXPIRED) atau
malah jalan padahal langganan sudah dibatalkan. Test ini mengunci:

- `_verify_jws`: signature ASLI (bukan mock) — tamper payload/sig/kid harus ditolak.
- `_evaluate`: seluruh cabang state machine (ACTIVE/TRIAL/EXPIRED/CANCEL/GRACE,
  anti-rollback server_time, nbf).
- `_warning_for`: window "expiring soon" + "grace".

Sengaja pakai signature Ed25519 asli (bukan mock) supaya verifikasi benar-benar
teruji.
"""
from __future__ import annotations

import base64
import json
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)

from palmgrade.license.manager import SECONDS_PER_DAY, LicenseManager

COMPANY_ID = "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@pytest.fixture
def keypair():
    priv = Ed25519PrivateKey.generate()
    pub_pem = priv.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return priv, pub_pem


@pytest.fixture
def mgr(keypair):
    _, pub_pem = keypair
    # repo tidak dipakai di test _verify_jws / _evaluate (dipanggil langsung).
    return LicenseManager(pubkey_pem=pub_pem, repo=None)


def _make_payload(**over):
    now = int(time.time())
    base = {
        "company_id": COMPANY_ID,
        "company_name": "PT Test",
        "status": "ACTIVE",
        "nbf": now - 10,
        "iat": now - 100,
        "exp": now + 30 * SECONDS_PER_DAY,
        "license_expires_at": now + 30 * SECONDS_PER_DAY,
        "warning_days_before_expiry": 7,
        "grace_days_after_expiry": 3,
        "server_time": now,
        "nonce": "n1",
        "kid": "key-1",
    }
    base.update(over)
    return base


def _sign_jws(priv, payload_dict, *, header=None):
    header = header or {"alg": "EdDSA", "kid": payload_dict["kid"]}
    header_b64 = _b64url(json.dumps(header).encode())
    payload_b64 = _b64url(json.dumps(payload_dict).encode())
    message = f"{header_b64}.{payload_b64}".encode()
    sig = priv.sign(message)
    return f"{header_b64}.{payload_b64}.{_b64url(sig)}"


# --- _load_pubkey ---------------------------------------------------------

def test_load_pubkey_rejects_non_ed25519():
    from cryptography.hazmat.primitives.asymmetric import rsa

    rsa_pub = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    pem = rsa_pub.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    with pytest.raises(ValueError, match="Ed25519"):
        LicenseManager(pubkey_pem=pem, repo=None)


# --- _verify_jws ----------------------------------------------------------

def test_verify_jws_valid_signature(mgr, keypair):
    priv, _ = keypair
    token = _sign_jws(priv, _make_payload())
    p = mgr._verify_jws(token)
    assert p.company_id == COMPANY_ID
    assert p.company_name == "PT Test"
    assert p.status == "ACTIVE"


def test_verify_jws_rejects_wrong_part_count(mgr):
    with pytest.raises(ValueError, match="Invalid JWS format"):
        mgr._verify_jws("only.two")


def test_verify_jws_rejects_tampered_payload(mgr, keypair):
    priv, _ = keypair
    token = _sign_jws(priv, _make_payload(status="ACTIVE"))
    header_b64, _payload_b64, sig_b64 = token.split(".")
    forged_payload = _b64url(json.dumps(_make_payload(status="EXPIRED")).encode())
    tampered = f"{header_b64}.{forged_payload}.{sig_b64}"
    with pytest.raises(ValueError, match="Invalid JWS signature"):
        mgr._verify_jws(tampered)


def test_verify_jws_rejects_kid_mismatch(mgr, keypair):
    priv, _ = keypair
    # Header kid beda dari payload kid → harus ditolak (signature tetap valid).
    payload = _make_payload(kid="key-1")
    token = _sign_jws(priv, payload, header={"alg": "EdDSA", "kid": "other-key"})
    with pytest.raises(ValueError, match="kid mismatch"):
        mgr._verify_jws(token)


def test_verify_jws_rejects_foreign_key(keypair):
    # Ditandatangani private key lain → gagal verify di pubkey mgr.
    priv, _ = keypair
    other_priv = Ed25519PrivateKey.generate()
    other_pub = other_priv.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    ).decode()
    mgr_other = LicenseManager(pubkey_pem=other_pub, repo=None)
    token = _sign_jws(priv, _make_payload())
    with pytest.raises(ValueError, match="Invalid JWS signature"):
        mgr_other._verify_jws(token)


# --- _evaluate: cabang EXPIRED --------------------------------------------

def _payload_obj(mgr, keypair, **over):
    priv, _ = keypair
    return mgr._verify_jws(_sign_jws(priv, _make_payload(**over)))


def test_evaluate_not_before_is_expired(mgr, keypair):
    now = int(time.time())
    p = _payload_obj(mgr, keypair, nbf=now + 3600)
    eff = mgr._evaluate(p, max_seen_server_time=0)
    assert eff.status == "EXPIRED"
    assert eff.reason == "not before"


def test_evaluate_server_time_rollback_is_expired(mgr, keypair):
    now = int(time.time())
    p = _payload_obj(mgr, keypair, server_time=now - 10_000)
    eff = mgr._evaluate(p, max_seen_server_time=now)
    assert eff.status == "EXPIRED"
    assert eff.reason == "server_time rollback"


def test_evaluate_canceled_is_expired(mgr, keypair):
    p = _payload_obj(mgr, keypair, status="CANCEL")
    eff = mgr._evaluate(p, max_seen_server_time=0)
    assert eff.status == "EXPIRED"
    assert eff.reason == "canceled"


def test_evaluate_status_expired_is_expired(mgr, keypair):
    p = _payload_obj(mgr, keypair, status="EXPIRED")
    eff = mgr._evaluate(p, max_seen_server_time=0)
    assert eff.status == "EXPIRED"
    assert eff.reason == "subscription expired"


def test_evaluate_grace_period_ended_is_expired(mgr, keypair):
    now = int(time.time())
    # exp di masa lalu → grace sudah lewat.
    p = _payload_obj(mgr, keypair, exp=now - 10, license_expires_at=now - 20)
    eff = mgr._evaluate(p, max_seen_server_time=0)
    assert eff.status == "EXPIRED"
    assert eff.reason == "grace period ended"


# --- _evaluate: cabang GRACE / valid --------------------------------------

def test_evaluate_grace_when_expired_but_within_exp(mgr, keypair):
    now = int(time.time())
    # license_expires_at < now <= exp → GRACE.
    p = _payload_obj(
        mgr, keypair,
        license_expires_at=now - SECONDS_PER_DAY,
        exp=now + 2 * SECONDS_PER_DAY,
    )
    eff = mgr._evaluate(p, max_seen_server_time=0)
    assert eff.status == "GRACE"
    assert eff.reason == "expired-grace"
    assert eff.warning is not None
    assert eff.warning.code == "LICENSE_EXPIRED_GRACE"


def test_evaluate_online_active_is_valid(mgr, keypair):
    p = _payload_obj(mgr, keypair, status="ACTIVE")
    eff = mgr._evaluate(p, max_seen_server_time=0)
    assert eff.status == "ACTIVE"
    assert eff.reason == "valid"


def test_evaluate_online_trial_is_valid(mgr, keypair):
    p = _payload_obj(mgr, keypair, status="TRIAL")
    eff = mgr._evaluate(p, max_seen_server_time=0)
    assert eff.status == "TRIAL"
    assert eff.reason == "valid"


# --- _warning_for ---------------------------------------------------------

def test_warning_expiring_soon_within_window(mgr, keypair):
    now = int(time.time())
    p = _payload_obj(
        mgr, keypair,
        warning_days_before_expiry=7,
        license_expires_at=now + 3 * SECONDS_PER_DAY,
        exp=now + 6 * SECONDS_PER_DAY,
    )
    w = mgr._warning_for(p, now)
    assert w is not None
    assert w.code == "LICENSE_EXPIRING_SOON"
    assert w.days_remaining == 3


def test_no_warning_when_far_from_expiry(mgr, keypair):
    now = int(time.time())
    p = _payload_obj(
        mgr, keypair,
        warning_days_before_expiry=7,
        license_expires_at=now + 30 * SECONDS_PER_DAY,
        exp=now + 33 * SECONDS_PER_DAY,
    )
    assert mgr._warning_for(p, now) is None

