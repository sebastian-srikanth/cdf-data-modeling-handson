#!/usr/bin/env python3
"""Rewrite the [WRITE] handler blocks in the chapters from the reference module.

The reference is the source of truth: it is what `live_e2e.py` deploys and what the
course evaluation scores. A chapter that teaches a different handler teaches something
nobody has ever run.

    uv run python tools/sync_handlers.py            # show what would change
    uv run python tools/sync_handlers.py --write    # do it
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
REFERENCE = ROOT / "training" / "modules" / "reference"

WRITE_PY = re.compile(
    r"(\[WRITE\]`\s*`(?P<path>[^`]+?\.py)`(?:(?!```)[\s\S])*?```python\n)"
    r"(?P<body>[\s\S]*?)(```)"
)
FUNCTION_FOLDER = re.compile(r"fnc_.*?_Training_(\w+)")


def reference_handler(path: str):
    parts = pathlib.PurePosixPath(path).parts
    if "functions" not in parts:
        return None
    m = FUNCTION_FOLDER.match(parts[parts.index("functions") + 1])
    if not m:
        return None
    candidate = REFERENCE / "functions" / f"fnc_REFERENCE_Training_{m.group(1)}" / "handler.py"
    return candidate if candidate.exists() else None


def main() -> int:
    write = "--write" in sys.argv
    changed = insync = 0
    for md in sorted(DOCS.glob("[0-9][0-9]-*.md")):
        text = md.read_text()
        out, last, touched = [], 0, False
        for m in WRITE_PY.finditer(text):
            ref = reference_handler(m.group("path").strip())
            if ref is None:
                continue
            # The chapters show the module rendered for a participant.
            want = ref.read_text().replace("REFERENCE", "<YOURNAME>").rstrip("\n")
            if m.group("body").rstrip("\n") == want:
                insync += 1
                continue
            out.append(text[last:m.start("body")])
            out.append(want + "\n")
            last = m.end("body")
            touched = True
            changed += 1
            print(f"  {md.name}: {pathlib.PurePosixPath(m.group('path')).parts[-2]}")
        if touched and write:
            out.append(text[last:])
            md.write_text("".join(out))

    print(f"\n  {changed} handler block(s) {'rewritten' if write else 'would change'}, "
          f"{insync} already in sync")
    if changed and not write:
        print("  re-run with --write to apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
