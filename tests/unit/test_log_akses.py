"""Saring access log polling (batch 3.3): yang dibisukan cuma polling yang BERHASIL.

Mahal kalau salah dua arah: tidak disaring = ±86 ribu baris per hari per line dan
permintaan penting tenggelam; disaring berlebihan = `/health` yang menjawab 503 atau
`/internal/status` yang ditolak kuncinya hilang dari log, padahal itu yang dicari.
"""
from __future__ import annotations

import logging

import pytest

from palmgrade.core.log_akses import JALUR_POLLING_SENYAP, SaringAksesPolling, polling_sukses


def _args(jalur: str, status: int, metode: str = "GET") -> tuple:
    """Bentuk argumen access log uvicorn (`h11_impl`/`httptools_impl`)."""
    return ("127.0.0.1:50000", metode, jalur, "1.1", status)


@pytest.mark.parametrize("jalur", sorted(JALUR_POLLING_SENYAP))
def test_setiap_jalur_polling_yang_sukses_dibisukan(jalur):
    assert polling_sukses(_args(jalur, 200)) is True


@pytest.mark.parametrize("status", [304, 399])
def test_jawaban_di_bawah_400_dianggap_sukses(status):
    assert polling_sukses(_args("/health", status)) is True


def test_query_string_tidak_membuat_polling_lolos():
    assert polling_sukses(_args("/api/console/state?t=123", 200)) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 503])
def test_galat_di_jalur_polling_tetap_tertulis(status):
    assert polling_sukses(_args("/internal/status", status)) is False


def test_head_ikut_dibisukan_post_tidak():
    assert polling_sukses(_args("/health", 200, "HEAD")) is True
    assert polling_sukses(_args("/api/console/weighings", 200, "POST")) is False


@pytest.mark.parametrize("jalur", ["/internal/assignment", "/api/console/login", "/health/", "/healthz", "/"])
def test_jalur_lain_tetap_tertulis(jalur):
    assert polling_sukses(_args(jalur, 200)) is False


@pytest.mark.parametrize(
    "args",
    [None, (), ("a", "GET", "/health", "1.1"), ("a", "GET", "/health", "1.1", "200"), ("a", 1, "/health", "1.1", 200)],
)
def test_bentuk_asing_dianggap_bukan_polling(args):
    """Kalau uvicorn mengubah bentuk argumennya, lebih baik satu baris berlebih
    daripada baris penting yang hilang."""
    assert polling_sukses(args) is False


def test_filter_logging_membuang_polling_meneruskan_sisanya():
    saring = SaringAksesPolling()

    def rekam(args):
        return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', args, None)

    assert saring.filter(rekam(_args("/internal/status", 200))) is False
    assert saring.filter(rekam(_args("/internal/status", 500))) is True
    assert saring.filter(rekam(_args("/internal/restart", 200, "POST"))) is True
