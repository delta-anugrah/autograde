"""The published image name must not follow the repository name.

The factory PC pulls `ghcr.io/delta-anugrah/palmgrade-vision` — the name sits in
`/opt/palmgrade/vision/.env` on that machine, and the updater compares it against
the `:latest` marker under that same name. `IMAGE_NAME: ${{ github.repository }}`
was fine until the repo started being renamed to `autograde`: the next tag would
publish under the new name, the factory would keep asking for the old one, and
`palmgrade pull vision` would answer "already up to date" forever.

Nothing errors in that failure. This test is the only thing standing between a
one-word edit and a factory that silently stops receiving updates.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy.yml"
EXPECTED_IMAGE = "delta-anugrah/palmgrade-vision"
"""Moves only in Fase 5, together with a new compose file on the factory PC."""


def _env_block() -> dict:
    # `on:` parses as the boolean True in YAML 1.1, which is harmless here since
    # only `env` is read.
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["env"]


def test_the_published_image_name_is_pinned():
    assert _env_block()["IMAGE_NAME"] == EXPECTED_IMAGE


def test_the_image_name_does_not_follow_the_repository_name():
    assert not re.search(
        r"IMAGE_NAME:\s*\$\{\{\s*github\.repository\s*\}\}", WORKFLOW.read_text(encoding="utf-8")
    ), "renaming the repo would move the image and cut the factory PC off from updates"
