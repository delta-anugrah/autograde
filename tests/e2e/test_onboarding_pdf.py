"""End-to-end: build docs/ONBOARDING.md into the official PDF, then read that PDF back.

Skipped unless headless Chrome, python-markdown and pypdf are all present — the CI runner has
none of them, and none is a runtime dependency. What it checks is what a reader actually gets:
a cover without page furniture, a contents page whose numbers match where each section really
starts, a bookmark per section, and "Halaman N dari M" on the pages after the cover.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "md_to_pdf.py"
DOC = REPO_ROOT / "docs" / "ONBOARDING.md"
_MAC_CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def _chrome() -> str | None:
    if _MAC_CHROME.exists():
        return str(_MAC_CHROME)
    for name in ("google-chrome", "chromium", "chromium-browser"):
        if found := shutil.which(name):
            return found
    return None


def _importable(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


pytestmark = pytest.mark.skipif(
    _chrome() is None or not _importable("markdown") or not _importable("pypdf"),
    reason="needs headless Chrome, python-markdown and pypdf",
)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _section_titles() -> list[str]:
    return re.findall(r"^## (\d+\. .+)$", DOC.read_text(encoding="utf-8"), re.M)


@pytest.fixture(scope="module")
def pdf(tmp_path_factory):
    import pypdf

    out = tmp_path_factory.mktemp("onboarding") / "onboarding.pdf"
    subprocess.run(
        [sys.executable, str(SCRIPT), str(DOC), str(out)],
        check=True,
        capture_output=True,
        timeout=180,
    )
    return pypdf.PdfReader(out)


@pytest.fixture(scope="module")
def bookmarks(pdf) -> dict[str, int]:
    marks: dict[str, int] = {}

    def walk(items):
        for item in items:
            if isinstance(item, list):
                walk(item)
            else:
                marks[_flat(item.title)] = pdf.get_destination_page_number(item) + 1

    walk(pdf.outline)
    return marks


def test_every_numbered_section_is_bookmarked(bookmarks):
    missing = [title for title in _section_titles() if title not in bookmarks]
    assert not missing, f"sections without a PDF bookmark: {missing}"


def test_the_contents_page_prints_where_each_section_really_starts(pdf, bookmarks):
    titles = _section_titles()
    first_section = min(bookmarks[title] for title in titles)
    front_matter = _flat(" ".join(pdf.pages[i].extract_text() for i in range(first_section - 1)))
    wrong = [
        title
        for title in titles
        if not re.search(re.escape(title) + r"\s*" + str(bookmarks[title]) + r"\b", front_matter)
    ]
    assert not wrong, f"contents page disagrees with where these sections start: {wrong}"


def test_the_cover_is_clean_and_the_pages_after_it_are_numbered(pdf):
    cover = _flat(pdf.pages[0].extract_text())
    assert "AutoGrade" in cover
    assert "Halaman" not in cover, "the cover must not carry the running footer"
    last = len(pdf.pages)
    assert f"Halaman {last} dari {last}" in _flat(pdf.pages[-1].extract_text())
