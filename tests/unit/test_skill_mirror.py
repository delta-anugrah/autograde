"""Every repo skill is visible to Codex through `.agents/skills/`.

Claude Code reads skills from `.claude/skills/`. Codex looks in `.agents/skills/`, where each entry
is a symlink back to the real folder, so there is still only one copy to edit. A skill added
without its symlink is invisible to Codex and nothing says so: three skills went unmirrored for
weeks (`docs/PROGRESS.md`, follow-up 3 of PR #196).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS = REPO_ROOT / ".claude" / "skills"
MIRROR = REPO_ROOT / ".agents" / "skills"


def _skills() -> list[str]:
    return sorted(path.name for path in SKILLS.iterdir() if (path / "SKILL.md").is_file())


def test_the_scan_finds_the_skills():
    # Guards the guard: a scan that found nothing would pass forever.
    assert len(_skills()) >= 5


def test_every_skill_has_a_mirror_that_links_back():
    problems = []
    for name in _skills():
        link = MIRROR / name
        if not link.is_symlink():
            problems.append(f"{name}: missing, run  ln -s ../../.claude/skills/{name} .agents/skills/{name}")
        elif link.resolve() != (SKILLS / name).resolve():
            problems.append(f"{name}: points at {link.resolve()}")
    assert not problems, problems


def test_the_mirror_holds_only_links_to_skills():
    strays = [path.name for path in MIRROR.iterdir() if not (path.is_symlink() and (path / "SKILL.md").is_file())]
    assert not strays, f"entries in .agents/skills that are not links to a skill: {strays}"
