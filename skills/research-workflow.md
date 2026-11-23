---
name: research-workflow
description: Use when a task requires reading, comparing or verifying documents or sources (attached, linked or found on the web), such as regulations, contracts, papers, reports, datasets or web pages, and building a sourced analysis from them. Not for tasks whose inputs are all in the user's message or project files (drawing, coding, rewriting, calculating from given numbers), and not for casual questions or simple lookups. If the task also produces a file, load build-files as well.
---

# Research workflow

Follow this procedure for source-based work. Terminal commands are described in the skill `research-terminal-tools`; load it with `view_skill` before your first terminal command.

## 0. Do you need this procedure?
If every input the task needs is in the user's message or in files the user gave you, and you need no outside facts, skip sections 1 to 7 and the coverage table: do the work, and load `build-files` if the result is a file. If the task depends on a few outside facts (for example a part's datasheet rating), look up just those, cite them, and continue. Use the full procedure only when the answer rests on reading or comparing sources.

## 1. Scope (one short step)
Restate the deliverable in one line: question, output format, audience. If an ambiguity would change the answer materially, ask one focused question; otherwise state your assumption and go on. List the kinds of sources the answer needs (official/primary, secondary, data) and what "done" looks like.

## 2. Acquire sources
- Prefer primary sources (the document that creates the rule, the dataset, the original paper) over summaries of them.
- Download every document you will rely on into the terminal with `fetch_doc`. Do not read long documents through search snippets or by pasting them into the conversation.
- Files the user attached are sources too: find and read them the same way.
- If a fetch fails or returns an error page, follow the fallback ladder: retry with `--archive`; search the exact filename or title (`site:<official domain>`); check other hosts, subdomains and mirrors; fetch the page that links to the file and read `links.txt`; finally ask the user to attach the file. Never repeat the same failing URL more than twice.
- Web pages that need JavaScript are handled by `fetch_doc` itself (it falls back to a remote reader). If a page still looks incomplete after that, record it as read in part, not in full.
- A source you could not read is recorded as NOT READ. You may mention what other sources say about it, labelled as secondary.

## 3. Read selectively, with locations
- Start with the outline (`doc_search -d NAME --outline`), then search or read the specific pages and sections you need.
- Read the passage itself before you state what a document says. Search hits are pointers; confirm by reading the page or section around them.
- OCR output can contain digit and diacritic errors: for any figure, date or threshold that matters and came from OCR, look at the page with `render_page` (or check it with `--ocr` on a crop) before relying on it.
- Tables, images and text boxes are the usual places where extraction silently loses content: read the warnings `fetch_doc` prints and act on them.

## 4. Keep a claims ledger
Maintain `~/work/ledger.md` while you work. One entry per claim that matters:

`- claim | source (name or URL) | location (page, sheet, section) | short quote (under 25 words) | status`

Status is one of: `verified` (read in the source), `single-source`, `conflicting`, `unverified` (not read or only seen secondhand). The final answer is built from the ledger, not from memory.

## 5. Currency and authority
For every source, check whether something newer or higher in the hierarchy exists: amendments, supplements, corrigenda, later editions, superseding versions, retractions, errata. Search for them explicitly. When sources disagree, prefer binding over advisory, specific over general, newer over older, primary over secondary, and say which rule you applied and why. If you cannot establish the hierarchy, say so.

## 6. Cross-check
When two or more sources cover the same subject, compare them attribute by attribute: dates and deadlines, numbers and thresholds, definitions, scope, who decides or is responsible, mandatory versus recommended. Report every mismatch in a table with both locations:

| Topic | Source A (location) | Source B (location) | Which prevails and why |

Do not smooth conflicts over and do not pick one silently. If there are no mismatches, say which attributes you compared.

## 7. Compute in code
Every calculation (totals, conversions, date arithmetic, rates) is done with a script in the terminal. Show the inputs, the formula and the output. State the unit, currency and rounding rule you used, and the source of each input.

## 8. Files
If the deliverable is a file, load the skill `build-files` and follow it.

## 9. Final answer
- Lead with the answer or deliverable.
- Cite each claim with a link or document name plus location, for example `[Regulation, p. 12]` or `[https://example.org/doc.pdf, sheet "Partners"]`.
- State confidence per claim where it differs: verified, single-source, or inferred.
- Finish with the coverage table:

| Source | Status (read in full / read in part / NOT READ) | Method (text, OCR, secondary) | Notes (what was skipped or uncertain) |

- List open points: conflicts you could not resolve, documents you could not obtain, and what the user could check or supply.

## Hard rules
1. Never attribute a statement to a document you have not read. If you only know it from a secondary source, say so.
2. Never present OCR or extracted text as certain when the numbers decide the answer: verify visually.
3. Never claim a source says nothing about X unless you searched all of its extracted text and note the extraction limits.
4. If a tool fails, say so and say what you did instead. Do not answer from memory as if the lookup had worked.
