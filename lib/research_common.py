"""Shared helpers for the research toolkit (fetch_doc, doc_search, render_page, check_output)."""
import os
import re
import shutil
import unicodedata
from pathlib import Path

CONF_PATH = Path(os.environ.get("RESEARCH_KIT_CONF", "/usr/local/etc/research-kit.conf"))


def _read_conf():
    data = {}
    try:
        for line in CONF_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip().strip('"')
    except OSError:
        pass
    return data


CONF = _read_conf()

HOME = Path(os.environ.get("RESEARCH_HOME") or (Path.home() / "work"))
SOURCES = HOME / "sources"
OUT = HOME / "out"
RENDERS = HOME / "scratch" / "renders"

WORKSPACE_DIRS = ("scratch", "scratch/renders", "tools", "state", "state/ledgers", "out", "sources")


def work_template_path():
    """The WORK.md template: RESEARCH_WORK_TEMPLATE if set, else WORK.md next to the installed library or at the repo root."""
    forced = os.environ.get("RESEARCH_WORK_TEMPLATE")
    if forced:
        p = Path(forced).expanduser()
        return p if p.is_file() else None
    here = Path(__file__).resolve().parent
    for p in (here / "WORK.md", here.parent / "WORK.md"):
        if p.is_file():
            return p
    return None


def work_template_text():
    p = work_template_path()
    return p.read_text(encoding="utf-8") if p else None


def ensure_workspace():
    """Create the workspace folders and README.md if missing; never overwrites. Returns the paths it created."""
    created = []
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        for d in WORKSPACE_DIRS:
            p = HOME / d
            if not p.is_dir():
                p.mkdir(parents=True, exist_ok=True)
                created.append(str(p))
        readme = HOME / "README.md"
        if not readme.exists():
            text = work_template_text()
            if text is not None:
                readme.write_text(text, encoding="utf-8")
                created.append(str(readme))
    except OSError:
        pass
    return created

# Playwright's own Chromium (only downloaded by install.sh when the system has none) lives here.
if Path("/opt/ms-playwright").exists():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/ms-playwright")

BROWSER_CANDIDATES = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")
BROWSER_ARGS = ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]


def system_browser():
    """Chromium/Chrome already on the machine ('' if none). RESEARCH_BROWSER or BROWSER_PATH in the conf overrides."""
    forced = os.environ.get("RESEARCH_BROWSER") or CONF.get("BROWSER_PATH")
    if forced:
        return forced
    for name in BROWSER_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    return ""


def browser_label():
    return system_browser() or "Playwright-managed Chromium"


def launch_chromium(p):
    """Start headless Chromium through an open Playwright context: the system browser if there is one, else Playwright's."""
    exe = system_browser()
    try:
        if exe:
            return p.chromium.launch(executable_path=exe, args=BROWSER_ARGS)
        return p.chromium.launch(args=BROWSER_ARGS)
    except Exception as e:  # noqa: BLE001
        first = str(e).strip().splitlines()[0][:200] if str(e).strip() else type(e).__name__
        raise RuntimeError(f"could not start browser ({exe or 'Playwright-managed Chromium'}): {first}") from e

MARKER_RE = re.compile(r"^=== (PAGE|SHEET|SLIDE|PART) (.+?) ===$")


def ocr_langs():
    return os.environ.get("RESEARCH_OCR_LANGS") or CONF.get("OCR_LANGS") or "eng"


def have(cmd):
    return shutil.which(cmd) is not None


def norm(s):
    """Accent- and case-insensitive form used only for matching (never for display)."""
    s = s.replace("đ", "d").replace("Đ", "D").replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.casefold()


def slugify(name, limit=60):
    s = norm(name)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s or "doc")[:limit].strip("-") or "doc"


def doc_dir(name):
    return SOURCES / name


def list_docs():
    if not SOURCES.exists():
        return []
    return sorted(p.name for p in SOURCES.iterdir() if (p / "text.txt").exists())


def read_text(name):
    path = doc_dir(name) / "text.txt"
    if not path.exists():
        known = ", ".join(list_docs()) or "none yet"
        raise SystemExit(f"No extracted document named '{name}'. Known: {known}")
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def blocks_of(lines):
    """Return [(kind, label, start_idx, end_idx_exclusive)] using location markers."""
    marks = []
    for i, line in enumerate(lines):
        m = MARKER_RE.match(line)
        if m:
            marks.append((m.group(1), m.group(2), i))
    out = []
    for n, (kind, label, i) in enumerate(marks):
        end = marks[n + 1][2] if n + 1 < len(marks) else len(lines)
        out.append((kind, label, i, end))
    return out


def location_of(blocks, idx):
    for kind, label, s, e in blocks:
        if s <= idx < e:
            return f"{kind} {label}"
    return "-"
