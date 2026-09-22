"""Turns an `EffectiveLicense` into the numbers a screen can show.

A pure function in its own module, not a method, for the same reason `gate.py`
is: everything that decides whether the mill keeps running must have tests that
actually execute, and importing the console or the workers drags in torch, which
CI deliberately does not install.

**The console reads the same token the cameras do.** Both processes are the same
image with the same `.env`, so there is no second source that could disagree.
Nothing here re-implements the state machine - `LicenseManager` has already
decided; this only formats what it decided.
"""

from __future__ import annotations

import math
import time

from .types import EffectiveLicense

SECONDS_PER_DAY = 86_400

# What the banner should look like. The console maps these to colours; naming
# them here keeps the rule in tested Python rather than in a template.
SEVERITY_NONE = "none"  # healthy, say nothing
SEVERITY_WARNING = "warning"  # expiry approaching
SEVERITY_GRACE = "grace"  # expired, still grading
SEVERITY_BLOCKED = "blocked"  # grading has stopped


def _days_from(seconds: int) -> int:
    """Whole days, rounded up: 0.4 days left is "1 day", never "0 days"."""
    return max(0, math.ceil(seconds / SECONDS_PER_DAY))


def license_summary(
    effective: EffectiveLicense,
    *,
    enabled: bool,
    token_installed: bool,
    now: float | None = None,
) -> dict:
    """The licence block served to the console.

    `enabled=False` is a dev PC or a mill that was never licensed. It reports
    `severity=none` and no dates: the gate is not armed, so a banner would be
    warning about a rule that is not being enforced.
    """
    current = int(time.time() if now is None else now)

    block: dict = {
        "aktif": enabled,
        "token_terpasang": token_installed,
        "status": effective.status,
        "severity": SEVERITY_NONE,
        "aktif_sampai": None,
        "tenggang_sampai": None,
        "sisa_hari": None,
        "perusahaan": None,
    }

    if not enabled:
        return block

    payload = effective.payload

    # No payload means the token is missing or would not verify. Both stop the
    # cameras, so both must show as stopped - a token that fails to parse and
    # one that expired are the same thing to the operator.
    if payload is None:
        block["severity"] = SEVERITY_BLOCKED
        return block

    block["perusahaan"] = payload.company_name
    block["aktif_sampai"] = payload.license_expires_at
    block["tenggang_sampai"] = payload.exp

    if effective.is_expired:
        block["severity"] = SEVERITY_BLOCKED
        block["sisa_hari"] = 0
        return block

    if effective.status == "GRACE":
        block["severity"] = SEVERITY_GRACE
        # Days until grading stops, not days since expiry: the operator needs to
        # know how long they still have, not how late they already are.
        block["sisa_hari"] = _days_from(payload.exp - current)
        return block

    block["sisa_hari"] = _days_from(payload.license_expires_at - current)
    if effective.warning is not None:
        block["severity"] = SEVERITY_WARNING

    return block
