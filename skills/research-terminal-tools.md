---
name: research-terminal-tools
description: Reference for the document tools installed in the terminal (fetch_doc, doc_search, render_page, check_output), covering how to download and read documents with page locations, OCR scanned pages, render pages to images, and validate generated files. Load before using any of these commands.
---

# Terminal research tools

Use the terminal tool to run these commands. Workspace: `~/work/` with `sources/` (extracted documents), `out/` (files for the user), `renders/` (page images). Everything is plain text output; nothing prints a whole document.

## fetch_doc: get a document into the workspace
```
fetch_doc <url-or-path> [<url-or-path> ...] [--name short-name] [--archive] [--ocr auto|off|force] [--lang eng+hrv]
                                               [--expect "text you expect on a web page"] [--reader auto|off|force]
```
- Handles PDF, DOCX, XLSX/XLSM, PPTX, HTML, CSV/TXT/MD/JSON, and images (OCR). Downloads with a browser-like User-Agent and follows redirects.
- Result is stored under `~/work/sources/<name>/`: `text.txt` (with `=== PAGE n ===`, `=== SHEET x ===`, `=== SLIDE n ===` or `=== PART n ===` markers), `manifest.json`, `original.*`, `outline.txt` (when available), `links.txt` (HTML).
- Scanned or image-only pages are OCR'd automatically (`--ocr auto`). The language defaults to the installed set; pass `--lang eng+deu` for other languages (the language pack must be installed).
- Read the printed WARN lines: they tell you about OCR use, pages with no text, images that may contain tables, tracked changes, hidden sheets, and TYPE MISMATCH (a URL that returned an HTML error or login page instead of the document: it is not the document).
- **JavaScript-heavy web pages:** for web pages (never for documents), if the standard extraction finds little or no text because the page is rendered by JavaScript, `fetch_doc` automatically re-fetches it through Jina Reader (a third-party remote renderer) and uses that result if it is clearly better; the original extraction is kept as `text_local.txt`. The summary then says `reader: Jina Reader USED`. If you know what the page should contain, pass `--expect "<phrase>"` (repeatable): when the phrase is missing from the standard extraction, the reader is tried, and a WARN tells you if it is still missing afterwards. The reader is not used for local/internal hosts or URLs carrying tokens, credentials or signatures; in that case the WARN says "NOT sent". `--reader off` disables it, `--reader force` tries it for any web page. Reader output is markdown: tables are flattened, so verify key figures with `render_page <url>`.
- A WARN about JavaScript with no reader result means the page is probably incomplete: do not treat it as fully read. Use `render_page <url> --ocr` (local browser screenshot) or ask the user.
- Exit code 2 means failure; the output lists the fallback ladder. Use `--archive` to try a Wayback snapshot.
- Re-running on the same source is cached; add `--force` to redo.
- Prefer giving short names (`--name regulation-2025`).

## doc_search: find and read, with locations
```
doc_search --list                              documents, types, OCR pages, warnings
doc_search "term1 term2"                       terms within 3 lines of each other, all documents
doc_search -d NAME "exact phrase" -C 2         one document, 2 lines of context
doc_search -d NAME -r "deadline|due date"      regex
doc_search -d NAME --outline                   headings / table of contents
doc_search -d NAME --at 12                     read page/sheet/slide/part 12 (also 12-14 or a sheet name)
doc_search -d NAME --section "Article 6"       read one section (heading text exactly as in the document)
```
- Matching ignores case and accents. Quote multi-word phrases. Try synonyms and other languages used in the document.
- Output is capped (6000 characters by default). Narrow the request rather than raising the cap blindly; use `--max-chars 20000` only when you need a long section.
- For `--section`, look at `--outline` first to see how headings are written ("Article 6", "Članak 6", "3.2 Eligibility"). If the table of contents and the body both match, the longest match is returned.
- "No hits" only proves absence in the extracted text. If the document had OCR or extraction warnings, say so.
- Cite as `[NAME, PAGE n]` using the location printed in each hit.

## render_page: look at a page
```
render_page NAME --page 12 [--dpi 150] [--crop 0,0.4,1,1] [--ocr]
render_page /path/file.docx --page 1
render_page https://example.org/page          screenshot of a web page
```
- Use it for tables, figures, scanned pages, layout questions, and to verify numbers that came from OCR. `--crop x0,y0,x1,y1` takes fractions of the page and gives a sharper view of a region.
- Output is a PNG path. If you cannot view images, add `--ocr` to print the recognized text of the render.
- Office files are rendered through LibreOffice, so page breaks can differ slightly from Word/Excel/PowerPoint.

## check_output: validate generated files
```
check_output ~/work/out/file.docx [--render]
```
- `.docx` structure, placeholders, rendered page count, blank pages. `.xlsx` recalculated and scanned for `#REF!`, `#DIV/0!`, `#NAME?`, `#VALUE!`, `#N/A`. `.pptx` off-slide shapes, overlapping text, empty slides. `.pdf`, `.html`, `.svg`, `.xml`/`.bpmn` (well-formedness, duplicate ids, overlapping diagram shapes), `.json`, `.csv`.
- Exit code 1 and `FAIL` lines mean the file is broken; fix and rerun. `WARN` lines mean look closer.
- `--render` writes PNGs to `~/work/renders/` for visual review.

## Building files
For building files, load the skill `build-files`.

## Practical rules
- The container may be recreated, which wipes `~/work` if no persistent volume is attached: tell the user to download important files promptly.
- Never dump a whole document with `cat`. Use `doc_search --at` / `--section`.
- Keep scripts and notes in `~/work/`, not in `sources/`.
- If a command is missing (`command not found`), the toolkit is not installed in this container: tell the user to run the install step instead of improvising.
