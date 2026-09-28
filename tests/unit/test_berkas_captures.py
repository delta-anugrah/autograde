from __future__ import annotations

import pytest

from palmgrade.domain.berkas_captures import boleh_disajikan


@pytest.mark.parametrize("jalur", [
    "results/2026-09-28/101500_B1234XY_abcd1234/bbox/Ripe/20260928_101501_auto.webp",
    "results/2026-09-28/20260928_101501_ripeness.json",
    "results/2026-09-28/x/thumb/JK/a.webp",
])
def test_foto_dan_sidecar_boleh(jalur):
    assert boleh_disajikan(jalur) is True


@pytest.mark.parametrize("jalur", [
    "outbox.db", "license.db", "OUTBOX.DB", "license.db-wal", "license.db-shm",
    "outbox.db-journal", "upload_manifest.sqlite3", ".hapus-data", ".hapus-data.tmp",
    "results/.tersembunyi/x.webp", "results/../outbox.db", "", ".",
])
def test_basis_data_dan_berkas_tersembunyi_tidak_pernah(jalur):
    assert boleh_disajikan(jalur) is False
