from __future__ import annotations

import pytest

from palmgrade.domain.rahasia import rahasia_cocok


def test_sama_persis_cocok():
    assert rahasia_cocok("kunci-palsu-1", "kunci-palsu-1") is True


@pytest.mark.parametrize("diberikan", [None, "", "kunci-palsu-2", "kunci-palsu-1 ", "KUNCI-PALSU-1"])
def test_selain_itu_ditolak(diberikan):
    assert rahasia_cocok(diberikan, "kunci-palsu-1") is False


@pytest.mark.parametrize("diberikan", [None, ""])
def test_secret_kosong_di_server_tidak_pernah_membuka_lane(diberikan):
    """`hmac.compare_digest("", "")` bernilai True. `WEBHOOK_SECRET=` di .env tidak
    boleh berarti siapa pun tanpa header lolos."""
    assert rahasia_cocok(diberikan, "") is False


def test_bukan_ascii_tidak_melempar():
    assert rahasia_cocok("kunci-é", "kunci-e") is False
