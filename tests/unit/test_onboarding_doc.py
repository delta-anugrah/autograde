"""docs/ONBOARDING.md is printed into the office's official PDF — these are the inputs it needs.

The PDF build reads document-control fields from the front matter for the cover and the running
header, swaps each ```diagram:<name> block for `docs/assets/onboarding/<name>.svg`, and numbers
the table of contents from the `## N.` headings. A missing field prints an empty cover line, a
missing SVG prints nothing where the figure should be, and a skipped number reads like a lost
page. None of those fail the build, so they are pinned here, where CI can see them without Chrome.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "ONBOARDING.md"
ASSETS = REPO_ROOT / "docs" / "assets" / "onboarding"

DOCUMENT_CONTROL = {"judul", "subjudul", "label", "versi", "tanggal", "klasifikasi", "pemilik"}


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def _front_matter() -> dict[str, str]:
    match = re.match(r"\A---\n(.*?)\n---\n", _text(), re.S)
    assert match, "ONBOARDING.md must open with a --- front matter block"
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip('"')
    return fields


def test_front_matter_carries_every_document_control_field():
    fields = _front_matter()
    missing = sorted(key for key in DOCUMENT_CONTROL if not fields.get(key))
    assert not missing, f"front matter is missing or empty: {missing}"


def test_every_diagram_block_has_its_svg():
    names = re.findall(r"^```diagram:([\w-]+)", _text(), re.M)
    assert names, "the guide should draw its architecture, not only describe it"
    missing = sorted(name for name in names if not (ASSETS / f"{name}.svg").is_file())
    assert not missing, f"diagram blocks without docs/assets/onboarding/<name>.svg: {missing}"


def test_numbered_sections_run_one_to_n_without_gaps():
    numbers = [int(n) for n in re.findall(r"^## (\d+)\. ", _text(), re.M)]
    assert numbers == list(range(1, len(numbers) + 1)), f"section numbers skip or repeat: {numbers}"
