"""Buah REJ milik truk Internal tidak dibuang piston (§3.5b + permintaan Mas Samuel).

Hasil inference TIDAK diubah: yang hilang cuma pulse ke PLC. Kalau verdict ikut
diubah jadi ACC, rekap yang dibayar ikut bohong dan buktinya hilang.
"""
from __future__ import annotations

import pytest

from palmgrade.domain.plc_signal import plc_status_for


def test_rej_truk_internal_tidak_menghasilkan_pulse():
    assert plc_status_for("rej", "Internal") is None


def test_acc_truk_internal_tetap_menghasilkan_pulse():
    assert plc_status_for("acc", "Internal") == "acc"


@pytest.mark.parametrize("sumber", ["External", None])
def test_rej_selain_internal_tetap_dibuang(sumber):
    # Termasuk truk yang sumbernya belum jelas dan line tanpa truk: kalau ragu,
    # sortir normal.
    assert plc_status_for("rej", sumber) == "rej"


def test_huruf_besar_kecil_tidak_mengubah_keputusan():
    assert plc_status_for("REJ", "Internal") is None
    assert plc_status_for("Rej", "Internal") is None


def test_status_tak_dikenal_melempar_seperti_ingest():
    with pytest.raises(ValueError):
        plc_status_for("mentah", "Internal")
