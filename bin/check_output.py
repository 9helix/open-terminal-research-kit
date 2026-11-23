#!/usr/bin/env python3
"""check_output: validate a generated file before handing it to the user.

  check_output ~/work/out/report.docx            structure, placeholders, rendered page count, blank pages
  check_output ~/work/out/model.xlsx             recalculates with LibreOffice and scans for #REF!/#DIV/0!/...
  check_output ~/work/out/deck.pptx --render     off-slide and overlapping shapes, empty slides, PNG renders
  check_output ~/work/out/diagram.bpmn           XML well-formedness, overlapping/negative shape bounds
  also: .pdf .xml .svg .html .json .csv .md .txt

Prints PASS / WARN / FAIL lines; exit code 1 on FAIL. WARN means "look at it", not "broken".
--render writes PNG pages to $RESEARCH_HOME/scratch/renders/ so they can be viewed or OCR'd with render_page.
"""
import argparse
import csv
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent.parent / "lib"), "/usr/local/lib/research_kit"]
from research_common import RENDERS, browser_label, ensure_workspace, have, launch_chromium, slugify  # noqa: E402

PLACEHOLDER = re.compile(r"(lorem ipsum|\bTODO\b|\bTBD\b|\bXXX+\b|\[(?:insert|placeholder|your)[^\]]*\]|\{\{[^}]+\}\}|<<[^>]+>>)", re.I)
XL_ERRORS = ("#REF!", "#DIV/0!", "#NAME?", "#VALUE!", "#N/A", "#NULL!", "#NUM!")


class Report:
    def __init__(self):
        self.fails, self.warns = 0, 0

    def ok(self, msg):
        print(f"PASS  {msg}")

    def warn(self, msg):
        self.warns += 1
        print(f"WARN  {msg}")

    def fail(self, msg):
        self.fails += 1
        print(f"FAIL  {msg}")

    def info(self, msg):
        print(f"INFO  {msg}")


def soffice_convert(path, fmt, outdir):
    exe = "soffice" if have("soffice") else ("libreoffice" if have("libreoffice") else None)
    if not exe:
        return None
    profile = Path(outdir) / "lo_profile"
    subprocess.run([exe, f"-env:UserInstallation=file://{profile}", "--headless", "--convert-to", fmt, "--outdir", str(outdir), str(path)],
                   capture_output=True, text=True, timeout=240)
    res = Path(outdir) / (Path(path).stem + "." + fmt.split(":")[0])
    return res if res.exists() else None


def check_pdf_pages(pdf, rep, render, label):
    import pymupdf
    doc = pymupdf.open(pdf)
    blank = []
    for i, page in enumerate(doc, start=1):
        if len(page.get_text().strip()) < 5 and not page.get_images():
            blank.append(i)
        if render:
            RENDERS.mkdir(parents=True, exist_ok=True)
            page.get_pixmap(dpi=80).save(str(RENDERS / f"{label}-check-p{i}.png"))
    rep.info(f"rendered to {len(doc)} page(s)")
    if blank:
        rep.warn(f"blank-looking pages: {blank}")
    else:
        rep.ok("no blank pages")
    if render:
        rep.info(f"page images in {RENDERS} ({label}-check-p*.png)")
    return len(doc)


def check_docx(path, rep, render):
    from docx import Document
    d = Document(path)
    text = "\n".join(p.text for p in d.paragraphs)
    for t in d.tables:
        for row in t.rows:
            text += "\n" + " ".join(c.text for c in row.cells)
    rep.info(f"{len(d.paragraphs)} paragraphs, {len(d.tables)} tables, {len(d.inline_shapes)} inline images, {len(d.sections)} sections")
    if len(text.strip()) < 50:
        rep.fail("document has almost no text")
    empty_heads = [p for p in d.paragraphs if p.style is not None and p.style.name.lower().startswith("heading") and not p.text.strip()]
    if empty_heads:
        rep.warn(f"{len(empty_heads)} empty heading paragraph(s)")
    ph = sorted(set(m.group(0) for m in PLACEHOLDER.finditer(text)))
    if ph:
        rep.warn(f"placeholder-like text found: {ph[:8]}")
    else:
        rep.ok("no placeholder text")
    with tempfile.TemporaryDirectory() as td:
        pdf = soffice_convert(path, "pdf", td)
        if pdf:
            check_pdf_pages(pdf, rep, render, slugify(Path(path).stem))
        else:
            rep.warn("LibreOffice unavailable: layout/page count not checked")


def check_xlsx(path, rep, render):
    import openpyxl
    wb = openpyxl.load_workbook(path)
    formulas = 0
    for ws in wb.worksheets:
        n = 0
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("="):
                    n += 1
        formulas += n
        rep.info(f"sheet '{ws.title}': {ws.max_row}x{ws.max_column}, {n} formulas")
        if ws.max_row <= 1 and ws.max_column <= 1 and ws.cell(1, 1).value is None:
            rep.warn(f"sheet '{ws.title}' is empty")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in"
        src.mkdir()
        copy = src / Path(path).name
        copy.write_bytes(Path(path).read_bytes())
        out = Path(td) / "out"
        out.mkdir()
        conv = soffice_convert(copy, "xlsx", out)
        values = None
        if conv:
            values = openpyxl.load_workbook(conv, data_only=True)
            rep.ok("recalculated with LibreOffice")
        else:
            values = openpyxl.load_workbook(path, data_only=True)
            rep.warn("LibreOffice unavailable: using cached values only (formulas written by openpyxl have none)")
        errors, empty_formula = [], []
        for ws in values.worksheets:
            f_ws = wb[ws.title] if ws.title in wb.sheetnames else None
            for row in ws.iter_rows():
                for c in row:
                    v = c.value
                    if isinstance(v, str) and (v in XL_ERRORS or v.startswith("Err:")):
                        errors.append(f"{ws.title}!{c.coordinate}={v}")
                    elif v is None and f_ws is not None:
                        fv = f_ws[c.coordinate].value
                        if isinstance(fv, str) and fv.startswith("="):
                            empty_formula.append(f"{ws.title}!{c.coordinate}")
        if errors:
            rep.fail(f"{len(errors)} formula error(s): {errors[:15]}")
        else:
            rep.ok(f"no formula errors ({formulas} formulas checked)")
        if empty_formula:
            rep.warn(f"{len(empty_formula)} formula cell(s) evaluate to empty: {empty_formula[:10]}")
    if render:
        with tempfile.TemporaryDirectory() as td:
            pdf = soffice_convert(path, "pdf", td)
            if pdf:
                check_pdf_pages(pdf, rep, True, slugify(Path(path).stem))


def check_pptx(path, rep, render):
    from pptx import Presentation
    prs = Presentation(path)
    W, H = prs.slide_width, prs.slide_height
    rep.info(f"{len(prs.slides)} slides, {W}x{H} EMU")
    problems = 0
    for i, s in enumerate(prs.slides, start=1):
        boxes = []
        has_content = False
        for sh in s.shapes:
            if sh.left is None or sh.width is None:
                continue
            l, t, r, b = sh.left, sh.top, sh.left + sh.width, sh.top + sh.height
            if sh.has_text_frame and sh.text_frame.text.strip() or sh.shape_type == 13:
                has_content = True
            if l < 0 or t < 0 or r > W or b > H:
                rep.warn(f"slide {i}: shape '{sh.name}' extends beyond the slide")
                problems += 1
            if sh.has_text_frame and sh.text_frame.text.strip():
                boxes.append((sh.name, l, t, r, b))
        for x in range(len(boxes)):
            for y in range(x + 1, len(boxes)):
                a, b2 = boxes[x], boxes[y]
                ix = max(0, min(a[3], b2[3]) - max(a[1], b2[1]))
                iy = max(0, min(a[4], b2[4]) - max(a[2], b2[2]))
                small = min((a[3] - a[1]) * (a[4] - a[2]), (b2[3] - b2[1]) * (b2[4] - b2[2])) or 1
                if ix * iy / small > 0.15:
                    rep.warn(f"slide {i}: text boxes '{a[0]}' and '{b2[0]}' overlap")
                    problems += 1
        if not has_content:
            rep.warn(f"slide {i} has no text or pictures")
            problems += 1
    if not problems:
        rep.ok("no off-slide shapes, overlaps or empty slides")
    with tempfile.TemporaryDirectory() as td:
        pdf = soffice_convert(path, "pdf", td)
        if pdf:
            check_pdf_pages(pdf, rep, render, slugify(Path(path).stem))
        else:
            rep.warn("LibreOffice unavailable: text overflow not checked")


def localname(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def check_xml(path, rep, render):
    from lxml import etree
    try:
        tree = etree.parse(str(path))
    except etree.XMLSyntaxError as e:
        rep.fail(f"not well-formed XML: {e}")
        return
    root = tree.getroot()
    rep.ok(f"well-formed XML, root <{localname(root.tag)}>, {sum(1 for _ in root.iter())} elements")
    ids = {}
    for el in root.iter():
        i = el.get("id")
        if i:
            ids.setdefault(i, 0)
            ids[i] += 1
    dups = [k for k, v in ids.items() if v > 1]
    if dups:
        rep.fail(f"duplicate id values: {dups[:10]}")
    shapes = []
    for el in root.iter():
        if localname(el.tag) == "Bounds":
            try:
                x, y, w, h = (float(el.get(k)) for k in ("x", "y", "width", "height"))
            except (TypeError, ValueError):
                continue
            parent = el.getparent()
            pname = localname(parent.tag) if parent is not None else ""
            ref = (parent.get("bpmnElement") or parent.get("id") or pname) if parent is not None else "?"
            if x < 0 or y < 0:
                rep.warn(f"negative coordinates for {ref}: x={x} y={y}")
            if pname.endswith("Shape"):
                shapes.append((ref, x, y, x + w, y + h))
    if shapes:
        bad = 0
        for i in range(len(shapes)):
            for j in range(i + 1, len(shapes)):
                a, b = shapes[i], shapes[j]
                ix = min(a[3], b[3]) - max(a[1], b[1])
                iy = min(a[4], b[4]) - max(a[2], b[2])
                if ix > 0 and iy > 0:
                    a_in_b = a[1] >= b[1] and a[2] >= b[2] and a[3] <= b[3] and a[4] <= b[4]
                    b_in_a = b[1] >= a[1] and b[2] >= a[2] and b[3] <= a[3] and b[4] <= a[4]
                    if not (a_in_b or b_in_a):
                        rep.warn(f"shapes overlap without containment: {a[0]} / {b[0]}")
                        bad += 1
        if not bad:
            rep.ok(f"{len(shapes)} diagram shapes, no partial overlaps")
    if localname(root.tag) == "svg" or Path(path).suffix.lower() == ".svg":
        render_web(Path(path), rep, render)


def render_web(path, rep, render):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        rep.warn("playwright not installed: page not rendered")
        return
    errs = []
    try:
        with sync_playwright() as p:
            b = launch_chromium(p)
            rep.info(f"browser: {browser_label()}")
            pg = b.new_page(viewport={"width": 1280, "height": 900})
            pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(path.resolve().as_uri(), wait_until="load", timeout=60000)
            if render:
                RENDERS.mkdir(parents=True, exist_ok=True)
                out = RENDERS / f"{slugify(path.stem)}-check.png"
                pg.screenshot(path=str(out), full_page=True)
                rep.info(f"screenshot: {out}")
            b.close()
    except RuntimeError as e:
        rep.warn(f"{e}; page not rendered")
        return
    if errs:
        rep.fail(f"browser console errors: {errs[:5]}")
    else:
        rep.ok("rendered in headless Chromium without console errors")


def check_html(path, rep, render):
    from lxml import html
    try:
        doc = html.parse(str(path))
    except Exception as e:  # noqa: BLE001
        rep.fail(f"cannot parse HTML: {e}")
        return
    rep.ok(f"parsed HTML, {sum(1 for _ in doc.getroot().iter())} elements")
    txt = doc.getroot().text_content()
    ph = sorted(set(m.group(0) for m in PLACEHOLDER.finditer(txt)))
    if ph:
        rep.warn(f"placeholder-like text found: {ph[:8]}")
    render_web(path, rep, render)


def check_pdf(path, rep, render):
    import pymupdf
    try:
        doc = pymupdf.open(path)
    except Exception as e:  # noqa: BLE001
        rep.fail(f"cannot open PDF: {e}")
        return
    rep.info(f"{len(doc)} pages")
    check_pdf_pages(path, rep, render, slugify(Path(path).stem))


def check_json(path, rep, render):
    try:
        json.loads(Path(path).read_text(encoding="utf-8"))
        rep.ok("valid JSON")
    except Exception as e:  # noqa: BLE001
        rep.fail(f"invalid JSON: {e}")


def check_csv(path, rep, render):
    rows = list(csv.reader(Path(path).open(encoding="utf-8", errors="replace", newline="")))
    if not rows:
        rep.fail("empty CSV")
        return
    widths = {len(r) for r in rows if r}
    rep.info(f"{len(rows)} rows, column counts: {sorted(widths)}")
    if len(widths) > 1:
        rep.warn("rows have different column counts")
    else:
        rep.ok("consistent column count")


def check_text(path, rep, render):
    txt = Path(path).read_text(encoding="utf-8", errors="replace")
    if len(txt.strip()) < 10:
        rep.fail("file is (almost) empty")
    else:
        rep.ok(f"{len(txt)} characters")
    ph = sorted(set(m.group(0) for m in PLACEHOLDER.finditer(txt)))
    if ph:
        rep.warn(f"placeholder-like text found: {ph[:8]}")


HANDLERS = {".docx": check_docx, ".xlsx": check_xlsx, ".xlsm": check_xlsx, ".pptx": check_pptx, ".pdf": check_pdf,
            ".xml": check_xml, ".bpmn": check_xml, ".svg": check_xml, ".drawio": check_xml,
            ".html": check_html, ".htm": check_html, ".json": check_json, ".csv": check_csv,
            ".md": check_text, ".txt": check_text}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--render", action="store_true", help="also write PNG renders of pages/slides/screenshots")
    a = ap.parse_args()
    ensure_workspace()
    exit_code = 0
    for f in a.files:
        p = Path(f).expanduser()
        rep = Report()
        print(f"== {p}")
        if not p.exists() or p.stat().st_size == 0:
            rep.fail("file missing or empty")
        else:
            rep.info(f"{p.stat().st_size // 1024 or 1} KB")
            h = HANDLERS.get(p.suffix.lower())
            if h is None:
                rep.warn(f"no checker for '{p.suffix}'; only existence was verified")
            else:
                try:
                    h(p, rep, a.render)
                except Exception as e:  # noqa: BLE001
                    rep.fail(f"checker crashed: {type(e).__name__}: {e} (the file may be corrupt)")
        result = "FAIL" if rep.fails else (f"PASS with {rep.warns} warning(s)" if rep.warns else "PASS")
        print(f"RESULT: {result}")
        if rep.fails:
            exit_code = 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
