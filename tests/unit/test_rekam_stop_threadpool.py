"""`POST /internal/rekam/stop` jalan di threadpool, bukan di event loop line.

`routes/internal.py` menarik torch, jadi dijaga sebagai AST di sini (jalan di CI);
perilakunya diuji di `tests/e2e/test_rekam_lane.py::test_stop_tidak_membekukan_event_loop_line`.
`VideoRecorder.stop()` menguras antrean encoder (paling banyak 30 frame) dan menunggu
thread-nya: sebagai `async def`, selama itu `/health`, MJPEG, dan perintah konsol lain
di line itu tidak dijawab.
"""
from __future__ import annotations

import ast
from pathlib import Path

INTERNAL = Path(__file__).resolve().parents[2] / "src" / "palmgrade" / "routes" / "internal.py"


def test_rekam_stop_bukan_async_def():
    fungsi = {
        n.name: n for n in ast.parse(INTERNAL.read_text(encoding="utf-8")).body
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    assert isinstance(fungsi["rekam_stop"], ast.FunctionDef)
