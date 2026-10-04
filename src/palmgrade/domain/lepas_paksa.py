"""Lepas paksa, the pure rules (user 2026-10-04, rule 13).

Rule 13 records a release only after the line has heard it. A line that never answers
can never hear it, so its truck stayed on the console: Update now was refused (rule 38),
automatic assignment held (rule 36), and the line, once started again, pulled the
departed truck from the console and stamped it on the next truck's bunches.

Lepas paksa lets the console clear the line by itself, but only for a line that gave no
answer at all. A line that answered anything, a refusal included, is alive and is never
overruled. A line that was only cut off still holds the truck in memory, so the console
remembers each forced release until that line is seen again (`/internal/status` carries
the truck it holds) and then sends the release once more.
"""
from __future__ import annotations

import json

from .line_tak_terbaca import SEBAB_TAK_TERJANGKAU, sebab_tak_terbaca

#: `sync_state` key of the forced releases the line has not heard yet: {line_code: truck_id}.
#: No `setelan_` prefix on purpose: Danger Zone wipes it with the assignments it belongs to.
KUNCI_LEPAS_PAKSA = "lepas_paksa_tertunda"


def boleh_paksa(kode: str | None, status: int | None) -> bool:
    """True only when the line gave no answer at all (refused connection, timeout).

    The same rule that words a silent line on the Diagnostics card, so the two never
    disagree about which line is dead.
    """
    return sebab_tak_terbaca(kode, status) == SEBAB_TAK_TERJANGKAU


def perlu_kirim_ulang(truk_paksa: str, *, truk_di_line: str | None, truk_di_konsol: str | None) -> bool:
    """A line answers again after a forced release: does it still need to hear it?

    Only when it still holds the very truck that was forced off and the console has put
    nothing on that line since. Any other answer ends the pending release: an empty line
    restarted and pulled the empty assignment itself, and a truck the console holds was
    put on through the line (rule 13), so the line already agrees with the console.
    """
    return truk_di_line == truk_paksa and not truk_di_konsol


def baca_tertunda(teks: str | None) -> dict[str, str]:
    """The stored pending releases; anything unreadable counts as nothing pending.

    Read on the status poll, so it never raises. Losing a broken entry costs only the
    re-send to a line that was cut off; the release on the console is already written.
    """
    try:
        isi = json.loads(teks or "{}")
    except ValueError:
        return {}
    if not isinstance(isi, dict):
        return {}
    return {k: v for k, v in isi.items() if isinstance(k, str) and k and isinstance(v, str) and v}


def teks_tertunda(tertunda: dict[str, str]) -> str:
    """The text kept in `sync_state` for `baca_tertunda`."""
    return json.dumps(tertunda, sort_keys=True)
