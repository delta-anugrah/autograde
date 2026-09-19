"""Redact secrets before a log line settles on disk for 180 days.

Error messages often echo payload fragments, and these logs get read over
AnyDesk on a PC several people share. Pure text-in-text-out — knows nothing
about sqlite or logging.
"""

from __future__ import annotations

import re

_KEYS = (
    "password|sandi|password_hash|token|secret|authorization|api_key"
    "|x-webhook-secret|konsol_sesi"
)

# The key must start the string or follow a separator, not sit mid-word — this
# is what keeps "not-a-secret" whole while still matching "password_hash"
# (underscore is deliberately not a separator).
_KEY_BOUNDARY = r'(?:^|(?<=[\s"\'{,;?&]))'
_KEY_G = rf'(?P<key>["\']?(?:{_KEYS})["\']?\s*[:=]\s*)'

# Quoted value, unrolled-loop form (non-special run, then repeat escape-pair +
# run) — the only way to match a given input. `(?:\\.|(?!q).)*` looks
# equivalent but is ambiguous on a run of backslashes and blows up
# exponentially on an unterminated value; this runs inside a logging handler,
# so a hang here would freeze whatever thread was logging, maybe a grading
# line. Named groups, not \1-backreferences — numbered ones renumber by
# position once embedded below and silently point at the wrong group.
_QUOTED_VALUE = (
    r'(?P<quote>["\'])'
    r'(?P<quoted_body>'
    r'(?:(?!(?P=quote)|\\).)*'
    r'(?:\\.(?:(?!(?P=quote)|\\).)*)*'
    r')'
    r'(?P=quote)'
)

# Unquoted value: an optional auth scheme word stays visible; the value stops
# at the next separator. `&`/`#` end it only when followed by `word=` — deep
# inside a token they must stay part of the value (else the tail leaks after
# the marker), but before the next query param they must still end it (else
# that param gets swallowed).
_PLAIN_VALUE = (
    r'(?P<scheme>(?:(?:Bearer|Basic|Token|Digest)\s+)?)'
    r'(?P<plain_value>(?:[^\s,;}\'"&#]|[&#](?!\w+=))+)'
)

_PATTERN = re.compile(
    rf'''(?ixs)
    {_KEY_BOUNDARY}{_KEY_G}
    (?:{_QUOTED_VALUE}|{_PLAIN_VALUE})
    '''
)

_MASK = "«redacted»"


def redact(text: str) -> str:
    """Return `text` with secret values replaced by a marker."""
    if not text:
        return text
    return _PATTERN.sub(_replace, text)


def _replace(m: re.Match[str]) -> str:
    if m.group("quote") is not None:
        quote = m.group("quote")
        return f"{m.group('key')}{quote}{_MASK}{quote}"
    scheme = m.group("scheme") or ""  # unquoted: keep the scheme word, hide the rest
    return f"{m.group('key')}{scheme}{_MASK}"
