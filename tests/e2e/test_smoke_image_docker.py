"""End-to-end: `scripts/smoke_image.py` against a real built image (batch 4.2).

Skipped unless E2E_IMAGE names a built image and E2E_IMAGE_VERSION / E2E_IMAGE_LABEL say
what it should report, for example:

    docker build --build-arg TORCH_VARIANT=cpu --build-arg WITH_SDK=false \\
        --build-arg APP_VERSION=v0.0.1 --label org.opencontainers.image.version=v0.0.1-cpu \\
        -t autograde-smoke:good .
    E2E_IMAGE=autograde-smoke:good E2E_IMAGE_VERSION=v0.0.1 E2E_IMAGE_LABEL=v0.0.1-cpu \\
        pytest tests/e2e/test_smoke_image_docker.py -rs
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

IMAGE = os.getenv("E2E_IMAGE", "")
VERSION = os.getenv("E2E_IMAGE_VERSION", "")
LABEL = os.getenv("E2E_IMAGE_LABEL", "")
pytestmark = pytest.mark.skipif(
    not (IMAGE and VERSION and LABEL) or shutil.which("docker") is None,
    reason="E2E_IMAGE, E2E_IMAGE_VERSION, E2E_IMAGE_LABEL not set or no docker",
)

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "smoke_image.py"


def _smoke(version: str, label: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), IMAGE, "--version", version, "--label", label],
        capture_output=True,
        text=True,
        timeout=900,
    )


def _containers_of_image() -> list[str]:
    out = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"ancestor={IMAGE}", "--format", "{{.ID}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.split()


def test_image_yang_sehat_lulus_dan_tidak_meninggalkan_container():
    before = set(_containers_of_image())
    result = _smoke(VERSION, LABEL)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines()[:4] == ["ok   label", "ok   line", "ok   console", "ok   boot"]
    assert set(_containers_of_image()) == before


def test_versi_yang_tidak_cocok_ditolak_dan_container_dibuang():
    """Image yang sama, dicek dengan versi lain: harus gagal di /health, bukan lolos."""
    before = set(_containers_of_image())
    result = _smoke(VERSION + "9", LABEL)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FAIL boot: /health returned" in result.stderr
    assert set(_containers_of_image()) == before


def test_label_yang_tidak_cocok_ditolak_sebelum_container_dinyalakan():
    result = _smoke(VERSION, LABEL + "-salah")
    assert result.returncode == 1
    assert "FAIL label" in result.stderr
    assert "ok   line" not in result.stdout
