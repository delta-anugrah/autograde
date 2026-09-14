#!/usr/bin/env bash
# Markdown → PDF without LaTeX or pandoc: python-markdown renders the HTML and
# headless Chrome prints it. Both are already on any laptop that runs this repo,
# so the PDF stays reproducible instead of being a binary nobody can rebuild.
#
#   scripts/md-to-pdf.sh docs/ONBOARDING.md            → docs/ONBOARDING.pdf
#   scripts/md-to-pdf.sh docs/ONBOARDING.md /tmp/x.pdf
#
# Needs: pip install markdown   (test-only, not a runtime dependency)
set -euo pipefail

SRC="${1:?usage: scripts/md-to-pdf.sh <file.md> [out.pdf]}"
OUT="${2:-${SRC%.md}.pdf}"

python3 -c 'import markdown' 2>/dev/null || {
  echo "python-markdown belum ada. Pasang dulu: pip install markdown" >&2
  exit 1
}

CHROME=""
for candidate in \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "$(command -v google-chrome || true)" \
  "$(command -v chromium || true)" \
  "$(command -v chromium-browser || true)"; do
  [ -x "$candidate" ] && CHROME="$candidate" && break
done
[ -n "$CHROME" ] || { echo "Chrome/Chromium tidak ketemu — itu yang mencetak PDF-nya." >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
HTML="$WORK/doc.html"

SRC="$SRC" HTML="$HTML" python3 <<'PY'
import os
import pathlib

import markdown

src = pathlib.Path(os.environ["SRC"])
body = markdown.markdown(
    src.read_text(encoding="utf-8"),
    extensions=["tables", "fenced_code", "sane_lists", "attr_list"],
)

# Print styling only — screen readers get the Markdown, this is for paper.
pathlib.Path(os.environ["HTML"]).write_text(
    f"""<!doctype html>
<html lang="id"><head><meta charset="utf-8"><title>{src.stem}</title><style>
  @page {{ size: A4; margin: 18mm 16mm; }}
  body {{ font: 10.5pt/1.55 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
          color: #1a1a1a; }}
  h1 {{ font-size: 21pt; border-bottom: 2px solid #1a7f4b; padding-bottom: 6px; }}
  h2 {{ font-size: 15pt; margin-top: 26px; color: #14663c; page-break-after: avoid; }}
  h3 {{ font-size: 12pt; margin-top: 18px; page-break-after: avoid; }}
  p, li {{ orphans: 3; widows: 3; }}
  table {{ border-collapse: collapse; width: 100%; margin: 10px 0; page-break-inside: avoid; }}
  th, td {{ border: 1px solid #cfd6d2; padding: 5px 8px; text-align: left; vertical-align: top;
            font-size: 9.5pt; }}
  th {{ background: #eef5f1; }}
  code {{ font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 9pt;
          background: #f2f4f3; padding: 1px 4px; border-radius: 3px; }}
  pre {{ background: #f7f9f8; border: 1px solid #e2e8e5; border-radius: 5px; padding: 10px;
         page-break-inside: avoid; overflow-wrap: break-word; white-space: pre-wrap; }}
  pre code {{ background: none; padding: 0; font-size: 8.5pt; line-height: 1.35; }}
  blockquote {{ border-left: 3px solid #1a7f4b; margin-left: 0; padding-left: 12px; color: #444; }}
  hr {{ border: 0; border-top: 1px solid #dde4e0; margin: 22px 0; }}
</style></head><body>
{body}
</body></html>""",
    encoding="utf-8",
)
PY

"$CHROME" --headless --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="$OUT" "file://$HTML" >/dev/null 2>&1

echo "PDF: $OUT"
