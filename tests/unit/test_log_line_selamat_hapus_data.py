"""Hapus data Danger Zone tidak menyentuh log line (batch 3.2).

Berkasnya sudah dibuka sejak proses line mulai (`pasang_log_line` di `create_app`),
jauh sebelum hapus-saat-boot jalan di lifespan: SQLite yang terbuka tidak boleh
dihapus dari bawah prosesnya. Kejadian yang ditulis tepat sebelum line keluar untuk
menghapus datanya juga justru yang dicari support sesudahnya.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from palmgrade.repositories.log_line_repository import LogLineStore
from palmgrade.services.hapus_data_line import hapus_kalau_diminta, tulis_penanda


def _folder(root: Path) -> tuple[Path, Path]:
    artifacts, state = root / "artifacts", root / "state"
    (artifacts / "results").mkdir(parents=True)
    state.mkdir()
    return artifacts, state


@pytest.mark.parametrize("mode", ["transaksi", "semua"])
def test_log_line_di_state_selamat(tmp_path, mode):
    artifacts, state = _folder(tmp_path)
    store = LogLineStore(state / "log_line.db")
    store.write("ERROR", "a", "sebelum hapus", None, now=1.0)
    tulis_penanda(artifacts, mode=mode, diminta_oleh="s@pks.id", now=1.0)

    hapus_kalau_diminta(artifacts, state, folder_db=state)

    assert (state / "log_line.db").exists()
    sesudah = LogLineStore(state / "log_line.db")
    assert sesudah.generasi == store.generasi
    assert [e["message"] for e in sesudah.ambil(setelah=0, generasi=store.generasi, batas=10)["entri"]] == [
        "sebelum hapus"
    ]


def test_log_line_di_artifacts_selamat_saat_state_tidak_di_mount(tmp_path):
    """Compose host tanpa `./state/line-N`: folder DB line = artifacts/, dan hapus data
    mengosongkan artifacts/ kecuali berkas yang selamat."""
    artifacts, state = _folder(tmp_path)
    LogLineStore(artifacts / "log_line.db").write("ERROR", "a", "x", None, now=1.0)
    tulis_penanda(artifacts, mode="semua", diminta_oleh="s@pks.id", now=1.0)

    hapus_kalau_diminta(artifacts, state, folder_db=artifacts)

    sisa = {p.name for p in artifacts.iterdir()}
    assert "log_line.db" in sisa
    assert "results" not in sisa
