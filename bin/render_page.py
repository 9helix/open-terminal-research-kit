#!/usr/bin/env python3
"""render_page: turn a page/slide/sheet of any document into a PNG (and optionally OCR it).

  render_page NAME --page 12                 a document extracted with fetch_doc (NAME), page 12
  render_page /path/file.docx --page 1       any local PDF/DOCX/XLSX/PPTX/image/HTML file
  render_page NAME --pages 3-5 --dpi 150
  render_page NAME --page 7 --crop 0,0.4,1,1 only the lower 60% of the page (x0,y0,x1,y1 as 0-1 fractions)
  render_page NAME --page 7 --ocr            also print OCR text of the render
  render_page https://example.org/x --page 1 screenshot of a web page (needs playwright; page is ignored)

PNGs go to $RESEARCH_HOME/renders/. They are for visual checks of layout, tables and scanned content; if the
model cannot see images, use --ocr or check_output instead.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent.parent / "lib"), "/usr/local/lib/research_kit"]
from research_common import RENDERS, doc_dir, have, launch_chromium, ocr_langs, slugify  # noqa: E402


def to_pdf(path, workdir):
    """Convert office documents to PDF with LibreOffice (headless)."""
    exe = "soffice" if have("soffice") else ("libreoffice" if have("libreoffice") else None)
    if not exe:
        raise SystemExit("LibreOffice not installed: cannot render Office files (run install.sh without --no-office)")
    profile = Path(workdir) / "lo_profile"
    cmd = [exe, f"-env:UserInstallation=file://{profile}", "--headless", "--convert-to", "pdf", "--outdir", str(workdir), str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    pdf = Path(workdir) / (Path(path).stem + ".pdf")
    if not pdf.exists():
        raise SystemExit(f"LibreOffice conversion failed: {r.stderr.strip()[:300]}")
    return pdf


def screenshot_url(target, out):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("playwright is not installed (run install.sh without --no-browser)")
    try:
        with sync_playwright() as p:
            b = launch_chromium(p)
            pg = b.new_page(viewport={"width": 1280, "height": 900})
            pg.goto(target, wait_until="networkidle", timeout=60000)
            pg.screenshot(path=str(out), full_page=True)
            b.close()
    except RuntimeError as e:
        raise SystemExit(str(e))


def parse_pages(spec, total):
    spec = (spec or "1").strip()
    m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", spec)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
    elif spec.isdigit():
        lo = hi = int(spec)
    else:
        raise SystemExit("--page/--pages must be like 3 or 3-5")
    lo, hi = max(1, lo), min(total, hi)
    if lo > hi:
        raise SystemExit(f"page out of range (document has {total} pages)")
    if hi - lo > 11:
        raise SystemExit("at most 12 pages per call")
    return range(lo, hi + 1)


def ocr_file(png, langs):
    if not have("tesseract"):
        return "(tesseract not installed)"
    r = subprocess.run(["tesseract", str(png), "stdout", "-l", langs, "-c", "preserve_interword_spaces=1"],
                       capture_output=True, text=True, timeout=180)
    return r.stdout.strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="name from fetch_doc, a file path, or an http(s) URL")
    ap.add_argument("--page", "--pages", dest="page", default="1")
    ap.add_argument("--dpi", type=int, default=130)
    ap.add_argument("--crop", help="x0,y0,x1,y1 fractions (0-1)")
    ap.add_argument("--ocr", action="store_true")
    ap.add_argument("--lang", default=ocr_langs())
    ap.add_argument("--out", help="output directory (default renders dir)")
    a = ap.parse_args()

    out_dir = Path(a.out) if a.out else RENDERS
    out_dir.mkdir(parents=True, exist_ok=True)
    t = a.target
    label = slugify(Path(t).stem if not t.startswith("http") else t.split("//", 1)[1])

    if re.match(r"^https?://", t):
        out = out_dir / f"{label}-web.png"
        screenshot_url(t, out)
        print(f"{out}  (full-page screenshot)")
        if a.ocr:
            print(ocr_file(out, a.lang))
        return

    path = Path(t).expanduser()
    if not path.exists():
        cand = sorted(doc_dir(t).glob("original.*")) if doc_dir(t).exists() else []
        if not cand:
            raise SystemExit(f"'{t}' is neither a file nor an extracted document name")
        path, label = cand[0], slugify(t)

    ext = path.suffix.lower()
    with tempfile.TemporaryDirectory() as td:
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".img"):
            from PIL import Image
            im = Image.open(path).convert("RGB")
            frames = [(1, im)]
        elif ext in (".html", ".htm"):
            out = out_dir / f"{label}-html.png"
            screenshot_url(path.resolve().as_uri(), out)
            print(f"{out}  (full-page screenshot)")
            if a.ocr:
                print(ocr_file(out, a.lang))
            return
        else:
            import pymupdf
            pdf = path if ext == ".pdf" else to_pdf(path, td)
            doc = pymupdf.open(pdf)
            frames = []
            for n in parse_pages(a.page, len(doc)):
                pix = doc[n - 1].get_pixmap(dpi=a.dpi)
                from PIL import Image
                frames.append((n, Image.frombytes("RGB", (pix.width, pix.height), pix.samples)))
            if ext != ".pdf":
                print(f"(rendered via LibreOffice: page breaks may differ slightly from Word/Excel/PowerPoint; {len(doc)} pages in total)")
        for n, im in frames:
            if a.crop:
                x0, y0, x1, y1 = [float(v) for v in a.crop.split(",")]
                w, h = im.size
                im = im.crop((int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)))
            out = out_dir / f"{label}-p{n}.png"
            im.save(out)
            print(f"{out}  {im.size[0]}x{im.size[1]}px")
            if a.ocr:
                print(f"--- OCR page {n} ---")
                print(ocr_file(out, a.lang))


if __name__ == "__main__":
    main()
