"""Konsol menunggu line mati lebih lama dari urutan tutup line (batch 2.2).

Sejak batch 2.2 line tidak lagi `os._exit` sedetik sesudah menjawab
`/internal/hapus-data`: dia mematikan coil dan menghabiskan antrean simpan dulu,
maksimal `BATAS_TUTUP_S`. Janjang yang ditulis selama itu masih dikirim ke
konsol, jadi konsol yang berhenti menunggu lebih cepat akan mengosongkan
index-nya lalu menerima baris yang fotonya segera dihapus (aturan 25).
"""
from __future__ import annotations

import inspect

from palmgrade.routes.internal_bahaya import JEDA_KELUAR_DETIK
from palmgrade.services.bahaya_service import BahayaService
from palmgrade.services.penutup_line import BATAS_SEBELUM_KELUAR_S, BATAS_TUTUP_S


def test_batas_tunggu_mati_bawaan_menutup_jeda_dan_batas_tutup_line():
    """Batch 3.2 menambah `BATAS_SEBELUM_KELUAR_S` (menguras log line sebelum `os._exit`)
    di ujung jalan keluar yang sama: batas itu ikut dijumlah, supaya perubahan yang
    memakan cadangan tunggu Danger Zone langsung merah di sini."""
    bawaan = inspect.signature(BahayaService.__init__).parameters["tunggu_mati_s"].default
    # +1 detik: dua pemeriksaan `/health` berturut-turut yang tidak dijawab.
    assert bawaan >= JEDA_KELUAR_DETIK + BATAS_TUTUP_S + BATAS_SEBELUM_KELUAR_S + 1.0
