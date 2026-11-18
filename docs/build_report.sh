#!/usr/bin/env bash
# ============================================================================
#  build_report.sh — compile the EC486 LaTeX report to PDF
#
#  Usage:   ./build_report.sh
#
#  Produces: docs/EC486_Minor_Project_Report.pdf
#  Two passes are run so the "Page X of Y" footer resolves via lastpage.
#
#  If you have NO local TeX install (common on this Mac — no pdflatex/brew/
#  docker found), just upload the .tex to Overleaf (free) and it compiles
#  as-is. The document is fully self-contained: no external images, no .bib,
#  no \input files, no shell-escape. Only standard TeX Live packages.
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

# Ensure ~/.local/bin is in PATH (common for user-installed tools like tectonic)
export PATH="$HOME/.local/bin:$PATH"

JOB="EC486_Minor_Project_Report"

pick() {
  for c in pdflatex lualatex xelatex tectonic latexmk; do
    if command -v "$c" >/dev/null 2>&1; then echo "$c"; return 0; fi
  done
  return 1
}

ENGINE="$(pick || true)"

if [ -z "$ENGINE" ]; then
  cat <<'MSG'
No LaTeX engine found (looked for: pdflatex, lualatex, xelatex, tectonic, latexmk).

Quickest fix — use Overleaf (free, no install):
  1. Go to https://www.overleaf.com  ->  New Project  ->  Upload Project
  2. Upload this file:  docs/EC486_Minor_Project_Report.tex
     (menu: Menu -> Compiler -> pdfLaTeX)
  3. Click Recompile. Download the PDF.

Local options (if you want a native build):
  macOS : install MacTeX (https://tug.org/mactex) or BasicTeX (~100MB subset)
  Debian: sudo apt-get install texlive-latex-extra texlive-fonts-recommended

Then re-run:  ./build_report.sh
MSG
  exit 1
fi

echo "Using engine: $ENGINE"
if [ "$ENGINE" = "tectonic" ]; then
  tectonic "${JOB}.tex"
elif [ "$ENGINE" = "latexmk" ]; then
  latexmk -pdf -interaction=nonstopmode -halt-on-error "${JOB}.tex"
else
  # Two passes: pass 1 writes .aux/.out, pass 2 resolves Page X of Y + refs.
  "$ENGINE" -interaction=nonstopmode -halt-on-error "${JOB}.tex"
  "$ENGINE" -interaction=nonstopmode -halt-on-error "${JOB}.tex"
fi

echo
echo "Built: $(pwd)/${JOB}.pdf"
