"""Startup must not create artifact folders that nothing ever writes to.

Two places declare the artifact layout: the app creates its folders on startup,
and the image pre-creates the same ones in the Dockerfile. Both drifted.
`captures/`, `errors/` and `logs/` kept being created long after the code stopped
writing to them — REJ images are found through `ripeness_status` metadata and logs
go to stdout for Docker — so every machine grew three empty folders that looked
like they held something, and the only way to tell was to read three files at once.

These tests read the sources as text on purpose: importing `main.py` pulls in torch
and cv2, which the unit suite deliberately runs without.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src" / "palmgrade"
MAIN_PY = SRC / "main.py"
DOCKERFILE = REPO_ROOT / "Dockerfile"

# Declare-only files: they name the folders, they do not put anything in them.
_DECLARING_FILES = {"main.py", "config.py"}

_STARTUP_LIST = re.compile(r"for folder in \[(?P<items>[^\]]*)\]")
_STARTUP_MKDIR = re.compile(r"settings\.(\w+)_dir\.mkdir")
_SETTINGS_DIR = re.compile(r"settings\.(\w+)_dir")


def _startup_folders() -> set[str]:
    """Folders startup creates, written either as a loop over a list or one by one."""
    source = MAIN_PY.read_text(encoding="utf-8")
    folders = set(_STARTUP_MKDIR.findall(source))
    for match in _STARTUP_LIST.finditer(source):
        folders |= set(_SETTINGS_DIR.findall(match.group("items")))
    assert folders, "startup no longer creates any artifact folder — update this test"
    return folders


def _dockerfile_folders() -> set[str]:
    for line in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        if "mkdir -p artifacts/" in line:
            return {part.split("/", 1)[1] for part in line.split() if part.startswith("artifacts/")}
    raise AssertionError("Dockerfile no longer pre-creates the artifact folders")


def _writers_of(folder: str) -> list[str]:
    """Files that use the folder for something beyond declaring and creating it."""
    needle = f"{folder}_dir"
    return [
        path.name
        for path in SRC.rglob("*.py")
        if path.name not in _DECLARING_FILES and needle in path.read_text(encoding="utf-8")
    ]


def test_startup_only_creates_folders_something_writes_to():
    orphans = sorted(folder for folder in _startup_folders() if not _writers_of(folder))
    assert not orphans, (
        f"created on startup but nothing writes there: {orphans}. "
        "Drop each one from main.py, config.py and the Dockerfile."
    )


def test_the_image_precreates_the_same_folders_as_startup():
    assert _dockerfile_folders() == _startup_folders(), (
        "the Dockerfile and startup disagree about the artifact layout; "
        "a folder created in only one of them exists on some machines and not others"
    )
