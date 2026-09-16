"""`capture_writer` copies one constant instead of importing it. Keep them equal.

`core/constants.py` imports cv2 at module level, and the unit suite runs without
cv2 on purpose (CLAUDE.md § Tests) — importing it there would drag the entire
capture path out of CI. The copy is the lesser evil, but a silent drift would
mean the two save paths encode at different qualities, which nobody would notice
until comparing file sizes months later.

Read as text, never imported: importing `core.constants` is the very thing this
guard exists to avoid.
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "palmgrade"


def _int_constant(path: Path, name: str) -> int:
    match = re.search(rf"^{name}\s*=\s*(\d+)", path.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, f"{name} not found in {path.name} — update this guard with the rename"
    return int(match.group(1))


def test_the_writer_encodes_at_the_documented_save_quality() -> None:
    assert _int_constant(SRC / "services" / "capture_writer.py", "_SAVE_QUALITY") == _int_constant(
        SRC / "core" / "constants.py", "JPEG_QUALITY_SAVE"
    )
