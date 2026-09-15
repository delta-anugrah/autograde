"""Redact secrets before a log line settles on disk for 180 days.

Error messages often echo payload fragments, and these logs get read over
AnyDesk on a PC several people share. Pure text-in-text-out — knows nothing
about sqlite or logging.
"""

from __future__ import annotations

import re

_KUNCI = "password|sandi|password_hash|token|secret|authorization|api_key|x-webhook-secret"

# `key=value`, `key: value`, and JSON `"key": "value"`. `\b` around the key stops
# "passwordless" from matching "password". The value is either:
#   - quoted: consume to the matching close quote, spaces included (a value
#     with a space is never seen if we stop at whitespace); or
#   - unquoted: stop at the next separator, but first swallow a leading auth
#     scheme word (Bearer/Basic/Token/Digest) so "Authorization: Bearer <tok>"
#     redacts the token, not just the scheme name.
_POLA = re.compile(
    rf'''(?ix)
    (["\']?\b(?:{_KUNCI})\b["\']?\s*[:=]\s*)
    (?:
        (["\'])(.*?)(\2)
        |
        ((?:(?:Bearer|Basic|Token|Digest)\s+)?)([^\s,;}}\'"]+)
    )
    '''
)

_TUTUP = "«ditutup»"


def redaksi(teks: str) -> str:
    """Return `teks` with secret values replaced by a marker."""
    if not teks:
        return teks
    return _POLA.sub(_ganti, teks)


def _ganti(m: re.Match[str]) -> str:
    if m.group(2) is not None:  # quoted value matched
        return f"{m.group(1)}{m.group(2)}{_TUTUP}{m.group(4)}"
    scheme = m.group(5) or ""  # unquoted: keep the scheme word, hide the rest
    return f"{m.group(1)}{scheme}{_TUTUP}"
