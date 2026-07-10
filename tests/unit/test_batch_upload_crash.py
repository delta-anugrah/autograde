"""Simulasi mati listrik (spec §7.3): os._exit di tengah transisi state →
manifest tetap konsisten saat dibuka ulang (WAL + synchronous=FULL)."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

_CRASH_SCRIPT = """
import os, sys
from pathlib import Path
from palmgrade.integrations.upload.upload_manifest import UploadManifest

db = Path(sys.argv[1])
m = UploadManifest(db_path=db)
for i in range(3):
    m.upsert_item(f"results/d/{i}_auto_ripeness.json", event_id=f"e{i}",
                  image_path=f"captures/results/d/{i}.webp", r2_key=f"M/d/{i}.webp")
m.mark_image_uploaded(m.get_uploadable(limit=1)[0]["id"])
os._exit(1)  # mati listrik: tanpa cleanup, tanpa flush python
"""


def test_crash_mid_batch_no_partial_write(tmp_path):
    db = tmp_path / "m.db"
    env = {**os.environ, "PYTHONPATH": str(_REPO / "src")}
    proc = subprocess.run([sys.executable, "-c", _CRASH_SCRIPT, str(db)],
                          env=env, capture_output=True, text=True)
    assert proc.returncode == 1, proc.stderr

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT item_key, status FROM upload_items ORDER BY item_key").fetchall()
    # Semua transaksi yang commit sebelum crash selamat; tidak ada row setengah jadi.
    assert [r["status"] for r in rows] == ["image_uploaded", "pending", "pending"]
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
