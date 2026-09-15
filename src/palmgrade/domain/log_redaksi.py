"""Redact secrets before a log line settles on disk for 180 days.

Error messages often echo payload fragments, and these logs get read over
AnyDesk on a PC several people share. Pure text-in-text-out — knows nothing
about sqlite or logging.
"""

from __future__ import annotations

import re

_KUNCI = (
    "password|sandi|password_hash|token|secret|authorization|api_key"
    "|x-webhook-secret|konsol_sesi"
)

# The key must start the string or follow a separator, not sit mid-word — this
# is what keeps "not-a-secret" whole while still matching "password_hash"
# (underscore is deliberately not a separator).
_BATAS_KUNCI = r'(?:^|(?<=[\s"\'{,;?&]))'
_KUNCI_G = rf'(?P<kunci>["\']?(?:{_KUNCI})["\']?\s*[:=]\s*)'

# Quoted value: `\\.` matches first so an escaped quote doesn't end the value
# early; DOTALL (in the outer flags) lets it span a newline — a multi-line
# traceback is exactly the shape this filter exists to catch. Named groups
# throughout, not \1-style backreferences: once embedded in the composed
# pattern below, a numbered backreference renumbers by position and silently
# points at the wrong group.
_NILAI_KUTIP = r'(?P<kutip>["\'])(?P<isi_kutip>(?:\\.|(?!(?P=kutip)).)*)(?P=kutip)'

# Unquoted value: an optional auth scheme word is kept visible, the real
# value stops at the next separator.
_NILAI_POLOS = (
    r'(?P<skema>(?:(?:Bearer|Basic|Token|Digest)\s+)?)'
    r'(?P<nilai_polos>[^\s,;}\'"]+)'
)

_POLA = re.compile(
    rf'''(?ixs)
    {_BATAS_KUNCI}{_KUNCI_G}
    (?:{_NILAI_KUTIP}|{_NILAI_POLOS})
    '''
)

_TUTUP = "«ditutup»"


def redaksi(teks: str) -> str:
    """Return `teks` with secret values replaced by a marker."""
    if not teks:
        return teks
    return _POLA.sub(_ganti, teks)


def _ganti(m: re.Match[str]) -> str:
    if m.group("kutip") is not None:
        kutip = m.group("kutip")
        return f"{m.group('kunci')}{kutip}{_TUTUP}{kutip}"
    skema = m.group("skema") or ""  # unquoted: keep the scheme word, hide the rest
    return f"{m.group('kunci')}{skema}{_TUTUP}"
