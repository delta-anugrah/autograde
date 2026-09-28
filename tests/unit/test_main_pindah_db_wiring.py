"""`main.py` (app line): penyerapan DB lama dijaga sebagai teks.

`main.py` menarik torch, jadi urutan boot-nya dipatok seperti
`test_main_bahaya_wiring.py`. Yang gagal senyap kalau urutannya salah: store
yang sudah membuka berkasnya sebelum penyerapan (dua antrean hidup
berdampingan), atau penyerapan sebelum hapus-saat-boot (data yang diminta
dihapus malah dipindah ke tempat yang tidak dihapus).
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "palmgrade"
MAIN = (SRC / "main.py").read_text(encoding="utf-8")
LIFESPAN = MAIN.split("async def lifespan(app: FastAPI):", 1)[1]


def test_pindah_sesudah_hapus_sebelum_lisensi_dan_worker():
    i_pindah = LIFESPAN.index("await pindahkan_db_lama(")
    assert LIFESPAN.index("hapus_kalau_diminta(") < i_pindah
    for sesudah in ("_lic_manager.init()", "CaptureSaveWorker(", "OutboxRetryWorker("):
        assert i_pindah < LIFESPAN.index(sesudah), sesudah


def test_outbox_dan_lisensi_satu_folder_db():
    assert 'get_folder_db_line() / "outbox.db"' in (SRC / "core" / "dependencies.py").read_text()
    assert 'get_folder_db_line() / "license.db"' in MAIN


def test_tidak_ada_lagi_db_line_yang_dibuka_di_artifacts():
    for berkas in SRC.rglob("*.py"):
        assert not re.search(r'artifacts_dir\s*/\s*"[a-z_]+\.db"', berkas.read_text(encoding="utf-8")), berkas


def test_health_membandingkan_folder_db_yang_sama():
    """`/health/detail` mencari sisa `artifacts/outbox.db` terhadap folder DB yang
    SAMA dengan yang dipakai outbox; folder lain = sisa yang tidak terlihat."""
    deps = (SRC / "core" / "dependencies.py").read_text(encoding="utf-8")
    blok = deps.split("def get_health_service()", 1)[1].split("\ndef ", 1)[0]
    assert "folder_db=get_folder_db_line()" in blok
