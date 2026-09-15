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

# Quoted value, unrolled-loop form (non-special run, then repeat escape-pair +
# run) — the only way to match a given input. `(?:\\.|(?!q).)*` looks
# equivalent but is ambiguous on a run of backslashes and blows up
# exponentially on an unterminated value; this runs inside a logging handler,
# so a hang here would freeze whatever thread was logging, maybe a grading
# line. Named groups, not \1-backreferences — numbered ones renumber by
# position once embedded below and silently point at the wrong group.
_NILAI_KUTIP = (
    r'(?P<kutip>["\'])'
    r'(?P<isi_kutip>'
    r'(?:(?!(?P=kutip)|\\).)*'
    r'(?:\\.(?:(?!(?P=kutip)|\\).)*)*'
    r')'
    r'(?P=kutip)'
)

# Unquoted value: an optional auth scheme word stays visible; the value stops
# at the next separator. `&`/`#` end it only when followed by `word=` — deep
# inside a token they must stay part of the value (else the tail leaks after
# the marker), but before the next query param they must still end it (else
# that param gets swallowed).
_NILAI_POLOS = (
    r'(?P<skema>(?:(?:Bearer|Basic|Token|Digest)\s+)?)'
    r'(?P<nilai_polos>(?:[^\s,;}\'"&#]|[&#](?!\w+=))+)'
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
