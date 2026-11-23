#!/usr/bin/env bash
# Installs the research toolkit into a Debian/Ubuntu-based container (the Open Terminal image is Debian-based).
# Re-runnable. Needs root or passwordless sudo.
#
#   ./install.sh                         defaults: OCR languages "eng hrv", LibreOffice, and a browser for rendering
#   ./install.sh --langs "eng deu fra"   OCR languages (tesseract 3-letter codes)
#   ./install.sh --no-office             skip LibreOffice (no Office rendering / spreadsheet recalculation)
#   ./install.sh --no-browser            remove Playwright entirely (no web screenshots, no HTML/SVG render checks); default reuses the system Chromium
#   ./install.sh --reader off            never use the Jina Reader fallback for JavaScript-heavy web pages (default: auto)
set -euo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LANGS="eng hrv"
WITH_OFFICE=1
WITH_BROWSER=1
READER=auto
while [ $# -gt 0 ]; do
  case "$1" in
    --langs) LANGS="$2"; shift 2 ;;
    --no-office) WITH_OFFICE=0; shift ;;
    --no-browser) WITH_BROWSER=0; shift ;;
    --reader) READER="$2"; shift 2 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
done

say() { printf '\n==> %s\n' "$*"; }

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then SUDO="sudo"
  else echo "ERROR: need root or passwordless sudo (run: docker exec -u root -it <container> bash)" >&2; exit 1; fi
fi
command -v apt-get >/dev/null 2>&1 || { echo "ERROR: apt-get not found; this kit supports Debian/Ubuntu images only (not the :alpine or :slim variants)" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found" >&2; exit 1; }

say "System packages (apt)"
export DEBIAN_FRONTEND=noninteractive
$SUDO apt-get update -qq
PKGS="ca-certificates poppler-utils tesseract-ocr fonts-liberation fonts-dejavu-core unzip file"
for l in $LANGS; do [ "$l" = "eng" ] || PKGS="$PKGS tesseract-ocr-$l"; done
if [ "$WITH_OFFICE" = 1 ]; then PKGS="$PKGS libreoffice-writer libreoffice-calc libreoffice-impress"; fi
if ! python3 -m pip --version >/dev/null 2>&1; then PKGS="$PKGS python3-pip"; fi
# shellcheck disable=SC2086
$SUDO apt-get install -y -qq --no-install-recommends $PKGS

say "Python packages"
REQ="$KIT_DIR/requirements.txt"
pip_install() {
  python3 -m pip install -q --disable-pip-version-check "$@" 2>/dev/null \
    || python3 -m pip install -q --disable-pip-version-check --break-system-packages "$@" 2>/dev/null \
    || $SUDO python3 -m pip install -q --disable-pip-version-check --break-system-packages "$@"
}
pip_install -r "$REQ"
if [ "$WITH_BROWSER" = 1 ]; then pip_install playwright; fi

if [ "$WITH_BROWSER" = 1 ]; then
  SYS_BROWSER=""
  for b in chromium chromium-browser google-chrome google-chrome-stable; do
    if command -v "$b" >/dev/null 2>&1; then SYS_BROWSER="$(command -v "$b")"; break; fi
  done
  if [ -n "$SYS_BROWSER" ]; then
    say "Using the system browser $SYS_BROWSER (no browser download)"
  else
    say "No system Chromium found: downloading Playwright's Chromium (shared location /opt/ms-playwright)"
    USERSITE="$(python3 -c 'import site;print(site.getusersitepackages())' 2>/dev/null || true)"
    $SUDO env "PATH=$PATH" "PYTHONPATH=${USERSITE}" PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
      python3 -m playwright install --with-deps chromium
    $SUDO chmod -R a+rX /opt/ms-playwright
  fi
fi

say "Installing tools to /usr/local/bin"
$SUDO install -d /usr/local/lib/research_kit /usr/local/etc
$SUDO install -m 644 "$KIT_DIR"/lib/*.py /usr/local/lib/research_kit/
for f in "$KIT_DIR"/bin/*.py; do
  n="$(basename "$f" .py)"
  $SUDO install -m 755 "$f" "/usr/local/bin/$n"
done
OCR_JOINED="$(echo "$LANGS" | tr ' ' '+')"
case "$READER" in auto|off|force) ;; *) echo "ERROR: --reader must be auto, off or force" >&2; exit 1 ;; esac
printf 'OCR_LANGS=%s\nREADER=%s\n' "$OCR_JOINED" "$READER" | $SUDO tee /usr/local/etc/research-kit.conf >/dev/null

say "Self-test"
if research_selftest; then
  echo
  echo "Done. Tools: fetch_doc, doc_search, render_page, check_output, research_selftest"
  echo "Workspace: \$HOME/work/{sources,out,renders}  (created on first use)"
else
  echo "Self-test reported failures: see output above." >&2
  exit 1
fi
