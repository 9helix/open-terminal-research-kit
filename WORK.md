# ~/work: workspace conventions

Read this before your first terminal command, and follow it. Use the terminal for downloading, reading, computing and building files instead of reading long documents in the conversation.

| Folder | What goes there |
|---|---|
| `scratch/` | One-off scripts, per-run data, temporary files, experiments and page renders (`scratch/renders/`). Disposable by definition: assume it may be wiped at the start of any session. This is the default home: when unsure where something goes, put it here. |
| `tools/` | Parameterized scripts meant to run more than once. Start each with a short comment saying what it does and how to call it, and look in this folder before writing a new script. Keep them working: give a tool a `--selftest` option where practical, and run it after you change the tool. If you write the same kind of script twice in one task, stop and make it one parameterized tool here instead of a third variant. |
| `state/` | Notes that should survive between sessions. Keep them small enough to regenerate in a minute (saved research ledgers in `state/ledgers/` are the exception, see below). Never store credentials or personal data here. |
| `out/` | Finished deliverables the user downloads. Final files only, with descriptive names; no scratch work. |
| `sources/` | Documents fetched by `fetch_doc` (text with page markers, manifest, original). Managed by the tool; treat it as a cache. |

## Research ledgers

While working on a source-based task, keep the claims ledger in `scratch/ledger-<task>.md`. When the task is done, save it to `state/ledgers/<topic>-<what-it-covers>-<YYYY-MM>.md` only if keeping it will help in future (the user is likely to return to the topic, or it holds verified facts or source locations worth reusing). Otherwise leave it in `scratch/`. Begin a saved ledger with the date, the question and the scope. When reusing an old ledger, treat its entries as leads and re-check anything that may have changed.

## Kit tools

`fetch_doc`, `doc_search`, `render_page`, `check_output` and `research_init` are installed as commands; the `research-terminal-tools` skill describes them.

This file was created by `research_init` and is not overwritten by it. Edit it to add your own conventions.
