#!/usr/bin/env python3
"""research_selftest: end-to-end check of the toolkit in a throwaway workspace.

Creates sample PDF/DOCX/XLSX/PPTX/HTML files (one PDF page is an image only), serves them from a local HTTP
server, and runs fetch_doc, doc_search, render_page and check_output against them. Prints PASS/FAIL per test.
"""
import http.server
import os
import urllib.parse
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIN = [str(HERE)] if (HERE / "fetch_doc.py").exists() else []
RESULTS = []


def tool(name):
    for d in BIN:
        p = Path(d) / f"{name}.py"
        if p.exists():
            return [sys.executable, str(p)]
    return [shutil.which(name) or name]


def run(name, *args, env=None):
    r = subprocess.run(tool(name) + list(args), capture_output=True, text=True, env=env, timeout=600)
    return r.returncode, r.stdout + r.stderr


def check(label, cond, detail=""):
    RESULTS.append(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f"\n      {detail[:400]}" if (detail and not cond) else ""))


def make_samples(d):
    import pymupdf
    from docx import Document
    from openpyxl import Workbook
    from PIL import Image, ImageDraw, ImageFont
    from pptx import Presentation

    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((72, 80), "Regulation on Examples", fontsize=16)
    p1.insert_text((72, 120), "Article 5", fontsize=12)
    p1.insert_text((72, 140), "The application deadline is 15 June.", fontsize=11)
    p1.insert_text((72, 180), "Article 6", fontsize=12)
    p1.insert_text((72, 200), "Appeals are decided by the committee within 30 days.", fontsize=11)
    p1.insert_text((72, 240), "Article 7", fontsize=12)
    p1.insert_text((72, 260), "Fees are paid in advance.", fontsize=11)
    p2 = doc.new_page()
    p2.insert_text((72, 80), "Clanak 9", fontsize=12)
    p2.insert_text((72, 100), "Zalba se podnosi u roku od 15 dana.", fontsize=11)
    # image-only page
    im = Image.new("RGB", (1200, 400), "white")
    dr = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 48)
    except OSError:
        font = ImageFont.load_default()
    dr.text((40, 60), "Scholarship amount 2997 EUR", fill="black", font=font)
    dr.text((40, 160), "Table row: travel 275 EUR", fill="black", font=font)
    png = d / "scan.png"
    im.save(png)
    p3 = doc.new_page()
    p3.insert_image(pymupdf.Rect(36, 36, 560, 220), filename=str(png))
    doc.save(d / "regulation.pdf")

    dd = Document()
    dd.add_heading("Guidelines", 1)
    dd.add_paragraph("The change deadline is 5 weeks before the start.")
    t = dd.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Item", "Limit"
    t.cell(1, 0).text, t.cell(1, 1).text = "Credits", "30 ECTS recommended"
    dd.save(d / "guidelines.docx")

    wb = Workbook()
    ws = wb.active
    ws.title = "Partners"
    ws.append(["Institution", "Country", "Places"])
    ws.append(["University of Examples", "Croatia", 4])
    ws.append(["Institute of Tests", "Austria", 2])
    wb.save(d / "partners.xlsx")

    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Overview"
    s.placeholders[1].text = "Deadline 15 November"
    prs.save(d / "deck.pptx")

    (d / "page.html").write_text(
        "<html><body><h1>Call for applications</h1><p>See the <a href='regulation.pdf'>regulation</a> and "
        "<a href='supplement.pdf'>supplement</a>.</p><table><tr><td>Deadline</td><td>15 June</td></tr></table></body></html>")
    (d / "bad.xlsx").write_bytes(b"not a real workbook")
    shell = ('<html><head><title>App</title></head><body><div id="root"></div><script src="/app.js"></script>'
             '<noscript>You need to enable JavaScript to run this app.</noscript></body></html>')
    (d / "spa.html").write_text(shell)
    (d / "spa-bad.html").write_text(shell)


def main():
    work = Path(tempfile.mkdtemp(prefix="research-selftest-"))
    samples = work / "samples"
    samples.mkdir()
    env = dict(os.environ, RESEARCH_HOME=str(work / "home"))
    os.environ["RESEARCH_HOME"] = env["RESEARCH_HOME"]
    print(f"workspace: {work}")
    make_samples(samples)

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(samples), **k)

        def log_message(self, *a):
            pass

    HITS = []
    GOOD = ("Title: Dashboard App\n\nURL Source: {t}\n\nMarkdown Content:\n# Dashboard\n\n"
            + "Quarterly figures: Q1 100, Q2 120, Q3 140, Q4 160. " * 12
            + "\n\n![Image 1: logo](http://example.org/logo.png)\n\n[Reports](https://example.org/reports)\n")
    BAD = ("Title: Just a moment...\n\nURL Source: {t}\n\nWarning: Target URL returned error 403: Forbidden\n\n"
           "Markdown Content:\nJust a moment...\n")

    class Reader(http.server.BaseHTTPRequestHandler):
        def _reply(self, target):
            HITS.append({"method": self.command, "target": target, "auth": self.headers.get("Authorization", ""),
                         "respond": self.headers.get("X-Respond-With", "")})
            body = (BAD if "spa-bad" in target else GOOD).format(t=target)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

        def do_GET(self):
            self._reply(self.path[1:])

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            data = self.rfile.read(n).decode()
            self._reply(urllib.parse.unquote_plus(data.split("=", 1)[1]))

        def log_message(self, *a):
            pass

    rsrv = socketserver.TCPServer(("127.0.0.1", 0), Reader)
    threading.Thread(target=rsrv.serve_forever, daemon=True).start()
    env["RESEARCH_READER_URL"] = f"http://127.0.0.1:{rsrv.server_address[1]}/"
    env["JINA_API_KEY"] = "test-key-123"

    srv = socketserver.TCPServer(("127.0.0.1", 0), Quiet)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    rc, out = run("fetch_doc", f"{base}/regulation.pdf", "--name", "reg", "--lang", "eng", env=env)
    check("fetch_doc: PDF from URL", rc == 0 and "type=pdf" in out and "units=3" in out, out)
    check("fetch_doc: OCR used on image-only page", "OCR used on: 3" in out, out)
    rc, out = run("fetch_doc", str(samples / "guidelines.docx"), "--name", "guide", env=env)
    check("fetch_doc: DOCX (headings, table)", rc == 0 and "type=docx" in out, out)
    rc, out = run("fetch_doc", str(samples / "partners.xlsx"), "--name", "partners", env=env)
    check("fetch_doc: XLSX", rc == 0 and "type=xlsx" in out, out)
    rc, out = run("fetch_doc", str(samples / "deck.pptx"), "--name", "deck", env=env)
    check("fetch_doc: PPTX", rc == 0 and "type=pptx" in out, out)
    rc, out = run("fetch_doc", f"{base}/page.html", "--name", "page", env=env)
    check("fetch_doc: HTML + links", rc == 0 and "links" in out, out)
    rc, out = run("fetch_doc", f"{base}/missing.pdf", env=env)
    check("fetch_doc: failure prints the fallback ladder and exits 2", rc == 2 and "--archive" in out and "NOT READ" in out, out)
    rc, out = run("fetch_doc", str(samples / "bad.xlsx"), "--name", "bad", env=env)
    check("fetch_doc: file whose content does not match its extension is flagged", "TYPE MISMATCH" in out and "Traceback" not in out, out)
    rc, out = run("fetch_doc", f"{base}/regulation.pdf", "--name", "reg", env=env)
    check("fetch_doc: cache hit on repeat", "CACHED" in out, out)

    check("reader: not used for PDF/DOCX/XLSX/PPTX or an ordinary static page", not HITS, str(HITS))

    rc, out = run("fetch_doc", f"{base}/spa.html", "--name", "spa", env=env)
    check("reader: JavaScript-only page is re-fetched through the reader", "Jina Reader USED" in out and len(HITS) == 1, out + str(HITS))
    check("reader: sent as GET with markdown format and API key",
          HITS and HITS[0]["method"] == "GET" and HITS[0]["respond"] == "markdown" and HITS[0]["auth"] == "Bearer test-key-123"
          and HITS[0]["target"].endswith("/spa.html") and HITS[0]["target"].startswith("http://"), str(HITS))
    sp = Path(env["RESEARCH_HOME"]) / "sources" / "spa"
    txt = (sp / "text.txt").read_text() if (sp / "text.txt").exists() else ""
    check("reader: markdown stored with outline, links and images stripped",
          "Quarterly figures" in txt and "![Image" not in txt and (sp / "links.txt").exists() and (sp / "text_local.txt").exists(), txt[:300])
    rc, out = run("doc_search", "-d", "spa", "quarterly figures", env=env)
    check("reader: result is searchable with doc_search", "PART 1" in out, out)

    n0 = len(HITS)
    rc, out = run("fetch_doc", f"{base}/spa.html", "--name", "spa-off", "--reader", "off", env=env)
    check("reader: --reader off never contacts the reader and warns", len(HITS) == n0 and "--reader is off" in out, out)

    rc, out = run("fetch_doc", f"{base}/spa-bad.html", "--name", "spa-bad", env=env)
    check("reader: error/challenge page from the reader is rejected, standard text kept",
          len(HITS) == n0 + 1 and "Jina Reader USED" not in out and "error/challenge" in out and rc == 0, out)

    n1 = len(HITS)
    rc, out = run("fetch_doc", f"{base}/page.html", "--name", "page-expect", "--expect", "quarterly figures", env=env)
    check("reader: --expect text missing from a static page triggers the reader", len(HITS) == n1 + 1 and "Jina Reader USED" in out, out)

    rc, out = run("fetch_doc", f"{base}/spa.html#/route", "--name", "spa-hash", env=env)
    check("reader: hash-route URLs are sent as POST with the fragment", HITS[-1]["method"] == "POST" and HITS[-1]["target"].endswith("#/route"), str(HITS[-1]))

    n2 = len(HITS)
    env_pub = {k: v for k, v in env.items() if k != "RESEARCH_READER_URL"}
    rc, out = run("fetch_doc", f"{base}/spa.html", "--name", "spa-private", env=env_pub)
    check("reader: private/local hosts are never sent to the public reader", len(HITS) == n2 and "NOT sent" in out, out)

    rc, out = run("fetch_doc", f"{base}/spa.html?token=abc", "--name", "spa-token", env=env_pub)
    check("reader: URLs with tokens are never sent to the public reader", "NOT sent" in out, out)

    env_dead = dict(env, RESEARCH_READER_URL="http://127.0.0.1:1/")
    rc, out = run("fetch_doc", f"{base}/spa.html", "--name", "spa-dead", env=env_dead)
    check("reader: unreachable reader falls back to the standard extraction with a warning", rc == 0 and "request failed" in out, out)

    rc, out = run("doc_search", "--list", env=env)
    check("doc_search --list", "reg" in out and "guide" in out, out)
    rc, out = run("doc_search", "appeals committee", "-d", "reg", env=env)
    check("doc_search: finds terms with page location", "PAGE 1" in out and "30 days" in out, out)
    rc, out = run("doc_search", "zalba", "-d", "reg", env=env)
    check("doc_search: accent/case-insensitive", "PAGE 2" in out, out)
    rc, out = run("doc_search", "2997", "-d", "reg", env=env)
    check("doc_search: finds text recovered by OCR", "PAGE 3" in out, out)
    rc, out = run("doc_search", "-d", "reg", "--section", "Article 6", env=env)
    check("doc_search --section stops at next article", "30 days" in out and "Fees" not in out, out)
    rc, out = run("doc_search", "-d", "reg", "--at", "2", env=env)
    check("doc_search --at reads one page", "Zalba" in out and "Article 6" not in out, out)
    rc, out = run("doc_search", "-d", "partners", "--at", "Partners", env=env)
    check("doc_search --at <sheet name>", "Institute of Tests" in out, out)
    rc, out = run("doc_search", "-d", "guide", "ECTS", env=env)
    check("doc_search: finds text inside DOCX table", "recommended" in out, out)
    rc, out = run("doc_search", "-r", "deadline|due date", env=env)
    check("doc_search: regex across documents", "reg" in out and "guide" in out, out)
    rc, out = run("doc_search", "nonexistent-term-xyz", env=env)
    check("doc_search: zero hits message", "no hits" in out, out)

    rc, out = run("render_page", "reg", "--page", "1", "--ocr", env=env)
    check("render_page: PDF page + OCR", rc == 0 and ".png" in out and "Regulation" in out, out)
    if shutil.which("soffice") or shutil.which("libreoffice"):
        rc, out = run("render_page", str(samples / "guidelines.docx"), "--page", "1", env=env)
        check("render_page: DOCX via LibreOffice", rc == 0 and ".png" in out, out)
    else:
        print("SKIP  render_page DOCX (LibreOffice not installed)")

    for f in ("guidelines.docx", "partners.xlsx", "deck.pptx", "regulation.pdf", "page.html"):
        rc, out = run("check_output", str(samples / f), env=env)
        check(f"check_output: {f}", rc == 0 and "RESULT: PASS" in out, out)

    sysb = next((shutil.which(c) for c in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable") if shutil.which(c)), None)
    if sysb:
        rc, out = run("check_output", str(samples / "page.html"), "--render", env=dict(env, RESEARCH_BROWSER=""))
        check("check_output: renders HTML with the system browser", f"browser: {sysb}" in out and "screenshot:" in out, out)
    else:
        print("SKIP  system browser test (no Chromium/Chrome on this machine)")
    rc, out = run("check_output", str(samples / "page.html"), "--render", env=dict(env, RESEARCH_BROWSER="/nonexistent/chromium"))
    check("check_output: unusable browser gives a warning, not a crash", rc == 0 and "could not start browser" in out and "Traceback" not in out, out)

    from openpyxl import Workbook
    wb = Workbook()
    wb.active["A1"] = 1
    wb.active["A2"] = "=A1/0"
    wb.save(samples / "broken.xlsx")
    if shutil.which("soffice") or shutil.which("libreoffice"):
        rc, out = run("check_output", str(samples / "broken.xlsx"), env=env)
        check("check_output: catches #DIV/0! after recalculation", rc == 1 and "DIV/0" in out, out)
    (samples / "bad.xml").write_text("<a><b></a>")
    rc, out = run("check_output", str(samples / "bad.xml"), env=env)
    check("check_output: catches malformed XML", rc == 1, out)
    (samples / "overlap.bpmn").write_text(
        '<d xmlns:di="x"><Shape id="s1" bpmnElement="A"><Bounds x="0" y="0" width="100" height="80"/></Shape>'
        '<Shape id="s2" bpmnElement="B"><Bounds x="50" y="40" width="100" height="80"/></Shape></d>')
    rc, out = run("check_output", str(samples / "overlap.bpmn"), env=env)
    check("check_output: flags partially overlapping diagram shapes", "overlap" in out, out)

    srv.shutdown()
    rsrv.shutdown()
    shutil.rmtree(work, ignore_errors=True)
    failed = RESULTS.count(False)
    print(f"\n{len(RESULTS) - failed}/{len(RESULTS)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
