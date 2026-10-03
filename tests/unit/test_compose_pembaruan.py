"""Batch 4.6: the console must see the launcher's folder, and only the console.

Read as text, not `docker compose config`: the factory's Compose 2.40.3 replaces an
`environment:` block the Mac's 5.5.1 merges (sawit CLAUDE.md trap 2026-09-20), so what
matters is what each file literally says.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
BERKAS = ("docker-compose.prod.yml", "docker-compose.yml")


def _layanan(berkas: str) -> dict:
    teks = (ROOT / berkas).read_text().replace("!override", "")
    return yaml.safe_load(teks)["services"]


@pytest.mark.parametrize("berkas", BERKAS)
def test_konsol_punya_folder_pembaruan_yang_bisa_ditulis(berkas):
    konsol = _layanan(berkas)["console"]
    assert "./update:/app/update" in konsol["volumes"]
    assert "UPDATE_DIR=${UPDATE_DIR:-/app/update}" in konsol["environment"]


@pytest.mark.parametrize("berkas", BERKAS)
def test_line_tidak_mendapat_folder_pembaruan(berkas):
    for nama, isi in _layanan(berkas).items():
        if nama != "console":
            assert not any("update" in str(v) for v in isi.get("volumes", [])), nama


@pytest.mark.parametrize("berkas", BERKAS)
def test_konsol_tidak_pernah_dapat_socket_docker(berkas):
    for nama, isi in _layanan(berkas).items():
        assert not any("docker.sock" in str(v) for v in isi.get("volumes", [])), nama
