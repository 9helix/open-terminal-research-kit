#!/usr/bin/env python3
"""research_init: create the workspace folders and its README.md.

  research_init                 create what is missing (safe to rerun; never overwrites an existing README.md)
  research_init --reset-readme  replace README.md with the kit's current template (old one saved as README.md.bak-<time>)

The README text comes from WORK.md (installed with the kit; set RESEARCH_WORK_TEMPLATE to use your own file).

Workspace root is $RESEARCH_HOME (default ~/work): scratch/ (with renders/), tools/, state/ (with ledgers/), out/, sources/.
Run it as the terminal's own user, e.g.:  docker exec <container> research_init
The kit's other tools create the workspace on first use too, but a model that starts with a plain terminal task only
finds the README if it already exists.
"""
import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent.parent / "lib"), "/usr/local/lib/research_kit"]
from research_common import HOME, WORKSPACE_DIRS, ensure_workspace, work_template_path, work_template_text  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset-readme", action="store_true", help="replace README.md with the current kit template")
    a = ap.parse_args()

    if work_template_path() is None:
        print("ERROR: the workspace template WORK.md was not found (reinstall the kit, or check RESEARCH_WORK_TEMPLATE)", file=sys.stderr)
        sys.exit(1)
    created = ensure_workspace()
    readme = HOME / "README.md"
    if a.reset_readme and readme.exists():
        backup = readme.with_name(f"README.md.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(readme, backup)
        readme.write_text(work_template_text(), encoding="utf-8")
        created.append(f"{readme} (reset; previous version saved as {backup.name})")

    missing = [d for d in WORKSPACE_DIRS if not (HOME / d).is_dir()] + ([] if readme.exists() else ["README.md"])
    if missing:
        print(f"ERROR: could not create in {HOME}: {', '.join(missing)} (check permissions and RESEARCH_HOME)", file=sys.stderr)
        sys.exit(1)
    print(f"workspace: {HOME}")
    for c in created:
        print(f"  created {c}")
    if not created:
        print("  already complete: nothing created")


if __name__ == "__main__":
    main()
