#!/usr/bin/env python3
"""Print a Markdown document as an official internal PDF.

    scripts/md_to_pdf.py docs/ONBOARDING.md                → docs/ONBOARDING.pdf
    scripts/md_to_pdf.py docs/ONBOARDING.md /tmp/out.pdf

The look follows the office's existing internal documents (sawit/docs/onboarding/build-pdf.py):
full-colour cover, a front page, every section starting on a new page. On top of that it adds
what an official document needs and that build does not have: document control read from the
front matter, a running header plus a "Halaman N dari M" footer, a contents page with real page
numbers, PDF bookmarks, and drawn diagrams in place of ASCII art.

It prints twice because Chrome cannot resolve `target-counter()`: the first print exists only to
read back, from its bookmarks, the page each heading landed on; the second prints those numbers.

Needs headless Chrome plus `pip install markdown pypdf` — tooling only, not runtime dependencies.
"""

from __future__ import annotations

import argparse
import html
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import markdown
    import pypdf
except ImportError:
    sys.exit("Butuh python-markdown dan pypdf: pip install markdown pypdf")

REPO_ROOT = Path(__file__).resolve().parents[1]
_MAC_CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

ACCENT = "#134e5e"
ACCENT_LIGHT = "#1f7a8c"
PANEL = "#eef5f6"
COVER_DIM = "#9cc3cc"
COVER_SOFT = "#c9e0e5"
COVER_RULE = "#2f6d7c"
FONT = "'Noto Sans', 'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "'JetBrains Mono', 'SF Mono', Menlo, 'DejaVu Sans Mono', monospace"

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_DIAGRAM = re.compile(r"^```diagram:([\w-]+)[ \t]*([^\n]*)\n.*?^```[ \t]*$", re.M | re.S)
_HEADING = re.compile(r"<h([23])>(.*?)</h\1>", re.S)


# ---------------------------------------------------------------- source ---------------


def split_front_matter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONT_MATTER.match(text)
    if not match:
        sys.exit("Dokumen harus diawali blok front matter --- (judul, versi, tanggal, ...)")
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip('"')
    return fields, text[match.end():]


def drop_title(body: str) -> str:
    # The cover prints the title; a second H1 would only repeat it.
    return re.sub(r"\A\s*#\s+[^\n]*\n", "", body, count=1)


def extract_diagrams(body: str, assets: Path) -> tuple[str, list[str]]:
    """Swap each ```diagram:<name> block for a placeholder and render its SVG as a figure.

    The Markdown keeps the ASCII version on purpose: agents and plain-text readers get a picture
    they can read, while the PDF gets the drawn one.
    """
    figures: list[str] = []

    def swap(match: re.Match) -> str:
        name, caption = match.group(1), match.group(2).strip()
        svg_path = assets / f"{name}.svg"
        if not svg_path.is_file():
            sys.exit(f"Diagram '{name}' tidak punya berkas {svg_path}")
        number = len(figures) + 1
        caption_html = f"Gambar {number}. {html.escape(caption)}" if caption else f"Gambar {number}"
        figures.append(
            f'<figure class="diagram">{svg_path.read_text(encoding="utf-8")}'
            f"<figcaption>{caption_html}</figcaption></figure>"
        )
        return f"\n\nXDIAGRAMX{number - 1}X\n\n"

    return _DIAGRAM.sub(swap, body), figures


def render_body(body: str, figures: list[str]) -> tuple[str, list[tuple[int, str, str]]]:
    """Markdown → HTML, figures put back, and every H2/H3 given an anchor for the contents."""
    out = markdown.markdown(body, extensions=["tables", "fenced_code", "sane_lists", "attr_list"])
    for index, figure in enumerate(figures):
        out = out.replace(f"<p>XDIAGRAMX{index}X</p>", figure)

    headings: list[tuple[int, str, str]] = []
    used: set[str] = set()

    def anchor(match: re.Match) -> str:
        level, inner = int(match.group(1)), match.group(2)
        text = _plain(inner)
        slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "bagian"
        while slug in used:
            slug += "-"
        used.add(slug)
        headings.append((level, slug, text))
        return f'<h{level} id="{slug}">{inner}</h{level}>'

    out = _HEADING.sub(anchor, out)
    out = re.sub(r"<p>(⚠️.*?)</p>", r'<div class="warn">\1</div>', out, flags=re.S)
    return out, headings


def _plain(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


# ---------------------------------------------------------------- layout ---------------


def _css_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _short_classification(fields: dict[str, str]) -> str:
    return fields["klasifikasi"].split("—")[0].strip().upper()


def stylesheet(fields: dict[str, str]) -> str:
    tokens = {
        "HEADER_LEFT": _css_string(fields["judul"]),
        "HEADER_RIGHT": _css_string(_short_classification(fields)),
        "FOOTER_LEFT": _css_string(f"Versi {fields['versi']} · {fields['tanggal']}"),
        "ACCENT_LIGHT": ACCENT_LIGHT,
        "ACCENT": ACCENT,
        "PANEL": PANEL,
        "COVER_DIM": COVER_DIM,
        "COVER_SOFT": COVER_SOFT,
        "COVER_RULE": COVER_RULE,
        "FONT": FONT,
        "MONO": MONO,
    }
    css = _CSS
    for key, value in tokens.items():
        css = css.replace(f"%%{key}%%", value)
    return css


def cover(fields: dict[str, str]) -> str:
    columns = []
    for chunk in filter(None, (c.strip() for c in fields.get("sorotan", "").split(";"))):
        label, _, items = chunk.partition("=")
        columns.append(f"<div><b>{html.escape(label.strip())}</b>{html.escape(items.strip())}</div>")
    e = html.escape
    return f"""
<section class="cover">
  <div class="band"></div>
  <div class="eyebrow">{e(fields["label"])}</div>
  <div class="title">{e(fields["judul"])}</div>
  <p class="sub">{e(fields["subjudul"])}</p>
  <div class="highlights">{"".join(columns)}</div>
  <div class="meta">
    <span>Versi <b>{e(fields["versi"])}</b> &nbsp;·&nbsp; <b>{e(fields["tanggal"])}</b>
      &nbsp;·&nbsp; {e(fields["pemilik"])}</span>
    <span class="badge">{e(_short_classification(fields))}</span>
  </div>
</section>"""


def front_page(fields: dict[str, str], source: str, headings, pages: dict[str, int]) -> str:
    e = html.escape
    info = [
        ("Judul", fields["judul"]),
        ("Versi", fields["versi"]),
        ("Tanggal", fields["tanggal"]),
        ("Klasifikasi", fields["klasifikasi"]),
        ("Pemilik", fields["pemilik"]),
        ("Naskah sumber", source),
    ]
    info_rows = "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in info)
    toc_rows = "".join(
        f'<li class="l{level}"><a href="#{slug}"><span class="t">{e(text)}</span>'
        f'<span class="dots"></span><span class="n">{pages.get(slug, "")}</span></a></li>'
        for level, slug, text in headings
    )
    return f"""
<section class="front">
  <div class="heading">Informasi Dokumen</div>
  <table class="docinfo"><tbody>{info_rows}</tbody></table>
  <div class="heading">Daftar Isi</div>
  <ol class="toc">{toc_rows}</ol>
</section>"""


def document(fields, source, body_html, headings, pages) -> str:
    return f"""<!doctype html>
<html lang="id"><head><meta charset="utf-8">
<title>{html.escape(fields["judul"])}</title>
<style>{stylesheet(fields)}</style></head>
<body>
{cover(fields)}
{front_page(fields, source, headings, pages)}
<main class="body">
{body_html}
<p class="end">— Akhir dokumen —</p>
</main>
</body></html>"""


# ---------------------------------------------------------------- printing -------------


def chrome_binary() -> str:
    if _MAC_CHROME.exists():
        return str(_MAC_CHROME)
    for name in ("google-chrome", "chromium", "chromium-browser"):
        if found := shutil.which(name):
            return found
    sys.exit("Chrome/Chromium tidak ditemukan — itu yang mencetak PDF-nya.")


def print_pdf(chrome: str, page: Path, out: Path) -> None:
    out.unlink(missing_ok=True)
    command = [
        chrome,
        "--headless",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--generate-pdf-document-outline",
        f"--print-to-pdf={out}",
        page.as_uri(),
    ]
    if platform.system() == "Linux":
        command.insert(1, "--no-sandbox")
    subprocess.run(command, check=True, capture_output=True, timeout=120)
    if not out.is_file():
        sys.exit(f"Chrome selesai tanpa menulis {out}")


def heading_pages(pdf: Path, headings) -> dict[str, int]:
    """Where each heading landed, read from the bookmarks Chrome wrote for it."""
    reader = pypdf.PdfReader(pdf)
    by_title: dict[str, list[int]] = {}

    def walk(items) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item)
            else:
                title = re.sub(r"\s+", " ", item.title).strip()
                by_title.setdefault(title, []).append(reader.get_destination_page_number(item) + 1)

    walk(reader.outline)
    pages = {}
    for _level, slug, text in headings:
        if by_title.get(text):
            pages[slug] = by_title[text].pop(0)
        else:
            print(f"peringatan: '{text}' tidak ada di bookmark PDF", file=sys.stderr)
    return pages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    args = parser.parse_args()

    source = args.source.resolve()
    output = (args.output or source.with_suffix(".pdf")).resolve()
    try:
        shown_source = str(source.relative_to(REPO_ROOT))
    except ValueError:
        shown_source = source.name

    fields, body = split_front_matter(source.read_text(encoding="utf-8"))
    missing = [k for k in ("judul", "subjudul", "label", "versi", "tanggal", "klasifikasi", "pemilik") if not fields.get(k)]
    if missing:
        sys.exit(f"Front matter belum lengkap: {', '.join(missing)}")

    body, figures = extract_diagrams(drop_title(body), source.parent / "assets" / source.stem.lower())
    body_html, headings = render_body(body, figures)
    chrome = chrome_binary()

    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "document.html"
        draft = Path(tmp) / "draft.pdf"
        # Pass 1 leaves the page numbers blank; the contents is one line per entry either way,
        # so filling them in on pass 2 cannot move a heading to another page.
        page.write_text(document(fields, shown_source, body_html, headings, {}), encoding="utf-8")
        print_pdf(chrome, page, draft)
        pages = heading_pages(draft, headings)
        page.write_text(document(fields, shown_source, body_html, headings, pages), encoding="utf-8")
        print_pdf(chrome, page, output)

    print(f"PDF: {output} ({len(pypdf.PdfReader(output).pages)} halaman)")


_CSS = """
@page {
  size: A4;
  margin: 24mm 18mm 22mm 18mm;
  @top-left     { content: %%HEADER_LEFT%%;  font-family: %%FONT%%; font-size: 8pt; color: #6b7780; }
  @top-right    { content: %%HEADER_RIGHT%%; font-family: %%FONT%%; font-size: 7.5pt; font-weight: 700;
                  letter-spacing: .14em; color: %%ACCENT%%; }
  @bottom-left  { content: %%FOOTER_LEFT%%;  font-family: %%FONT%%; font-size: 8pt; color: #6b7780; }
  @bottom-right { content: "Halaman " counter(page) " dari " counter(pages);
                  font-family: %%FONT%%; font-size: 8pt; color: #6b7780; }
}
@page :first {
  margin: 0;
  @top-left { content: none; }
  @top-right { content: none; }
  @bottom-left { content: none; }
  @bottom-right { content: none; }
}

:root {
  --ink: #1b1f1d; --ink-soft: #46505a; --ink-mute: #6b7780; --rule: #dfe4e6;
  --accent: %%ACCENT%%; --accent-lt: %%ACCENT_LIGHT%%; --panel: %%PANEL%%;
}
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; color: var(--ink); font-family: %%FONT%%; font-size: 10.2pt; line-height: 1.6; }

/* cover */
.cover {
  position: relative; width: 210mm; height: 297mm; padding: 40mm 24mm 22mm;
  background: var(--accent); color: #f3f8f9; display: flex; flex-direction: column;
  break-after: page;
}
.cover .band { position: absolute; left: 0; top: 0; width: 100%; height: 5mm; background: var(--accent-lt); }
.cover .eyebrow { font-size: 9.5pt; letter-spacing: .22em; text-transform: uppercase; color: %%COVER_DIM%%; margin-bottom: 12mm; }
.cover .title { font-size: 34pt; line-height: 1.1; font-weight: 700; letter-spacing: -.015em; margin: 0 0 7mm; max-width: 150mm; }
.cover .sub { font-size: 13pt; line-height: 1.5; color: %%COVER_SOFT%%; max-width: 140mm; margin: 0 0 auto; }
.cover .highlights { display: flex; gap: 10mm; margin-bottom: 9mm; }
.cover .highlights div { font-size: 9pt; line-height: 1.45; color: %%COVER_SOFT%%; }
.cover .highlights b { display: block; font-size: 11pt; color: #ffffff; margin-bottom: 1.5mm; }
.cover .meta {
  display: flex; justify-content: space-between; align-items: center;
  border-top: 1px solid %%COVER_RULE%%; padding-top: 6mm; font-size: 9pt; color: %%COVER_DIM%%;
}
.cover .meta b { color: #ffffff; font-weight: 600; }
.cover .badge {
  border: 1px solid %%COVER_DIM%%; border-radius: 2px; padding: 1mm 3mm;
  font-size: 8pt; font-weight: 700; letter-spacing: .14em; color: #ffffff;
}

/* front page */
.front { break-after: page; }
.front .heading {
  font-size: 17pt; font-weight: 700; color: var(--accent);
  border-bottom: 2px solid var(--accent); padding-bottom: 3mm; margin: 0 0 5mm;
}
table.docinfo { margin: 0 0 11mm; }
table.docinfo th {
  width: 38mm; background: var(--panel); color: var(--accent); border-bottom: 1px solid #ffffff;
}
table.docinfo td { border-bottom: 1px solid var(--rule); }
ol.toc { list-style: none; margin: 0; padding: 0; }
ol.toc li { margin: 0; }
ol.toc a { display: flex; align-items: baseline; gap: 2mm; text-decoration: none; }
ol.toc li.l2 a { padding: 1.5mm 0; font-size: 10.4pt; font-weight: 700; color: var(--accent); }
ol.toc li.l3 a { padding: .5mm 0 .5mm 7mm; font-size: 9.2pt; color: var(--ink-soft); }
ol.toc .dots { flex: 1; border-bottom: 1px dotted #b3bec2; transform: translateY(-1mm); }
ol.toc .n { min-width: 7mm; text-align: right; font-variant-numeric: tabular-nums; }

/* body */
h2 {
  break-before: page; break-after: avoid;
  font-size: 17pt; line-height: 1.25; color: var(--accent);
  border-bottom: 2px solid var(--accent); padding-bottom: 3mm; margin: 0 0 5mm;
}
.body > h2:first-of-type { break-before: avoid; margin-top: 9mm; }
h3 { break-after: avoid; font-size: 12pt; color: var(--ink); margin: 7mm 0 2.5mm; }
p { margin: 0 0 3mm; }
ul, ol { margin: 0 0 3.5mm; padding-left: 6mm; }
li { margin-bottom: 1.2mm; }
a { color: var(--accent-lt); text-decoration: none; }
strong { font-weight: 700; }
em { font-style: italic; }

code {
  font-family: %%MONO%%; font-size: .86em; color: #233640;
  background: #f1f4f5; padding: .4mm 1.2mm; border-radius: 2px;
}
pre {
  background: #f5f7f8; border: 1px solid var(--rule); border-left: 3px solid var(--accent-lt);
  border-radius: 3px; padding: 3mm 4mm; margin: 0 0 4mm; break-inside: avoid;
}
pre code { background: none; padding: 0; font-size: 8.4pt; line-height: 1.5; white-space: pre-wrap; }

table { width: 100%; border-collapse: collapse; margin: 0 0 5mm; font-size: 9.1pt; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th {
  background: var(--panel); color: var(--accent); text-align: left; font-weight: 700;
  padding: 2mm 2.5mm; border-bottom: 1.5px solid var(--accent-lt); vertical-align: top;
}
td { padding: 2mm 2.5mm; border-bottom: 1px solid var(--rule); vertical-align: top; }
tbody tr:nth-child(even) td { background: #fafbfb; }

blockquote {
  margin: 0 0 5mm; padding: 3mm 4mm; background: var(--panel);
  border-left: 3px solid var(--accent-lt); color: var(--ink-soft); break-inside: avoid;
}
blockquote p:last-child { margin-bottom: 0; }
.warn {
  background: #fdf6e8; border-left: 3px solid #d9a441; color: #5c4212;
  padding: 2.5mm 4mm; margin: 0 0 3.5mm; break-inside: avoid;
}

figure.diagram { margin: 3mm 0 6mm; break-inside: avoid; }
figure.diagram svg { display: block; width: 100%; height: auto; max-height: 165mm; }
figure.diagram figcaption { margin-top: 2.5mm; text-align: center; font-size: 8.8pt; color: var(--ink-mute); }

.end { margin-top: 10mm; text-align: center; font-size: 8.5pt; letter-spacing: .1em; color: var(--ink-mute); }
"""


if __name__ == "__main__":
    main()
