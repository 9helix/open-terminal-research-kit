---
name: build-files
description: Use whenever the task produces a file the user will open or download, such as DOCX, XLSX, PPTX, PDF, HTML, SVG or other diagram and XML formats, or CSV. Covers building the file with a script, validating it with check_output, and delivering it. Not for answers given in chat.
---

# Build files

Terminal commands are described in the skill `research-terminal-tools`; load it with `view_skill` before your first terminal command.

## 1. Inputs
- The user's specification is the source of truth. If something essential is missing or ambiguous, ask one focused question, or state your assumption at the top of your answer and go on.
- Do not invent values. If the file depends on outside facts (datasheet figures, rules, prices), look up only those, or mark them as unverified in the file and in your answer. If it depends on reading several sources, also load `research-workflow`.

## 2. Build
- Write a Python script to `~/work/build_<name>.py`, run it, and write the output to `~/work/out/`. Do not paste file contents into the chat unless asked.
- Libraries: python-docx, openpyxl, python-pptx, lxml, pymupdf, pillow. Install anything else with `pip install --user --break-system-packages <pkg>`.
- Spreadsheets: use formulas, not pasted results, when the user will edit the model.
- Diagrams (SVG, BPMN, draw.io and other XML formats): keep a machine-readable description next to the drawing (nodes and edges, or a component list and netlist). Generate coordinates from that description in code, never by hand.
- Circuits: produce a component list (reference designator, part, value with unit) and a netlist. Check in code that reference designators are unique, every component has the pins its type requires, every net has at least two connections, and no pin is left unconnected without being marked. Say clearly that the circuit was not simulated unless you ran a simulation.

## 3. Validate
- Run `check_output <file>` on every generated file. Fix every FAIL and decide on each WARN.
- For layout-heavy files also run it with `--render` and look at the renders (or use `render_page --ocr` if you cannot see images).
- If the user asked to see an SVG or HTML page and it is small, print it in the reply as a code block so it renders in the chat, and also save it to `~/work/out/`. Use `check_output --render` only to check your own work, and only look at the render if you can view images.

## 4. Deliver
- Tell the user the file path and that files are downloaded from the terminal file browser panel.
- To let the user view an HTML or SVG file you built, run `python3 -m http.server <port>` in the background from `~/work/out` only, then tell them to open that port from the Ports list in the Browser tab.
- State what you assumed, what `check_output` verified, and what it cannot verify (for example electrical correctness or content accuracy).

## Hard rules
1. Never claim a file was validated unless `check_output` ran and passed.
2. Never present a drawing as correct beyond what the checks cover.
3. If a tool fails, say so and say what you did instead.
