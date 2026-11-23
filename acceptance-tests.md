# Acceptance tests

Run each in a fresh chat with a model that has all three skills attached, the terminal attached to the chat, and web search on. Substitute your own documents where noted. Each case tests one pipeline capability, not a subject area. A case passes only if every criterion holds.

Tip: for cases 1 to 5, use real documents you know well, so you can judge correctness yourself.

## 1. Large PDF from a URL, read by section
**Prompt:** "Read <URL of a PDF of 50+ pages> and tell me what it says about <a topic covered in two or three places>. Quote the relevant passages (under 25 words each) with page numbers."
**Pass:** the model downloads it with `fetch_doc`; uses `doc_search`/`--section`/`--at`; every claim carries a page or section; the quotes match the source when you check; it does not paste the whole document into the chat.
**If it fails:** tools not on PATH (`command not found`) → re-run install; model skips the terminal → run the smoke test in the README ("Verify") and check that the skills are attached and the terminal is attached to the chat.

## 2. XLSX or DOCX as a source
**Prompt:** "Use the attached/linked <xlsx or docx> to answer <a question whose answer is in a table or on a second sheet>."
**Pass:** the file is read (sheet or table location cited); it does not say it cannot open the file.
**If it fails with attached files:** attachments are not reaching the terminal; upload via the terminal's file browser panel instead, and check how your Open Terminal connection handles chat uploads.

## 3. Image-only tables
**Prompt:** "In <PDF or DOCX with a table that is a picture or a scanned page>, what is <a value in that table>?"
**Pass:** the model notes OCR use, gives the value with page, and verifies it with `render_page` (or says explicitly that it could not verify and asks you to check). A confident number from OCR without verification is a fail.

## 4. Two sources that disagree
**Prompt:** "Compare <source A URL> and <source B URL> on <deadlines, thresholds, who decides>. List every difference."
**Pass:** a mismatch table with locations on both sides, plus which source prevails and why. It must not merge them into one answer silently, and must not attribute A's rule to B.

## 5. Newer amendment exists
**Prompt:** "What are the current rules in <document> that have been amended since it was published?"
**Pass:** it searches for amendments/supplements/errata, finds the newer document (when one exists), states the hierarchy it applied, and reports if none was found rather than assuming.

## 6. Failing URL
**Prompt:** "Read https://<a host you know>/does-not-exist.pdf and summarize it."  (or a real URL that blocks bots)
**Pass:** it tries `--archive`, searches the filename and other hosts, then reports the document as NOT READ and asks you for the file. It does not loop on the same URL more than twice, and it does not invent a summary.

## 7. Numeric computation
**Prompt:** "Given <a small data set or fee schedule with several rules>, calculate <total> for <scenario>. Show how."
**Pass:** a script was run in the terminal; inputs, formula and output are shown; units and rounding stated; the result matches your own calculation.

## 8. Generated file
**Prompt:** "Create a DOCX (and an XLSX with formulas) summarising <a small topic> with a table, headings and totals."
**Pass:** the build script is in `~/work/scratch/` and the files are in `~/work/out/`; `check_output` was run and its result reported; no FAIL lines; you can download them from the file browser; the XLSX opens with formulas and no error values.
**Variant:** ask for a diagram file in an XML format you use; it should run `check_output` and fix reported overlaps.

## 9. JavaScript-rendered web page
**Prompt:** "Read <URL of a page whose content only appears after JavaScript runs, e.g. a single-page app or dashboard> and summarise what it shows."
**Pass:** the `fetch_doc` summary shows `reader: Jina Reader USED` (or a WARN explaining why it was not used); the answer is based on the rendered content, not on an empty shell; the coverage table marks it as read via the reader, with the tables-flattened caveat if relevant. For a page you know is static, the reader must **not** be used.
**If it fails:** reader blocked by the terminal's network rules → `docker exec <container> curl -sI https://r.jina.ai/https://example.com`; rate-limited (HTTP 429/402) → set `JINA_API_KEY`.

## 10. Task that needs no research
**Prompt:** "Draw an SVG block diagram of <a small system you describe in the prompt>, with these labelled parts: <list>." (or a small circuit from your own component list)
**Pass:** the model does not load `research-workflow` and does not search the web; it loads `build-files`, writes the diagram with a script, runs `check_output`, shows or saves the result, and states what it did and did not verify. A coverage table or sources list here is a fail.

## 11. Coverage report
**Pass (applies to cases 1 to 6 and 9):** the final answer ends with the coverage table (source, read in full / part / NOT READ, method, notes) and an honest list of open points. Any source named in the answer but absent from the table, or marked "read" though a fetch failed, is a fail.

## 12. Workspace convention
**Prompt:** "In the terminal, write a throwaway script that counts the lines of <a file>, run it, then do the same for the words in the file. Tell me where you saved things."
**Pass:** the model read `~/work/README.md` before its first command; the first script is in `scratch/`; for the second, similar request it makes one parameterized script in `tools/` instead of a third variant; nothing but finished deliverables is in `out/`.
**If it fails:** the model skipped the README → check that the prompt line is present and that `research_init` has been run (`docker exec <container> ls ~/work`).

---

## Reading the results

| Symptom | Likely cause | Fix |
|---|---|---|
| Model never loads the skill | native function calling off for the model, skill not attached or inactive, or model ignores the manifest | README "Open WebUI setup" steps 1 to 3; attach the skill manually from the chat input; add the optional system prompt paragraph |
| Model reads documents through web search snippets only | skill not loaded, or terminal not attached to the chat | attach terminal; load skill |
| Right tools, but ignores WARN lines | prompt-following weakness of the base model | add one sentence to the skill step 3 naming the exact warning; consider a stronger model for hard jobs |
| OCR errors in numbers | OCR quality | `--lang` correct? higher `--dpi`; verify with `render_page` |
| Everything fine, but long runs stall | tool-permission prompts or timeouts | check your Open WebUI tool-permission setting for the terminal (allow without asking for every call, if you accept that) |
