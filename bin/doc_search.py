#!/usr/bin/env python3
"""doc_search: search and read documents extracted by fetch_doc, without loading them into context.

  doc_search --list                          documents available, with warnings
  doc_search "term1 term2"                   all terms within a few lines of each other, all documents
  doc_search -d NAME "exact phrase" -C 2     one document, 2 lines of context
  doc_search -d NAME -r "deadline|due date"  regular expression
  doc_search -d NAME --outline               table of contents / headings
  doc_search -d NAME --at 12                 read PAGE/SHEET/SLIDE/PART 12 (also 12-14, or a sheet name)
  doc_search -d NAME --section "Article 6"   read a whole section (heading text as written in the document)

Matching ignores case and accents (c = č = ć). Output is capped (--max-chars) so it never floods the context.
"""
import argparse
import json
import re
import shlex
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent.parent / "lib"), "/usr/local/lib/research_kit"]
from research_common import MARKER_RE, blocks_of, doc_dir, list_docs, location_of, norm, read_text  # noqa: E402

KW = ("article|section|chapter|clause|part|annex|appendix|schedule|title|rule|clanak|clan|poglavlje|odjeljak|"
      "prilog|dodatak|artikel|abschnitt|kapitel|anhang|articulo|seccion|capitulo|anexo|articolo|capitolo|sezione")
KW_HEAD = re.compile(rf"^\s*(?:#+\s*)?({KW})\.?\s*([0-9]+[a-z]?|[ivxlc]+)\b", re.I)
MD_HEAD = re.compile(r"^(#{1,6})\s+\S")
NUM_HEAD = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)]?\s+\S")
SYM_HEAD = re.compile(r"^\s*§\s*\d+")


def is_heading(line):
    n = norm(line)
    return bool(KW_HEAD.match(n) or MD_HEAD.match(line) or SYM_HEAD.match(line))


def cmd_list():
    docs = list_docs()
    if not docs:
        print("No documents yet. Use: fetch_doc <url-or-path>")
        return
    for name in docs:
        try:
            m = json.loads((doc_dir(name) / "manifest.json").read_text())
        except Exception:  # noqa: BLE001
            m = {}
        print(f"{name}  type={m.get('type', '?')}  units={m.get('pages') or m.get('units', '?')}  chars={m.get('chars', '?')}  src={m.get('source', '?')}")
        if m.get("ocr_pages"):
            print(f"    OCR pages: {len(m['ocr_pages'])}")
        for w in m.get("warnings", []):
            print(f"    WARN: {w}")


def cmd_outline(name):
    p = doc_dir(name) / "outline.txt"
    if p.exists():
        print(p.read_text(encoding="utf-8")[:12000])
        return
    lines = read_text(name)
    blocks = blocks_of(lines)
    shown = 0
    print("(no built-in outline; headings detected heuristically)")
    for i, line in enumerate(lines):
        if line.startswith("# SOURCE") or MARKER_RE.match(line):
            continue
        if is_heading(line) and len(line) < 140:
            print(f"{location_of(blocks, i):<12} L{i + 1:<6} {line.strip()}")
            shown += 1
            if shown >= 300:
                print("... (truncated)")
                break
    if not shown:
        print("no headings detected; use doc_search with terms or --at to browse")


def emit(header, text_lines, max_chars):
    text = "\n".join(text_lines)
    print(header)
    if len(text) > max_chars:
        print(text[:max_chars])
        print(f"\n[truncated: {len(text) - max_chars} more characters; narrow the request or raise --max-chars]")
    else:
        print(text)


def cmd_at(name, spec, max_chars):
    lines = read_text(name)
    blocks = blocks_of(lines)
    if not blocks:
        raise SystemExit("document has no location markers")
    spec = spec.strip()
    m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", spec)
    sel = []
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        sel = [b for b in blocks if b[1].isdigit() and lo <= int(b[1]) <= hi]
    else:
        sel = [b for b in blocks if norm(b[1]) == norm(spec)]
    if not sel:
        labels = ", ".join(b[1] for b in blocks[:40])
        raise SystemExit(f"no location '{spec}' in {name}. Available (first 40): {labels}")
    out = []
    for kind, label, s, e in sel:
        out.extend(lines[s:e])
    emit(f"[{name} | {sel[0][0]} {spec}]", out, max_chars)


def section_end(lines, start, mode):
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if MARKER_RE.match(line):
            continue
        n = norm(line)
        if mode[0] == "md":
            m = MD_HEAD.match(line)
            if m and len(m.group(1)) <= mode[1]:
                return j
        elif mode[0] == "kw":
            if KW_HEAD.match(n) or MD_HEAD.match(line) or SYM_HEAD.match(line):
                return j
        elif mode[0] == "num":
            m = NUM_HEAD.match(line)
            if m and m.group(1).count(".") + 1 <= mode[1] and len(line) < 140:
                return j
        else:
            if not line.strip() and j - start > 3:
                return j
            if j - start > 40:
                return j
    return len(lines)


def cmd_section(name, query, max_chars):
    lines = read_text(name)
    blocks = blocks_of(lines)
    q = norm(query).strip()
    pat = re.compile(rf"^\s*(?:#+\s*)?{re.escape(q)}(?![0-9a-z])")
    cands = []
    for i, line in enumerate(lines):
        if line.startswith("# SOURCE") or MARKER_RE.match(line):
            continue
        if pat.match(norm(line)):
            cands.append(i)
    if not cands:
        raise SystemExit(f"no heading starting with '{query}' in {name}. Try --outline to see exact heading text.")
    best = None
    for i in cands:
        line = lines[i]
        n = norm(line)
        md = MD_HEAD.match(line)
        if md:
            mode = ("md", len(md.group(1)))
        elif KW_HEAD.match(n) or SYM_HEAD.match(line):
            mode = ("kw", 0)
        else:
            nm = NUM_HEAD.match(line)
            mode = ("num", nm.group(1).count(".") + 1) if nm else ("loose", 0)
        end = section_end(lines, i, mode)
        span = sum(len(x) for x in lines[i:end])
        if best is None or span > best[0]:
            best = (span, i, end)
    _, i, end = best
    if len(cands) > 1:
        note = f" (picked the longest of {len(cands)} matches; others are probably table-of-contents entries)"
    else:
        note = ""
    emit(f"[{name} | {location_of(blocks, i)} | L{i + 1}-L{end}]{note}", lines[i:end], max_chars)


def cmd_search(patterns, docs, regex, exact, ctx, window, limit, max_chars):
    if not patterns:
        raise SystemExit("give search terms, or use --list / --outline / --at / --section")
    rx, terms_n = None, []
    if regex:
        rx = re.compile(patterns, 0 if exact else re.I)
    else:
        terms = shlex.split(patterns)
        if not terms:
            raise SystemExit("empty search terms")
        terms_n = [t if exact else norm(t) for t in terms]
    total, shown, chars = 0, 0, 0
    per_doc = {}
    for name in docs:
        lines = read_text(name)
        blocks = blocks_of(lines)
        norm_lines = [(l if exact else norm(l)) for l in lines]

        def hit(lo, hi):
            if regex:
                if rx.search(" ".join(lines[lo:hi])):
                    return True
                return (not exact) and bool(rx.search(" ".join(norm_lines[lo:hi])))
            joined = " ".join(norm_lines[lo:hi])
            return all(t in joined for t in terms_n)

        i = 0
        while i < len(lines):
            if lines[i].startswith("# SOURCE") or MARKER_RE.match(lines[i]):
                i += 1
                continue
            end = min(len(lines), i + window)
            if not hit(i, end):
                i += 1
                continue
            lo, hi = i, end  # tighten so the hit is reported where the terms really are
            while lo + 1 < hi and hit(lo + 1, hi):
                lo += 1
            while hi - 1 > lo and hit(lo, hi - 1):
                hi -= 1
            total += 1
            per_doc[name] = per_doc.get(name, 0) + 1
            if shown < limit and chars < max_chars:
                a, b = max(0, lo - ctx), min(len(lines), hi + ctx)
                snippet = "\n".join(f"  {k + 1:>5}| {lines[k]}" for k in range(a, b) if not MARKER_RE.match(lines[k]))
                block = f"[{name} | {location_of(blocks, lo)} | L{lo + 1}]\n{snippet}\n"
                chars += len(block)
                print(block)
                shown += 1
            i = max(hi, i + 1)
    summary = ", ".join(f"{k}:{v}" for k, v in per_doc.items()) or "none"
    print(f"-- {total} hit(s); showing {shown}. Per document: {summary}")
    if total > shown:
        print("-- more hits exist: add terms, restrict with -d, or raise -n / --max-chars")
    if total == 0:
        print("-- no hits. Try fewer or different terms, a regex (-r), or check OCR quality with --at. "
              "Absence of a hit does not prove absence in the source if the document was only partly extracted.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pattern", nargs="?", help="search terms (quote phrases) or regex with -r")
    ap.add_argument("-d", "--doc", action="append", help="document name (repeatable); default all")
    ap.add_argument("-r", "--regex", action="store_true")
    ap.add_argument("--exact", action="store_true", help="case-sensitive and accent-sensitive")
    ap.add_argument("-C", "--context", type=int, default=1, help="context lines around hits")
    ap.add_argument("-w", "--window", type=int, default=3, help="terms must appear within this many lines")
    ap.add_argument("-n", "--limit", type=int, default=15)
    ap.add_argument("--max-chars", type=int, default=6000)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--outline", action="store_true")
    ap.add_argument("--at", help="location to read: 12, 12-14, or a sheet name")
    ap.add_argument("--section", help="heading text of the section to read")
    a = ap.parse_args()

    if a.list:
        return cmd_list()
    docs = a.doc or list_docs()
    if not docs:
        raise SystemExit("No documents yet. Use: fetch_doc <url-or-path>")
    if a.outline:
        for d in docs:
            print(f"== {d} ==")
            cmd_outline(d)
        return
    if a.at or a.section:
        if len(docs) != 1:
            raise SystemExit("--at/--section need exactly one document: add -d NAME")
        return cmd_at(docs[0], a.at, a.max_chars) if a.at else cmd_section(docs[0], a.section, a.max_chars)
    cmd_search(a.pattern, docs, a.regex, a.exact, a.context, a.window, a.limit, a.max_chars)


if __name__ == "__main__":
    main()
