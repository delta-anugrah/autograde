"""The coding standard reaches every session, and the review checklist cites rules that exist.

`docs/coding-standard.md` is pulled into every Claude Code session by one import line in
`CLAUDE.md`. Claude Code skips an import it cannot resolve without a word, and it never reads an
import written inside a code span, so a renamed file or a line wrapped in backticks would drop the
whole standard in silence. `rule-reviewer` walks `docs/REVIEW-CHECKLIST.md` section E, which cites
the standard by rule id; an id that no longer exists sends the reviewer to a rule that is not there.
The standard also names code paths (`routes/console.py`, `domain/`), which `test_doc_links.py` does
not check; a renamed module would leave a rule pointing at nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CODE_ROOT = REPO_ROOT / "src" / "palmgrade"
STANDARD = REPO_ROOT / "docs" / "coding-standard.md"
CHECKLIST = REPO_ROOT / "docs" / "REVIEW-CHECKLIST.md"
IMPORT_LINE = "@docs/coding-standard.md"
# Loaded into every session, so it stays short; the why lives in docs/rules.md and overview.md.
MAX_LINES = 120

_DEFINED_ID = re.compile(r"^- \*\*([LSBFTCD]\d{1,2})\.\*\*", re.MULTILINE)
_CITED_ID = re.compile(r"\b([LSBFTCD]\d{1,2})\b")
_INLINE_CODE = re.compile(r"(`+)(?:(?!\1).)+?\1")
_CODE_SPAN = re.compile(r"`([^`\n]+)`")
# A file with a known extension, or a folder ending in "/"; URLs, globs and templates never match.
_PATH = re.compile(r"(?:[\w.-]+/)*[\w.-]+\.(?:py|html|md|yml|toml|txt)|(?:[\w.-]+/)+")


def _outside_code(text: str) -> str:
    """What Claude Code scans for imports: no fenced blocks, no inline code spans."""
    kept, fenced = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            kept.append(_INLINE_CODE.sub("", line))
    return "\n".join(kept)


def _defined_ids() -> list[str]:
    return _DEFINED_ID.findall(STANDARD.read_text(encoding="utf-8"))


def _named_paths(text: str) -> list[str]:
    """Code spans that are paths in this repo, written from the root or from `src/palmgrade/`."""
    spans = _CODE_SPAN.findall(text)
    return [span for span in spans if _PATH.fullmatch(span) and not span.startswith("autoerp/")]


def _missing(paths: list[str]) -> list[str]:
    return [p for p in paths if not ((REPO_ROOT / p).exists() or (CODE_ROOT / p).exists())]


def _checklist_section_e() -> str:
    text = CHECKLIST.read_text(encoding="utf-8")
    match = re.search(r"^## E\..*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "docs/REVIEW-CHECKLIST.md has no section E for the coding standard"
    return match.group(0)


def test_claude_md_imports_the_standard_outside_code():
    claude_md = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert IMPORT_LINE in _outside_code(claude_md)


def test_the_standard_stays_short_enough_to_load_every_session():
    lines = STANDARD.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= MAX_LINES, f"{len(lines)} lines; keep it at {MAX_LINES} or fewer"


def test_every_rule_id_is_defined_once():
    ids = _defined_ids()
    assert len(ids) >= 30, "the rule list was not found; the scan matches nothing"
    duplicates = sorted({rule for rule in ids if ids.count(rule) > 1})
    assert not duplicates, f"rule ids defined twice: {duplicates}"


def test_every_path_the_standard_names_exists():
    paths = _named_paths(STANDARD.read_text(encoding="utf-8"))
    assert len(paths) >= 15, "the path scan found almost nothing; the pattern no longer matches"
    assert not _missing(paths), f"the standard names paths that do not exist: {_missing(paths)}"


def test_the_path_scan_reports_a_path_that_does_not_exist():
    # Guards the guard: a scan that silently skipped every path would pass forever.
    text = "`routes/no_such_module.py`, `domain/`, `autoerp/docs/x.md`, `/api/console/trucks`"
    assert _missing(_named_paths(text)) == ["routes/no_such_module.py"]


def test_checklist_cites_only_rules_the_standard_defines():
    cited = set(_CITED_ID.findall(_checklist_section_e()))
    assert len(cited) >= 5, "section E cites no rule ids; the scan matches nothing"
    unknown = sorted(cited - set(_defined_ids()))
    assert not unknown, f"section E cites rules the standard does not define: {unknown}"
