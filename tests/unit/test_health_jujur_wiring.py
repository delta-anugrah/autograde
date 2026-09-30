"""Perakitan health jujur (batch 3.6 + 3.7) di tempat yang menarik torch, dijaga
sebagai TEKS (pola `test_ai_mati_wiring.py`): `main.py` dan
`internal_controller.line_status` tidak bisa dinyalakan di CI.

Yang gagal senyap kalau salah: pemantau disk tidak pernah dipasang (Diagnostik
dan alert disk kosong selamanya), atau `/internal/status` tidak membawa `disk`.
"""
from __future__ import annotations

from pathlib import Path

from palmgrade.schemas.internal_schema import LineStatusResponse

SRC = Path(__file__).resolve().parents[2] / "src" / "palmgrade"
LIFESPAN = (SRC / "main.py").read_text(encoding="utf-8").split("async def lifespan(app: FastAPI):", 1)[1]


def test_pemantau_disk_dirakit_di_lifespan_untuk_foto_dan_db():
    i = LIFESPAN.index("state.pemantau_disk = PemantauDisk(")
    assert LIFESPAN.index("state = get_runtime_state()") < i
    blok = LIFESPAN[i : LIFESPAN.index(")", LIFESPAN.index("jalur=", i)) + 1]
    assert "settings.artifacts_dir" in blok and "get_folder_db_line()" in blok


def test_status_line_membawa_blok_disk():
    kontrol = (SRC / "controllers" / "internal_controller.py").read_text(encoding="utf-8")
    fungsi = kontrol.split("async def line_status(", 1)[1]
    assert "disk=ringkas_disk_dari_state(state)" in fungsi


def test_skema_status_line_menerima_disk_dan_bawaannya_none():
    assert LineStatusResponse(machine_id="m", truck_id=None, ffb_source=None, piston=None).disk is None
