"""The two console account roles, plus filtering for roles pulled from AutoERP.

Pure rules, no I/O: `console_repository` stores it, `routes/console.py` enforces it.
Only two roles on purpose — none of the developer screens split sensibly between
a third role, which would just be a second name for one of these.
"""

from __future__ import annotations

ROLE_OPERATOR = "operator"
ROLE_SUPPORT = "support"

_KNOWN_ROLES = frozenset({ROLE_OPERATOR, ROLE_SUPPORT})


def sanitize_role(value: object) -> str:
    """A known role, or `operator`. Never raises: a bad row must still be able
    to sign in as a plain operator, not lock the mill's screen."""
    if not isinstance(value, str):
        return ROLE_OPERATOR
    cleaned = value.strip().lower()
    return cleaned if cleaned in _KNOWN_ROLES else ROLE_OPERATOR


def parse_allowed_roles(raw: str) -> frozenset[str]:
    """`PERAN_ERP_DIIZINKAN` as the set of roles ERP is allowed to grant."""
    if not raw:
        return frozenset()
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def filter_erp_role(value: object, allowed: frozenset[str]) -> str:
    """Role from AutoERP, but only if this PC's allow-list grants it.

    The one brake the factory side can pull on its own: clear the setting and
    restart, and no ERP account can open a developer screen.
    """
    role = sanitize_role(value)
    return role if role in allowed else ROLE_OPERATOR
