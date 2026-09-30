"""Why the console could not read a line, as a small code the screen words (2026-10-01).

User decision after testing PR #200: outside the Log tab no screen shows system error
text. The Diagnostik card and the line queue used to print the raw reason ("line-1 did
not answer: Client error '404 Not Found' for url ..."); now the backend classifies it
once and the screen maps the code through KAMUS. The raw reason goes to the Log tab.
"""
from __future__ import annotations

import pytest

from palmgrade.domain.line_tak_terbaca import (
    SEBAB_BUKAN_LINE,
    SEBAB_KUNCI_DITOLAK,
    SEBAB_LAIN,
    SEBAB_LINE_GALAT,
    SEBAB_SEMUA,
    SEBAB_TAK_TERJANGKAU,
    sebab_tak_terbaca,
)
from palmgrade.domain.operator_error import LINE_MENOLAK, LINE_TIDAK_DIKENAL, LINE_TIDAK_MENJAWAB


@pytest.mark.parametrize(
    "kode,status,sebab",
    [
        # No answer at all: container down, restarting, timeout.
        (LINE_TIDAK_MENJAWAB, None, SEBAB_TAK_TERJANGKAU),
        # Something answered 404 at the line's address: not an AutoGrade line there, or a
        # line too old for the route (the case the user saw on the Status tab).
        (LINE_TIDAK_MENJAWAB, 404, SEBAB_BUKAN_LINE),
        # The line itself refused the console key.
        (LINE_MENOLAK, 401, SEBAB_KUNCI_DITOLAK),
        (LINE_MENOLAK, 403, SEBAB_KUNCI_DITOLAK),
        # The line answered with its own error.
        (LINE_TIDAK_MENJAWAB, 500, SEBAB_LINE_GALAT),
        (LINE_TIDAK_MENJAWAB, 503, SEBAB_LINE_GALAT),
        # Anything else: a status nobody expects, or no operator code at all.
        (LINE_TIDAK_MENJAWAB, 418, SEBAB_LAIN),
        (LINE_TIDAK_DIKENAL, None, SEBAB_LAIN),
        (None, None, SEBAB_LAIN),
    ],
)
def test_sebab_dipilih_dari_kode_dan_status(kode, status, sebab):
    assert sebab_tak_terbaca(kode, status) == sebab


def test_kunci_ditolak_dikenali_dari_statusnya_juga():
    """`_get_json` sends 401/403 as LINE_MENOLAK; a status alone must still read as the key."""
    assert sebab_tak_terbaca(LINE_TIDAK_MENJAWAB, 401) == SEBAB_KUNCI_DITOLAK


def test_kosakata_lengkap_dan_tanpa_ganda():
    """The screen has one KAMUS sentence per code (`lineSebab_<code>`), pinned against this tuple."""
    assert set(SEBAB_SEMUA) == {
        SEBAB_TAK_TERJANGKAU, SEBAB_BUKAN_LINE, SEBAB_KUNCI_DITOLAK, SEBAB_LINE_GALAT, SEBAB_LAIN,
    }
    assert len(SEBAB_SEMUA) == len(set(SEBAB_SEMUA))
