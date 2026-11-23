# research-kit

A toolkit and three skills that let a model in Open WebUI do source-based work through an Open Terminal: download and read documents with page-level locations, OCR scanned pages, render pages to images, run calculations in code, build files, and check the files it builds. The skills give the model a procedure for doing this reliably (retrieve, read with locations, check for newer versions, cross-check sources, report coverage) and for building and checking files.

It is task-agnostic: nothing in it is specific to one subject, language or document type.

## What is in it

**Terminal tools** (installed as commands in the Open Terminal container):

| Command | Purpose |
|---|---|
| `fetch_doc` | Download a URL or open a file (PDF, DOCX, XLSX, PPTX, HTML, CSV/TXT/MD/JSON, images) and extract its text with `=== PAGE n ===` / `SHEET` / `SLIDE` / `PART` markers. OCRs pages and embedded images that have little or no text. Falls back to a remote renderer (Jina Reader) for JavaScript-rendered web pages. Warns about extraction problems instead of hiding them. |
| `doc_search` | Search and read extracted documents without loading them into the model's context: term and regex search (accent- and case-insensitive), outline, read page/sheet/slide N, read a section by heading. |
| `render_page` | Turn a page, slide or sheet (or a web page) into a PNG, optionally cropped and OCR'd. For checking tables, figures and scanned content. |
| `check_output` | Validate generated files: DOCX, XLSX (recalculated with LibreOffice, scanned for formula errors), PPTX, PDF, HTML, SVG, XML/BPMN, JSON, CSV. Prints PASS / WARN / FAIL. |
| `research_selftest` | End-to-end self-test of all of the above in a throwaway workspace. |

**Skills** (Markdown files you import into Open WebUI):

| File | Purpose |
|---|---|
| `skills/research-workflow.md` | The research procedure: scope, acquire sources with fallbacks, read selectively, keep a claims ledger, check currency and authority, cross-check, compute in code, report coverage. It starts with a gate: tasks that need no outside sources skip it. |
| `skills/research-terminal-tools.md` | Reference for the commands above, loaded by the model before it uses them. |
| `skills/build-files.md` | Producing files (DOCX, XLSX, PPTX, PDF, HTML, SVG and other diagram formats, CSV): build with a script, validate with `check_output`, deliver and say what was and was not verified. Used on its own for tasks that need no research, such as drawing a diagram from the user's specification. |

Also included: `Dockerfile` and `docker-compose.yml` (image with the kit baked in and a persistent volume), `install.sh`, and `acceptance-tests.md` (domain-neutral checks to run after setup).

## Requirements

- Open WebUI with an Open Terminal connected, and a model with native function calling (skills and terminal tools are called as tools).
- The Open Terminal container must be Debian/Ubuntu-based with `python3` and root or passwordless sudo. Per the Open Terminal docs, the default `latest` image has sudo and can install packages; the `:openshift` variant does not support runtime package installs and so cannot run the installer.
- Outbound internet from the container for installation (apt, pip) and for fetching documents.

## Install

All commands run on the machine that hosts Docker. Replace `open-terminal` with your container name (`docker ps`).

### 1. Inspect the container

```bash
docker inspect --format 'image={{.Config.Image}} user="{{.Config.User}}"' open-terminal
docker exec open-terminal sh -c 'id; grep PRETTY_NAME /etc/os-release; command -v apt-get python3; sudo -n true && echo sudo-ok'
```

You need `apt-get` and `python3` found, and either `sudo-ok` or `uid=0`. Note the `user=` value: option B needs it as `RUN_USER` (empty means the image runs as root, so use `root`).

### 2a. Option A: install into a running container

Quick, but not persistent: tools and files are lost if the container is removed or recreated (for example when you pull a new image).

```bash
docker cp ./research-kit open-terminal:/tmp/research-kit
docker exec -it open-terminal bash -c 'cd /tmp/research-kit && chmod +x install.sh bin/*.py && ./install.sh'
```

If this fails with a sudo error, add `-u root` after `exec`.

### 2b. Option B: build an image with the kit and a persistent volume (recommended)

The kit is installed at build time, and `~/work` (downloaded sources, generated files) lives on a volume, so nothing needs reinstalling after a recreate.

1. Edit `docker-compose.yml`: set `RUN_USER` to the value from step 1 and adjust the memory and CPU limits to your host.
2. Copy `.env.example` to `.env` and fill it in (`OPEN_TERMINAL_API_KEY` is required, `JINA_API_KEY` is optional, see "Jina Reader fallback"). `.env` is listed in `.gitignore`, so it is not committed, and in `.dockerignore`, so it is not copied into the image. Never commit it; if it ever is, rotate the keys.
3. Remove the old container if it uses the same name or port (`docker stop open-terminal && docker rm open-terminal`), then:
   ```bash
   docker compose up -d --build
   ```

The service keeps port 8000, so an existing Open WebUI connection to the terminal keeps working if the host, port and key are unchanged.

To update: `docker compose build --pull && docker compose up -d`. The volume keeps your files. Scripts are copied into the image at build time, so edits to the kit need a rebuild.

**Mounting a project folder** (optional): add a bind mount under `volumes:` in `docker-compose.yml`:

```yaml
      - /path/on/the/docker/host/myproject:/home/user/project:ro
```

The path is on the machine that runs Docker. Use `:ro` unless you want the model to be able to modify or delete files in it. For read-write mounts, the container user must be able to write to the folder (`docker exec open-terminal id` shows its user ID).

### Install options

`install.sh` accepts these. With the Docker build, pass them through the `OCR_LANGS`, `READER` and `INSTALL_FLAGS` build arguments in `docker-compose.yml`.

| Option | Effect |
|---|---|
| `--langs "eng deu"` | OCR languages (tesseract 3-letter codes). Default `eng hrv`. |
| `--no-office` | Skip LibreOffice. You lose spreadsheet recalculation and page counts/blank-page checks for DOCX, XLSX, PPTX, and `render_page` on Office files. Reading Office files is unaffected. |
| `--no-browser` | Remove Playwright entirely. You lose web-page screenshots and HTML/SVG render checks. |
| `--reader off` | Never use the Jina Reader fallback (default `auto`; `force` also exists). |

By default the installer reuses a Chromium or Chrome already on the machine (`chromium`, `chromium-browser`, `google-chrome`, `google-chrome-stable`) and downloads nothing. Only if none is found does it download Playwright's Chromium. According to the Open Terminal v0.15.0 release notes, Chromium is included in the default image.

### 3. Verify

```bash
curl -s http://<terminal-host>:8000/health                # expect a JSON status response (see the Open Terminal docs if your version differs)
docker exec open-terminal research_selftest               # expect "N/N checks passed"
docker exec open-terminal bash -c 'fetch_doc --help | head -3; doc_search --list'
```

All 43 checks run when LibreOffice and a browser are installed; with `--no-office` or `--no-browser` fewer run and some are skipped. A failure in the `render_page` or `check_output` Office checks usually means LibreOffice is missing or short of memory.

## Open WebUI setup

Menu names vary between Open WebUI versions; search the admin settings for the quoted names if one differs.

1. **Connect the terminal** (admin settings → Integrations → Open Terminal): URL and API key of the container, as described in the Open Terminal docs. Skip this if it is already connected.
2. **Import the skills** (Workspace → Skills → Import): `skills/research-workflow.md`, `skills/research-terminal-tools.md` and `skills/build-files.md`. Keep the names unchanged: the skills refer to each other by id (`research-terminal-tools`, `build-files`, `research-workflow`). If the import ignores the frontmatter, create each skill with **+ New Skill** and copy the name (as the id), the description and the body. Make sure all three are active. If other users will use them, share the skills with them.
3. **Attach the skills to a model** (Workspace → Models): create a model, or edit one, tick all three skills, and set **Function Calling** to **Native**. Attached skills load on demand: only a short name and description is in the prompt until the model loads the full text.
4. **In each chat**, select that model and attach the terminal in the chat input. Generated files appear in the terminal's file browser panel; download them from there.
5. **Optional system prompt paragraph**, for models that have the skills attached:

   ```
   Source-based work: If a `research-workflow` skill is available to you, load it with view_skill when the answer depends on reading, comparing or verifying documents or sources (reports, regulations, contracts, papers, datasets), whether attached, linked or to be found. Do not load it for everyday questions that a quick web search answers (prices, product advice, schedules, opening hours), or when the task needs no outside facts. If a `build-files` skill is available, load it when the task produces a file (DOCX, XLSX, PPTX, PDF, diagrams, spreadsheets). If a terminal is connected, use it for downloading, reading, computing and building files instead of reading long documents in the conversation.
   ```

   The paragraph is conditional on the skill being available, so it is harmless in a shared prompt used with models that don't have it.

Then run the smoke test below.

### Smoke test

Ask: "Use the terminal to run `doc_search --list` and `fetch_doc --help` and tell me what the tools do. Then load the research-workflow skill and summarise its steps in five lines." It should run both commands and load the skill. If it never loads the skill, check that function calling is native, that the skill is attached and active, and that the terminal is attached to the chat. If needed, select the skill manually from the chat input.

Then work through `acceptance-tests.md`.

## Configuration

Environment variables (set on the container, for example in `docker-compose.yml`):

| Variable | Effect |
|---|---|
| `RESEARCH_HOME` | Workspace root (default `~/work`, with `sources/`, `out/`, `renders/`). |
| `RESEARCH_OCR_LANGS` | Default OCR languages, e.g. `eng+deu` (default from the install, `eng+hrv`). |
| `RESEARCH_READER` | `auto` / `off` / `force`: Jina Reader fallback mode. |
| `RESEARCH_READER_URL` | Base URL of an alternative or self-hosted reader. |
| `JINA_API_KEY` | Optional API key for Jina Reader. |
| `RESEARCH_BROWSER` | Path to the Chromium/Chrome binary to use (default: auto-detected). |

The installer also writes `/usr/local/etc/research-kit.conf` (`OCR_LANGS`, `READER`); `READER_URL` and `BROWSER_PATH` can be set there too. Environment variables take precedence.

## Jina Reader fallback for JavaScript-heavy web pages

`fetch_doc` fetches a web page normally first. If the page looks JavaScript-rendered (an empty app shell, a "please enable JavaScript" wall, almost no text next to a lot of script), or text you named with `--expect "..."` is missing, it re-fetches the page through [Jina Reader](https://r.jina.ai), a third-party service that renders the page in a remote browser and returns markdown. The result replaces the standard extraction only if it is clearly better; the standard text stays in `text_local.txt`. This applies only to web pages, never to documents (PDF, Office, CSV, images).

- **Privacy:** on the public endpoint, the page URL is sent to Jina. URLs on local or private hosts, URLs with credentials, and URLs carrying tokens or signatures (`?token=`, `?key=`, `?sig=` and similar) are never sent; the tool prints "NOT sent". Disable it with `--reader off` per call, `RESEARCH_READER=off`, or `--reader off` at install.
- **API key:** optional; set `JINA_API_KEY` for higher rate limits. Without one, expect stricter rate limiting (HTTP 429 or 402 is reported with a hint).
- **Self-hosted reader:** set `RESEARCH_READER_URL` to a service that accepts `<base><target-url>` GET requests and returns markdown. Privacy guards are relaxed for a custom endpoint, since the URL no longer goes to the public service.
- **Network:** the container must be able to reach `r.jina.ai`: `docker exec open-terminal curl -sI https://r.jina.ai/https://example.com | head -1`.
- **Limits:** no help for pages behind a login, captchas, or content that needs a click. Markdown flattens tables, which the tool warns about. Detection is heuristic: use `--expect "<phrase on the page>"` or `--reader force` when it misses a page, and note that a false trigger just keeps the standard text if the reader result isn't clearly better.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `command not found: fetch_doc` | Not installed in this container, or the container was recreated after a path A install. Re-run the install, or use option B. |
| Install fails on `apt-get` | Not a Debian/Ubuntu-based image. Use the default `latest` image. |
| Install fails with a sudo error | Run with `docker exec -u root`. |
| `check_output` warns "LibreOffice unavailable" | Installed with `--no-office`, or the install failed. Spreadsheet formulas are then not recalculated. |
| `check_output` warns "could not start browser" | No usable Chromium. Check `which chromium` in the container, or set `RESEARCH_BROWSER`. |
| `fetch_doc` prints `TYPE MISMATCH` | The URL returned an error, login or access-denied page instead of the document. It is not the document. |
| OCR errors in numbers | Check `--lang`, raise `--dpi`, and verify the page with `render_page`. |
| Reader requests fail | Network access to `r.jina.ai` blocked, or rate-limited (set `JINA_API_KEY`). |

## Limitations and status

- OCR accuracy depends on scan quality; the tools flag OCR pages and the workflow skill tells the model to verify decisive figures visually. A human check remains the real safeguard for critical numbers.
- XLSX extraction reads cached values: a workbook generated by a script and never opened in a spreadsheet application has none. `check_output` recalculates a copy; extracting text from such a file needs the same step first.
- Legacy `.doc`, `.xls` and `.ppt` files are not supported by `fetch_doc`; convert them to DOCX/XLSX/PPTX first.
- DOCX extraction does not read headers, footers, footnotes, text boxes or comments, and warns about tracked changes. Hidden XLSX sheets are marked.
- `check_output`'s geometry check applies to XML diagram files with `Bounds` elements (such as BPMN) and only warns. SVG gets well-formedness, duplicate-id and render checks; overlapping shapes are not flagged. A checker cannot judge whether a diagram or circuit is correct.
- Everyone who can use one Open Terminal connection shares the same `~/work`.
- Tested: the tools and installer pass the 43-check self-test in a Debian-based test environment (with the Jina Reader tests run against a local mock, not the real service). Not verified: the Docker build, and the kit against the current Open Terminal image; check step 1 first.

## Security notes

- The terminal gives the model a shell with network access. It is as powerful as what you mount into it and what the container can reach on your network. Do not mount `/var/run/docker.sock`, and mount only the folders you intend to share, read-only where possible.
- Keep API keys in the environment or a `.env` file, not in files the kit writes. `.dockerignore` excludes `.env` from the image, but check any other secrets you place in the build folder.

## Layout

```
research-kit/
├── bin/            fetch_doc.py, doc_search.py, render_page.py, check_output.py, research_selftest.py
├── lib/            research_common.py
├── skills/         research-workflow.md, research-terminal-tools.md, build-files.md
├── install.sh      installer (run inside the container)
├── requirements.txt
├── Dockerfile, docker-compose.yml, .env.example
├── .dockerignore, .gitignore
├── acceptance-tests.md
└── README.md
```
