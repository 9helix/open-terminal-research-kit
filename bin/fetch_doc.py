#!/usr/bin/env python3
"""fetch_doc: download (URL) or open (path) any document and extract its text with location markers.

Output goes to $RESEARCH_HOME/sources/<name>/ (default ~/work/sources/<name>/):
  text.txt       extracted text, split by "=== PAGE n ===" / "=== SHEET x ===" / "=== SLIDE n ===" / "=== PART n ==="
  manifest.json  type, size, pages, extraction method, OCR pages, warnings
  original.<ext> the untouched original file
  outline.txt    table of contents / headings when available
  links.txt      hyperlinks (HTML only), useful for finding attachments and newer versions

Nothing large is printed: read the result with doc_search.

Web pages (not documents) that look JavaScript-rendered, or that lack text you told it to expect (--expect), are
re-fetched through Jina Reader (https://r.jina.ai, a third-party service that renders the page remotely) unless
--reader off. See "JavaScript-heavy pages" below for the rules and privacy guards.
"""
import argparse
import io
import ipaddress
import json
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

sys.path[:0] = [str(Path(__file__).resolve().parent.parent / "lib"), "/usr/local/lib/research_kit"]
from research_common import CONF, SOURCES, doc_dir, have, norm, ocr_langs, slugify  # noqa: E402

UAS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "curl/8.5.0",
]
CHUNK = 3500
TYPE_EXT = {"pdf": ".pdf", "docx": ".docx", "xlsx": ".xlsx", "pptx": ".pptx", "html": ".html",
            "csv": ".csv", "text": ".txt", "image": ".img"}


class Result:
    def __init__(self):
        self.parts = []          # [(kind, label, text)]
        self.warnings = []
        self.outline = []
        self.links = []
        self.ocr_pages = []
        self.method = ""
        self.pages = None
        self.js_reasons = []     # why a web page looks JavaScript-rendered (set by extract_html)
        self.visible_chars = 0
        self.text_norm = ""      # normalised page text, used for --expect checks
        self.reader = None       # info about Jina Reader use, goes into the manifest
        self.local_parts = None  # standard extraction kept when the reader result replaces it


# ---------------------------------------------------------------- download

def sniff_type(data, name="", ctype=""):
    head = data[:2048]
    low = head.lstrip().lower()
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            names = []
        if any(n.startswith("word/") for n in names):
            return "docx"
        if any(n.startswith("xl/") for n in names):
            return "xlsx"
        if any(n.startswith("ppt/") for n in names):
            return "pptx"
    if head[:8] == b"\x89PNG\r\n\x1a\n" or head[:3] == b"\xff\xd8\xff" or head[:4] in (b"GIF8", b"II*\x00", b"MM\x00*"):
        return "image"
    if low.startswith(b"<!doctype html") or low.startswith(b"<html") or b"<html" in low[:500] or "html" in ctype:
        return "html"
    ext = Path(name).suffix.lower()
    if ext in (".csv", ".tsv"):
        return "csv"
    if ext in (".txt", ".md", ".json", ".xml", ".log", ".rst"):
        return "text"
    if ctype.startswith("text/") or ctype in ("application/json", "application/xml"):
        return "text"
    if b"\x00" not in head:
        return "text"
    return "binary"


def wayback_url(url):
    import httpx
    try:
        r = httpx.get("https://archive.org/wayback/available", params={"url": url}, timeout=30)
        snap = r.json().get("archived_snapshots", {}).get("closest")
        if snap and snap.get("available"):
            u = snap["url"].replace("http://", "https://")
            return re.sub(r"(/web/\d{14})/", r"\1id_/", u, count=1)
    except Exception:
        pass
    return None


def download(url, use_archive):
    import httpx
    errors = []
    candidates = [url] + ([] if not use_archive else ["__ARCHIVE__"])
    for cand in candidates:
        if cand == "__ARCHIVE__":
            cand = wayback_url(url)
            if not cand:
                errors.append("archive.org: no snapshot found")
                continue
        for ua in UAS:
            try:
                with httpx.Client(follow_redirects=True, timeout=90, headers={
                        "User-Agent": ua, "Accept": "*/*", "Accept-Language": "en,hr;q=0.8"}) as c:
                    r = c.get(cand)
                if r.status_code >= 400:
                    errors.append(f"{cand} -> HTTP {r.status_code} (UA {ua[:12]}...)")
                    continue
                if not r.content:
                    errors.append(f"{cand} -> empty body (UA {ua[:12]}...)")
                    continue
                cd = r.headers.get("content-disposition", "")
                m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', cd)
                fname = unquote(m.group(1)) if m else unquote(Path(urlparse(str(r.url)).path).name)
                return r.content, fname, r.headers.get("content-type", "").split(";")[0].strip(), str(r.url), errors
            except Exception as e:  # noqa: BLE001
                errors.append(f"{cand} -> {type(e).__name__}: {e}")
    return None, "", "", url, errors


# ---------------------------------------------------------------- OCR helpers

_warned_tesseract = False


def ocr_png(png_path, langs, res):
    global _warned_tesseract
    if not have("tesseract"):
        if not _warned_tesseract:
            res.warnings.append("tesseract not installed: image-only content could not be OCR'd (run install.sh)")
            _warned_tesseract = True
        return ""
    try:
        out = subprocess.run(["tesseract", str(png_path), "stdout", "-l", langs, "-c", "preserve_interword_spaces=1"],
                             capture_output=True, text=True, timeout=180)
        if out.returncode != 0 and "Failed loading language" in out.stderr:
            res.warnings.append(f"tesseract language pack missing for '{langs}': {out.stderr.strip()[:120]}")
        return out.stdout.strip()
    except Exception as e:  # noqa: BLE001
        res.warnings.append(f"OCR failed: {e}")
        return ""


def ocr_zip_media(path, prefix, langs, res, min_bytes=15000):
    """OCR embedded images of docx/pptx (images often hold tables or scanned text)."""
    texts = []
    with zipfile.ZipFile(path) as z:
        media = [n for n in z.namelist() if n.startswith(prefix) and Path(n).suffix.lower() in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif")]
        for n in media:
            data = z.read(n)
            if len(data) < min_bytes:
                continue
            with tempfile.TemporaryDirectory() as td:
                p = Path(td) / ("img" + Path(n).suffix)
                p.write_bytes(data)
                t = ocr_png(p, langs, res)
            if len(t) > 30:
                texts.append(f"[IMAGE OCR: {Path(n).name}]\n{t}")
    return media, texts


# ---------------------------------------------------------------- extractors

def chunk_blocks(blocks, size=CHUNK):
    parts, cur, n = [], [], 0
    for b in blocks:
        cur.append(b)
        n += len(b)
        if n >= size:
            parts.append("\n".join(cur))
            cur, n = [], 0
    if cur:
        parts.append("\n".join(cur))
    return parts


def extract_pdf(path, a, res):
    import pymupdf
    doc = pymupdf.open(path)
    if doc.needs_pass:
        raise RuntimeError("PDF is password-protected")
    res.method = "pymupdf text layer"
    res.pages = len(doc)
    for t in doc.get_toc() or []:
        res.outline.append(f"{'  ' * (t[0] - 1)}{t[1]} (p.{t[2]})")
    low = []
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text").strip()
        n_img = len(page.get_images(full=True))
        need = a.ocr == "force" or (a.ocr == "auto" and (len(text) < 40 or (n_img > 0 and len(text) < 200)))
        ocr_text = ""
        if need:
            with tempfile.TemporaryDirectory() as td:
                png = Path(td) / "p.png"
                page.get_pixmap(dpi=a.dpi).save(str(png))
                ocr_text = ocr_png(png, a.lang, res)
            if len(ocr_text) > 20:
                res.ocr_pages.append(i)
        body = text
        if ocr_text and len(ocr_text) > 20:
            body = (text + "\n\n[OCR of page image]\n" + ocr_text).strip() if text else "[OCR of page image]\n" + ocr_text
        if not a.no_tables and text:
            try:
                tabs = page.find_tables()
                md = [t.to_markdown() for t in tabs.tables if t.row_count >= 2 and t.col_count >= 2]
                if md:
                    body += "\n\n[TABLES detected on this page]\n" + "\n\n".join(md)
            except Exception:  # noqa: BLE001
                pass
        if len(body.strip()) < 20:
            low.append(i)
        res.parts.append(("PAGE", str(i), body))
    if res.ocr_pages:
        res.method += f" + OCR ({a.lang}) on pages {_ranges(res.ocr_pages)}"
        res.warnings.append("OCR text can contain recognition errors in digits and diacritics: verify key figures with render_page")
    if low:
        res.warnings.append(f"pages with almost no text even after OCR: {_ranges(low)} (look at them with render_page)")


def _ranges(nums):
    nums = sorted(set(nums))
    out, start, prev = [], None, None
    for n in nums:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{start}-{prev}" if start != prev else str(start))
            start = prev = n
    if start is not None:
        out.append(f"{start}-{prev}" if start != prev else str(start))
    return ",".join(out)


def extract_docx(path, a, res):
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    d = Document(path)
    res.method = "python-docx"
    blocks = []
    for child in d.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, d)
            txt = p.text.strip()
            if not txt:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            if style.lower().startswith("heading"):
                nums = re.findall(r"\d+", style)
                lvl = int(nums[0]) if nums else 1
                blocks.append("#" * min(lvl, 6) + " " + txt)
                res.outline.append("  " * (lvl - 1) + txt)
            elif style.lower() == "title":
                blocks.append("# " + txt)
            elif "list" in style.lower():
                blocks.append("- " + txt)
            else:
                blocks.append(txt)
        elif tag == "tbl":
            t = Table(child, d)
            rows = []
            for row in t.rows:
                cells = []
                prev = None
                for c in row.cells:
                    if c._tc is prev:
                        continue
                    prev = c._tc
                    cells.append(c.text.strip().replace("\n", " "))
                rows.append("| " + " | ".join(cells) + " |")
            blocks.append("[TABLE]\n" + "\n".join(rows))
    for n, txt in enumerate(chunk_blocks(blocks), start=1):
        res.parts.append(("PART", str(n), txt))
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
        names = z.namelist()
    if "<w:ins " in xml or "<w:del " in xml:
        res.warnings.append("tracked changes present: inserted/deleted text may be missing or merged")
    if any(n.startswith("word/comments") for n in names):
        res.warnings.append("document has comments (not extracted)")
    res.warnings.append("headers, footers, footnotes and text boxes are not extracted")
    if a.ocr != "off":
        media, texts = ocr_zip_media(path, "word/media/", a.lang, res)
        if media:
            res.warnings.append(f"{len(media)} embedded images (tables or scans may be images); OCR appended where text was found")
        if texts:
            res.parts.append(("PART", "images", "\n\n".join(texts)))
            res.method += " + OCR of embedded images"


def extract_xlsx(path, a, res):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    res.method = "openpyxl (cached cell values; formulas are not evaluated)"
    res.pages = len(wb.worksheets)
    for ws in wb.worksheets:
        lines, n = [], 0
        state = getattr(ws, "sheet_state", "visible")
        if state != "visible":
            lines.append(f"[sheet state: {state}]")
        for r_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if all(c is None or str(c).strip() == "" for c in row):
                continue
            n += 1
            if n > 20000:
                res.warnings.append(f"sheet '{ws.title}' truncated at 20000 non-empty rows")
                break
            cells = ["" if c is None else str(c).replace("\n", " ").replace("\t", " ") for c in row]
            while cells and cells[-1] == "":
                cells.pop()
            lines.append(f"R{r_idx}\t" + "\t".join(cells))
        res.parts.append(("SHEET", ws.title, "\n".join(lines) if lines else "[empty sheet]"))
        res.outline.append(f"{ws.title} ({n} non-empty rows, state={state})")


def extract_pptx(path, a, res):
    from pptx import Presentation
    prs = Presentation(path)
    res.method = "python-pptx"
    res.pages = len(prs.slides)
    pics = 0
    for i, slide in enumerate(prs.slides, start=1):
        lines = []
        for sh in slide.shapes:
            if sh.shape_type == 13:
                pics += 1
            if sh.has_text_frame and sh.text_frame.text.strip():
                lines.append(sh.text_frame.text.strip())
            if getattr(sh, "has_table", False) and sh.has_table:
                rows = ["| " + " | ".join(c.text.strip().replace("\n", " ") for c in r.cells) + " |" for r in sh.table.rows]
                lines.append("[TABLE]\n" + "\n".join(rows))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            lines.append("[NOTES] " + slide.notes_slide.notes_text_frame.text.strip())
        res.parts.append(("SLIDE", str(i), "\n".join(lines)))
    if pics and a.ocr != "off":
        media, texts = ocr_zip_media(path, "ppt/media/", a.lang, res)
        if texts:
            res.parts.append(("SLIDE", "images", "\n\n".join(texts)))
            res.method += " + OCR of embedded images"
    if pics:
        res.warnings.append(f"{pics} pictures on slides (text inside pictures needs OCR or render_page)")


def extract_html(data, url, a, res):
    from bs4 import BeautifulSoup
    res.method = "BeautifulSoup text"
    soup = BeautifulSoup(data, "lxml")
    raw = data.decode("utf-8", "ignore") if isinstance(data, (bytes, bytearray)) else str(data)
    scripts = soup.find_all("script")
    n_scripts = len(scripts)
    script_bytes = sum(len(str(sc)) for sc in scripts)
    noscript_text = " ".join(n.get_text(" ", strip=True) for n in soup.find_all("noscript"))
    for t in soup(["script", "style", "noscript", "template"]):
        t.decompose()
    if url:
        for aa in soup.find_all("a", href=True):
            href = urljoin(url, aa["href"])
            if href.startswith("http"):
                res.links.append(f"{aa.get_text(' ', strip=True)[:120]}\t{href}")
    blocks = []
    names = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "tr", "pre", "blockquote", "dt", "dd", "figcaption"]
    for el in soup.find_all(names):
        if el.name != "tr" and el.find_parent("tr"):
            continue
        if el.name in ("li", "blockquote") and el.find(names):
            continue
        if el.name == "tr":
            cells = [c.get_text(" ", strip=True) for c in el.find_all(["td", "th"])]
            txt = "| " + " | ".join(cells) + " |" if any(cells) else ""
        else:
            txt = el.get_text(" ", strip=True)
        if not txt:
            continue
        if el.name.startswith("h") and len(el.name) == 2:
            lvl = int(el.name[1])
            blocks.append("#" * lvl + " " + txt)
            res.outline.append("  " * (lvl - 1) + txt)
        elif el.name == "li":
            blocks.append("- " + txt)
        else:
            blocks.append(txt)
    if not blocks:
        res.warnings.append("no text extracted: page may need JavaScript rendering (try render_page with a browser)")
    for n, txt in enumerate(chunk_blocks(blocks), start=1):
        res.parts.append(("PART", str(n), txt))
    if len(soup.get_text(strip=True)) < 300 and n_scripts:
        res.warnings.append("very little text: page may load its content with JavaScript")
    visible = sum(len(b) for b in blocks)
    all_text = " ".join(blocks)
    res.visible_chars = visible
    res.text_norm = norm(all_text)
    res.js_reasons = js_signals(raw, visible, n_scripts, script_bytes, norm(noscript_text + " " + all_text[:4000]))


def decode_text(data):
    for enc in ("utf-8-sig", "utf-16", "cp1250", "latin-1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("utf-8", "replace")


def extract_text(data, a, res, kind):
    res.method = "plain text"
    lines = decode_text(data).splitlines()
    size = 200 if kind == "csv" else 120
    for n in range(0, len(lines), size):
        chunk = lines[n:n + size]
        label = str(n // size + 1)
        res.parts.append(("PART", label, "\n".join(f"L{n + k + 1}\t{l}" if kind == "csv" else l for k, l in enumerate(chunk))))


def extract_image(path, a, res):
    res.method = f"tesseract OCR ({a.lang})"
    t = ocr_png(path, a.lang, res)
    res.parts.append(("PART", "1", t))
    res.ocr_pages.append(1)
    if len(t) < 20:
        res.warnings.append("OCR returned almost no text")


# ---------------------------------------------------------------- JavaScript-heavy pages -> Jina Reader
#
# Rules (web pages only; PDF/Office/CSV/images are never sent anywhere):
#   1. The standard fetch + extraction always runs first.
#   2. If the page looks JavaScript-rendered (js_signals), or text you passed with --expect is missing, the page is
#      re-fetched through Jina Reader, which renders it in a remote browser and returns markdown.
#   3. The reader result replaces the standard one only if it is clearly better; the standard text is kept in
#      text_local.txt. If the reader fails or is not better, the standard result stays and a WARN says why.
#   4. Privacy: on the public endpoint the URL (not your files) is sent to a third party. Local/private hosts, URLs
#      with credentials and URLs carrying tokens/signatures are never sent. --reader off disables it entirely.
#   Config: JINA_API_KEY (environment) raises the rate limit; RESEARCH_READER_URL (or READER_URL in the conf file)
#   points at a self-hosted reader; RESEARCH_READER / READER=off|auto|force sets the default mode.

READER_DEFAULT = "https://r.jina.ai/"
JS_HINT = re.compile(
    r"(enable|enabled|requires?|required|must|disabled|turn on|activate|omoguci|ukljuc|aktivier|activez|habilit)[^.\n]{0,60}javascript"
    r"|javascript[^.\n]{0,60}(required|disabled|not enabled|needed|must|is off|deaktiv)", re.I)
SPA_SHELL = re.compile(
    r"<div[^>]+id=[\"'](?:root|app|__next|__nuxt|svelte|q-app)[\"'][^>]*>\s*</div>|<app-root|ng-version=|data-reactroot", re.I)
SECRET_QS = re.compile(r"[?&](token|access_token|id_token|api_?key|key|sig|signature|auth|password|passwd|session|sessionid|secret)=", re.I)
READER_ERR = re.compile(
    r"target url returned error|access denied|forbidden|captcha|just a moment|enable javascript and cookies|attention required"
    r"|are you a robot|too many requests|rate limit|checking your browser", re.I)


def js_signals(raw, visible, n_scripts, script_bytes, hint_text):
    """Reasons to believe the page's real content is rendered by JavaScript. Empty list = looks like normal HTML."""
    reasons = []
    if JS_HINT.search(hint_text) and visible < 2000:
        reasons.append("page tells the visitor that JavaScript is required")
    if visible < 500 and (n_scripts >= 2 or script_bytes > 3000 or (visible < 150 and n_scripts >= 1)):
        reasons.append(f"only {visible} characters of text but {n_scripts} script tag(s) ({script_bytes // 1024} KB)")
    if SPA_SHELL.search(raw) and visible < 800:
        reasons.append("empty single-page-app shell (framework root element with almost no text)")
    if script_bytes > 100_000 and script_bytes > 100 * max(visible, 1) and visible < 1500:
        reasons.append(f"{script_bytes // 1024} KB of scripts against {visible} characters of text")
    return reasons


def reader_base():
    return os.environ.get("RESEARCH_READER_URL") or CONF.get("READER_URL") or READER_DEFAULT


def private_target(url):
    """Why this URL must not be sent to a public third-party service ('' = fine)."""
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if u.username or u.password:
        return "URL contains credentials"
    if SECRET_QS.search(url):
        return "URL carries a token, key or signature"
    if not host or "." not in host or host == "localhost" or host.endswith(
            (".local", ".lan", ".internal", ".home.arpa", ".localdomain", ".corp", ".intranet")):
        return "local/internal host name"
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return "private IP address"
    except ValueError:
        pass
    return ""


def call_reader(target, base, key):
    import httpx
    headers = {"X-Respond-With": "markdown", "X-Timeout": "45", "User-Agent": UAS[0]}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    with httpx.Client(follow_redirects=True, timeout=100, headers=headers) as c:
        if "#" in target:  # hash routes never reach a server in a GET: the reader takes the URL in a POST body
            r = c.post(base, data={"url": target})
        else:
            r = c.get(base + target)
    return r.status_code, r.text


def parse_reader(text):
    """Split Jina's 'Title: / URL Source: / Markdown Content:' preamble from the markdown body."""
    lines = text.splitlines()
    title, start = "", 0
    for i, line in enumerate(lines[:15]):
        m = re.match(r"^Title:\s*(.*)$", line)
        if m:
            title = m.group(1).strip()
        if line.strip().lower().startswith("markdown content:"):
            start = i + 1
            rest = line.split(":", 1)[1].strip()
            if rest:
                lines[i] = rest
                start = i
            break
    body = "\n".join(lines[start:])
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return title, body


def maybe_reader(src, final_url, a, res):
    """Decide whether to re-fetch a web page through Jina Reader and, if the result is better, swap it in."""
    mode = a.reader
    local_chars = sum(len(t) for _, _, t in res.parts)
    reasons = list(res.js_reasons)
    missing = [e for e in a.expect if norm(e) not in res.text_norm]
    if missing:
        reasons.append("expected text not found by standard extraction: " + ", ".join(repr(m) for m in missing))
    if mode == "off":
        if reasons:
            res.warnings.append("page looks JavaScript-rendered (" + "; ".join(reasons) + ") but --reader is off: content may be incomplete; "
                                "try render_page <url> --ocr for a local browser screenshot")
        return
    if not reasons and mode != "force":
        return
    base = reader_base()
    public = base.rstrip("/") == READER_DEFAULT.rstrip("/")
    target = final_url
    if "#" in src and "#" not in final_url:
        target = final_url + "#" + src.split("#", 1)[1]
    info = {"attempted": True, "reasons": reasons or ["--reader force"], "endpoint": urlparse(base).netloc, "local_chars": local_chars}
    res.reader = info
    if public:
        why = private_target(target)
        if why:
            info.update(attempted=False, skipped=why)
            res.warnings.append(f"page looks JavaScript-rendered ({'; '.join(reasons)}) but was NOT sent to the public reader: {why}. "
                                "Use render_page <url> --ocr, or a self-hosted reader (RESEARCH_READER_URL)")
            return
    key = os.environ.get("JINA_API_KEY", "")
    try:
        status, text = call_reader(target, base, key)
    except Exception as e:  # noqa: BLE001
        info.update(failed=f"{type(e).__name__}: {e}")
        res.warnings.append(f"Jina Reader request failed ({type(e).__name__}); kept the standard extraction, which may be incomplete. "
                            "Try render_page <url> --ocr")
        return
    title, body = parse_reader(text)
    head = body[:600]
    if status >= 400:
        info.update(failed=f"HTTP {status}")
        res.warnings.append(f"Jina Reader returned HTTP {status}" + (" (rate limit: set JINA_API_KEY)" if status in (402, 429) else "")
                            + "; kept the standard extraction, which may be incomplete. Try render_page <url> --ocr")
        return
    if len(body) < 1500 and READER_ERR.search(text[:800]):
        info.update(failed="reader returned an error or challenge page")
        res.warnings.append("Jina Reader returned an error/challenge page instead of the content; kept the standard extraction. "
                            "Try render_page <url> --ocr")
        return
    rn = norm(body)
    found_local = sum(1 for e in a.expect if norm(e) in res.text_norm)
    found_reader = sum(1 for e in a.expect if norm(e) in rn)
    info["reader_chars"] = len(body)
    better = found_reader > found_local or len(body) >= max(300, 2 * local_chars)
    if not better:
        info.update(used=False, rejected="reader result not clearly better than the standard extraction")
        res.warnings.append(f"Jina Reader was tried but did not return clearly more content ({len(body)} vs {local_chars} chars); kept the standard extraction")
        return
    # swap in the reader result
    res.local_parts = list(res.parts)
    res.parts = []
    blocks = [b.strip() for b in re.split(r"\n\s*\n", body) if b.strip()]
    for n, txt in enumerate(chunk_blocks(blocks), start=1):
        res.parts.append(("PART", str(n), txt))
    res.outline = [("  " * (len(m.group(1)) - 1)) + m.group(2).strip() for m in re.finditer(r"^(#{1,6})\s+(.+)$", body, re.M)]
    links = re.findall(r"(?<!!)\[([^\]]+)\]\((https?://[^)\s]+)", body)
    res.links = [f"{t.strip()[:120]}\t{u}" for t, u in links]
    res.method = "Jina Reader markdown (page rendered remotely)" + (f"; title: {title[:80]}" if title else "")
    res.warnings = [w for w in res.warnings if not w.startswith(("no text extracted", "very little text"))]
    res.warnings.append("content comes from Jina Reader (third-party remote rendering of this URL): tables and layout are flattened to markdown, "
                        "so verify key figures with render_page <url>")
    still = [e for e in a.expect if norm(e) not in rn]
    if still:
        res.warnings.append("expected text still not found after Jina Reader: " + ", ".join(repr(e) for e in still)
                            + " (the page may need a login or user action)")
    info.update(used=True, rejected=None)


# ---------------------------------------------------------------- main flow

def process(src, a):
    t0 = time.time()
    is_url = bool(re.match(r"^https?://", src, re.I))
    url = src if is_url else ""
    errors = []
    if is_url:
        data, fname, ctype, final_url, errors = download(src, a.archive)
        if data is None:
            return None, errors
        url = final_url
    else:
        p = Path(src).expanduser()
        if not p.exists():
            return None, [f"file not found: {src}"]
        data, fname, ctype = p.read_bytes(), p.name, mimetypes.guess_type(p.name)[0] or ""
    kind = sniff_type(data, fname, ctype)
    if kind == "binary":
        return None, [f"unsupported/unknown binary format ({fname or ctype or 'no name'}); convert it to PDF/DOCX/XLSX first"]

    base = a.name or slugify(Path(fname).stem if fname else (urlparse(url).netloc + "-" + Path(urlparse(url).path).stem))
    name = base
    if not a.force and (doc_dir(name) / "manifest.json").exists():
        try:
            old = json.loads((doc_dir(name) / "manifest.json").read_text())
        except Exception:  # noqa: BLE001
            old = {}
        if old.get("source") == (url or str(src)):
            print(f"CACHED  {name} (already extracted; use --force to redo)")
            print_summary(name, old)
            return name, []
        n = 2
        while (doc_dir(name) / "manifest.json").exists():
            name = f"{base}-{n}"
            n += 1
    d = doc_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    ext = Path(fname).suffix.lower() if fname and Path(fname).suffix else TYPE_EXT.get(kind, ".bin")
    if kind in ("pdf", "docx", "xlsx", "pptx"):
        ext = TYPE_EXT[kind]
    orig = d / f"original{ext}"
    orig.write_bytes(data)

    res = Result()
    try:
        if kind == "pdf":
            extract_pdf(orig, a, res)
        elif kind == "docx":
            extract_docx(orig, a, res)
        elif kind == "xlsx":
            extract_xlsx(orig, a, res)
        elif kind == "pptx":
            extract_pptx(orig, a, res)
        elif kind == "html":
            extract_html(data, url, a, res)
        elif kind == "image":
            extract_image(orig, a, res)
        else:
            extract_text(data, a, res, kind)
    except Exception as e:  # noqa: BLE001
        return None, [f"extraction failed for {kind}: {type(e).__name__}: {e}"]

    expected = {".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx", ".xlsm": "xlsx", ".pptx": "pptx"}.get(Path(fname).suffix.lower()) if fname else None
    if expected and kind != expected:
        res.warnings.insert(0, f"TYPE MISMATCH: name says {expected} but the content is {kind}: probably an error, login or access-denied page, or a corrupt download. Do NOT treat this as the document")

    if kind == "html" and is_url:
        maybe_reader(src, url, a, res)
        if res.local_parts is not None:
            (d / "text_local.txt").write_text("\n".join(f"=== PART {l} ===\n{t}" for _, l, t in res.local_parts) + "\n", encoding="utf-8")

    header = f"# SOURCE: {name} | {url or src} | type={kind} | fetched={datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')}"
    body = [header]
    for k, label, text in res.parts:
        body.append(f"\n=== {k} {label} ===")
        body.append(text)
    (d / "text.txt").write_text("\n".join(body) + "\n", encoding="utf-8")
    if res.outline:
        (d / "outline.txt").write_text("\n".join(res.outline) + "\n", encoding="utf-8")
    if res.links:
        (d / "links.txt").write_text("\n".join(dict.fromkeys(res.links)) + "\n", encoding="utf-8")
    chars = sum(len(t) for _, _, t in res.parts)
    if chars < 200:
        res.warnings.append("extracted text is very short: the document may be scanned, empty or protected")
    manifest = {
        "name": name, "source": url or str(src), "type": kind, "bytes": len(data),
        "units": len(res.parts), "pages": res.pages, "chars": chars, "method": res.method,
        "ocr_pages": res.ocr_pages, "warnings": res.warnings, "has_outline": bool(res.outline),
        "has_links": bool(res.links), "seconds": round(time.time() - t0, 1),
    }
    if res.reader:
        manifest["reader"] = res.reader
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print_summary(name, manifest)
    return name, []


def print_summary(name, m):
    units = m.get("pages") or m.get("units")
    print(f"OK  {name}  type={m['type']}  units={units}  chars={m['chars']}  size={m['bytes'] // 1024}KB")
    print(f"    method: {m['method']}")
    if m.get("ocr_pages"):
        print(f"    OCR used on: {_ranges(m['ocr_pages'])}")
    rd = m.get("reader")
    if rd and rd.get("used"):
        print(f"    reader: Jina Reader USED ({'; '.join(rd.get('reasons', []))}); standard extraction had {rd.get('local_chars')} chars, "
              f"reader {rd.get('reader_chars')}; standard text kept in text_local.txt")
    for w in m.get("warnings", []):
        print(f"    WARN: {w}")
    print(f"    text:   {doc_dir(name) / 'text.txt'}")
    extras = []
    if m.get("has_outline"):
        extras.append(f"doc_search -d {name} --outline")
    if m.get("has_links"):
        extras.append(f"less {doc_dir(name) / 'links.txt'}   (links on the page)")
    print(f"    next:   doc_search -d {name} \"<terms>\"   |   doc_search -d {name} --at 1" + ("   |   " + "   |   ".join(extras) if extras else ""))


FALLBACKS = """\
Fetch failed. Before giving up, try in this order:
  1. same URL with --archive (Wayback Machine snapshot)
  2. search the web for the exact filename / title with site:<domain>, then try other hosts, subdomains, mirrors
  3. the page that links to the file (fetch it as HTML and read links.txt)
  4. ask the user to attach the file
Report the document as NOT READ in the coverage table if all fail."""


def main():
    ap = argparse.ArgumentParser(description="Download/open documents and extract text with location markers.")
    ap.add_argument("sources", nargs="+", help="URL(s) or file path(s)")
    ap.add_argument("--name", help="short name for the document (only with a single source)")
    ap.add_argument("--ocr", choices=["auto", "off", "force"], default="auto", help="auto = OCR pages/images with little or no text (default)")
    ap.add_argument("--lang", default=ocr_langs(), help="tesseract languages, e.g. eng+hrv (default from config)")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--archive", action="store_true", help="also try a Wayback Machine snapshot if the URL fails")
    ap.add_argument("--no-tables", action="store_true", help="skip PDF table detection")
    ap.add_argument("--force", action="store_true", help="re-extract even if already cached")
    ap.add_argument("--reader", choices=["auto", "off", "force"], default=os.environ.get("RESEARCH_READER") or CONF.get("READER") or "auto",
                    help="Jina Reader for web pages: auto = only if the page looks JavaScript-rendered or --expect text is missing (default); "
                         "off = never; force = always (web pages only, never documents)")
    ap.add_argument("--expect", action="append", default=[], metavar="TEXT",
                    help="text you expect on a web page (repeatable); if the standard extraction lacks it, the reader is tried")
    a = ap.parse_args()
    if a.name and len(a.sources) > 1:
        ap.error("--name works with a single source")
    failed = 0
    for s in a.sources:
        name, errs = process(s, a)
        if name is None:
            failed += 1
            print(f"FAIL  {s}")
            for e in errs:
                print(f"    {e}")
            print(FALLBACKS)
    sys.exit(2 if failed else 0)


if __name__ == "__main__":
    main()
