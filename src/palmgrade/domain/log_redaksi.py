"""Redact secrets before a log line settles on disk for 180 days.

Error messages often echo payload fragments, and these logs get read over
AnyDesk on a PC several people share. Pure text-in-text-out — knows nothing
about sqlite or logging.
"""

from __future__ import annotations

import re

_KUNCI = "password|sandi|password_hash|token|secret|authorization|api_key|x-webhook-secret"

# `key=value`, `key: value`, and JSON `"key": "value"`. The value stops at the
# next separator so the rest of the line stays readable — a log that is fully
# blacked out is as useless as one that leaks.
_POLA = re.compile(
    rf'(?i)(["\']?(?:{_KUNCI})["\']?\s*[:=]\s*)(["\']?)([^\s,;}}\'"]+)(\2)'
)

_TUTUP = "«ditutup»"


def redaksi(teks: str) -> str:
    """Return `teks` with secret values replaced by a marker."""
    if not teks:
        return teks
    return _POLA.sub(rf"\1\2{_TUTUP}\4", teks)
