#!/usr/bin/env python3
"""Render every ```mermaid block to prove it parses. A broken one ships as an error box.

    uv run python tools/check_mermaid.py

Needs Node. Skips with exit 0 if npx is unavailable, so it never blocks a contributor who
only edited prose — CI has Node and will run it for real.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
BLOCK = re.compile(r"```mermaid\n(.*?)```", re.S)


def main() -> int:
    mmdc = shutil.which("mmdc")
    if mmdc is None and shutil.which("npx") is None:
        print("  neither mmdc nor npx found — skipping mermaid validation (CI runs it)")
        return 0
    runner = [mmdc] if mmdc else ["npx", "-y", "@mermaid-js/mermaid-cli@11"]

    blocks: list[tuple[str, int, str]] = []
    for md in sorted(DOCS.glob("*.md")):
        for i, m in enumerate(BLOCK.finditer(md.read_text())):
            blocks.append((md.name, i, m.group(1)))

    if not blocks:
        print("  no mermaid blocks found")
        return 0

    # CI runners need a sandbox-free Chromium; without this every render fails with
    # "Failed to launch the browser process", which looks exactly like a broken diagram.
    config = pathlib.Path(__file__).resolve().parent / "puppeteer-config.json"
    if config.exists():
        runner = [*runner, "-p", str(config)]

    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = pathlib.Path(tmp)
        for name, index, source in blocks:
            src = tmpdir / f"{name}_{index}.mmd"
            src.write_text(source)
            proc = subprocess.run(
                [*runner, "-i", str(src), "-o", str(src.with_suffix(".svg"))],
                capture_output=True, text=True,
            )
            if proc.returncode == 0:
                print(f"  OK   {name} block {index}")
                continue

            # Distinguish "this machine cannot run a browser" from "this diagram is
            # wrong". Reporting an environment problem as six broken diagrams sends
            # whoever reads the log hunting through correct markup.
            if "Failed to launch the browser" in proc.stderr:
                print("\n  CANNOT RUN: mermaid-cli could not start a browser on this machine.")
                print("  This says nothing about your diagrams. On CI, install Chromium;")
                print("  locally, `npm install -g @mermaid-js/mermaid-cli` and retry.")
                return 2

            failures += 1
            first = next((l for l in proc.stderr.splitlines() if "rror" in l), "")
            print(f"  FAIL {name} block {index}: {first[:160]}")

    print(f"\n  {len(blocks)} mermaid block(s) checked, {failures} broken")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
