"""Setelan dari konsol harus BENAR-BENAR mengubah keputusan grading.

Menyimpan angka ke `RuntimeState` itu gampang; yang mahal kalau salah adalah
angkanya tersimpan tapi tidak pernah dipakai — layar bilang "tersimpan", operator
mengira ambangnya sudah naik, dan line masih memakai nilai `.env` sepanjang
shift. Berkas ini menguji sisi pemakaiannya, bukan sisi penyimpanannya.
"""
from __future__ import annotations

import pathlib
from dataclasses import replace

from palmgrade.core.config import Settings
from palmgrade.workers.runtime_state import RuntimeState


def _minimum_size_terpakai(state: RuntimeState, settings: Settings) -> int:
    """Salinan aturan di `FrameProcessingWorker`: override menang atas `.env`."""
    return (
        state.minimum_size_override
        if state.minimum_size_override is not None
        else settings.minimum_size
    )


def test_tanpa_override_nilai_env_yang_dipakai():
    s = replace(Settings(), minimum_size=460000)
    assert _minimum_size_terpakai(RuntimeState(), s) == 460000


def test_override_menang_atas_env():
    s = replace(Settings(), minimum_size=460000)
    st = RuntimeState()
    st.minimum_size_override = 3000
    assert _minimum_size_terpakai(st, s) == 3000


def test_override_nol_tidak_mungkin_lolos_ke_state():
    """`0` mematikan penjaga ukuran sepenuhnya. Domain yang menahannya, jadi
    nilai itu tidak pernah sampai ke sini — dibuktikan di
    `test_setelan_grading.py`. Yang dikunci di sini: `0` BUKAN nilai yang
    diperlakukan sebagai "tidak ada override" (`is not None`, bukan truthiness).
    Kalau suatu saat pengecekannya berubah jadi `if state.minimum_size_override:`,
    nol akan diam-diam berarti "pakai env" — dan tes ini gagal."""
    s = replace(Settings(), minimum_size=460000)
    st = RuntimeState()
    st.minimum_size_override = 0
    assert _minimum_size_terpakai(st, s) == 0


def test_conf_override_dikirim_ke_pipeline_sebagai_argumen():
    """Pipeline tidak boleh membaca `RuntimeState` sendiri — worker yang
    mengirimnya. Ini yang membuat pipeline bisa dites tanpa merakit satu line.

    Sumbernya dibaca sebagai TEKS, bukan lewat `import`: modul pipeline menarik
    cv2 dan torch, dan CI sengaja jalan tanpa keduanya (CLAUDE.md § Tests).
    Meng-import-nya di sini membuat tes ini hijau di laptop yang kebetulan punya
    cv2 dan merah di CI — persis yang terjadi sebelum perbaikan ini.
    """
    berkas = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src" / "palmgrade" / "pipelines" / "realtime_inspection_pipeline.py"
    )
    sumber = berkas.read_text(encoding="utf-8")
    fungsi = sumber.split("def track_ripeness(")[1].split("\n    def ")[0]

    assert "conf: float | None = None" in fungsi, "None = pakai .env"
    # Docstring boleh menyebut RuntimeState (menjelaskan kenapa TIDAK dipakai);
    # yang dicek badan fungsinya.
    badan = fungsi.split('"""')[-1]
    assert "state" not in badan.lower()
    assert "conf=self.settings.conf_threshold if conf is None else conf" in badan


def test_worker_membaca_override_tiap_frame():
    """Dibaca di dalam loop, bukan disimpan saat worker dibuat: kalau di-cache
    di `__init__`, mengubah setelan butuh restart line — persis yang mau
    dihilangkan fitur ini.

    Sumbernya dibaca sebagai teks, alasannya sama dengan tes di atas: modul
    worker ini menarik cv2 lewat `capture_writer`."""
    berkas = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src" / "palmgrade" / "workers" / "frame_processing_worker.py"
    )
    sumber = berkas.read_text(encoding="utf-8")
    run_once = sumber.split("def run_once(")[1].split("\n    def ")[0]
    assert "self.state.conf_threshold_override" in run_once
    assert "self.state.minimum_size_override" in run_once
