"""Every repo path a live document names must exist.

Documents get deleted once nothing uses them. The risk is the one page that still points at
the deleted file: a reader who follows a dead path stops trusting the rest of that page, and
an agent reads it as an instruction to go study something that is not there.

Scope is what people and agents are actually sent to read — README, CLAUDE.md, docs/, folder
READMEs and the repo's skills. Paths that leave the repo (`../autoerp/...`, the sawit
workspace) belong to someone else and are skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# `docs/overview.md`, `config/camera/hikrobot.mfs` — written from the repo root. The
# look-behind keeps `sawit/docs/...` and `../docs/...` (other repos) out.
_ROOT_PATH = re.compile(r"(?<![\w./-])((?:docs|config)/[\w./-]+\.(?:md|mfs))")
# [label](SETUP.md), [label](../config/camera/hikrobot.mfs) — relative to the document.
_LINK = re.compile(r"\]\((?!https?:|mailto:|#)([^)\s#]+)")


def _live_docs() -> list[Path]:
    docs = [REPO_ROOT / "README.md", REPO_ROOT / "CLAUDE.md"]
    docs += sorted((REPO_ROOT / "docs").rglob("*.md"))
    docs += sorted((REPO_ROOT / "config").rglob("README.md"))
    docs += sorted((REPO_ROOT / ".claude" / "skills").rglob("SKILL.md"))
    return [doc for doc in docs if doc.is_file()]


def _inside_repo(path: Path) -> bool:
    return path == REPO_ROOT or REPO_ROOT in path.parents


def _dangling(doc: Path) -> list[str]:
    text = doc.read_text(encoding="utf-8")
    missing = {rel for rel in _ROOT_PATH.findall(text) if not (REPO_ROOT / rel).exists()}
    for rel in _LINK.findall(text):
        target = (doc.parent / rel).resolve()
        if _inside_repo(target) and not target.exists():
            missing.add(rel)
    return sorted(missing)


def test_live_docs_only_name_paths_that_exist():
    broken = {
        str(doc.relative_to(REPO_ROOT)): missing
        for doc in _live_docs()
        if (missing := _dangling(doc))
    }
    assert not broken, f"documents point at paths that do not exist: {broken}"


def test_the_scan_actually_reads_documents():
    # Guards the guard: a glob that silently matched nothing would pass forever.
    names = {doc.name for doc in _live_docs()}
    assert {"README.md", "CLAUDE.md", "overview.md"} <= names
