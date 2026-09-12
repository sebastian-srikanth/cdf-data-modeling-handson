#!/usr/bin/env python3
"""Offline correctness checks for the course. No credentials, no network.

Run:  uv run python tools/check_docs.py
Exit: 0 if everything passes, 1 otherwise (so CI fails the build).

Checks
  1. every relative markdown link resolves
  2. every "§N.M" cross-reference names a heading that exists
  3. every ```yaml block parses
  4. every ```python block parses
  5. every notebook code cell parses
  6. every [WRITE] yaml block matches the reference module byte for byte
  7. no notebook cell uses a name it never defines
  8. every hands-on chapter has a Gate and a next-chapter link
"""
from __future__ import annotations

import ast
import builtins
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
NOTEBOOKS = DOCS / "notebooks"
REFERENCE = ROOT / "training" / "modules" / "reference"

# A participant renders the reference module with their own name; the chapters show it
# rendered for "<YOURNAME>". Keep this table in step with materialising a module.
SUBSTITUTIONS = [
    ("{{ participant }}", "<YOURNAME>"),
    ("{{ instance_space }}", "isp_<YOURNAME>_TRN"),
    ("{{ schema_space_edm }}", "ssp_<YOURNAME>_TrainingCore_edm"),
    ("{{ schema_space_sdm }}", "ssp_<YOURNAME>_MaintenanceInsight_sdm"),
    ("{{ dataset }}", "dts_<YOURNAME>_Training_TRN"),
    ("{{ raw_db }}", "rwd_<YOURNAME>_Training_TRN"),
    ("{{ model_version }}", "v1.0.0"),
    ("{{ function_runtime }}", "py311"),
    ("{{ site_code }}", "TRN"),
]

# Chapters that are pure process (tooling, naming, git) and deploy nothing to CDF.
NO_GATE_EXPECTED = {"13", "14", "17", "18"}

failures: list[str] = []
notes: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)


def chapters() -> list[pathlib.Path]:
    return sorted(p for p in DOCS.glob("*.md") if re.match(r"^\d\d-", p.name))


def render(text: str) -> str:
    for token, value in SUBSTITUTIONS:
        text = text.replace(token, value)
    return text.rstrip("\n")


# ---------------------------------------------------------------- 1. links ----
LINK = re.compile(r"\]\((?!https?:|#|mailto:)([^)#]+)(#[^)]*)?\)")


def check_links() -> int:
    """Markdown files AND notebook cells — a stale ../NN-chapter.md link inside a
    notebook is just as broken, and is exactly what slipped through a renumber."""
    checked = 0
    for md in list(DOCS.rglob("*.md")) + [ROOT / "README.md", ROOT / "PREREQUISITES.md"]:
        if not md.exists():
            continue
        for m in LINK.finditer(md.read_text()):
            checked += 1
            if not (md.parent / m.group(1)).resolve().exists():
                fail(f"dead link  {md.relative_to(ROOT)} -> {m.group(1)}")

    for nb_path in sorted(NOTEBOOKS.glob("*.ipynb")):
        for i, cell in enumerate(json.loads(nb_path.read_text())["cells"]):
            for m in LINK.finditer("".join(cell["source"])):
                checked += 1
                if not (nb_path.parent / m.group(1)).resolve().exists():
                    fail(f"dead link  {nb_path.name} cell {i} -> {m.group(1)}")
    return checked


# ------------------------------------------------------------- 2. crossrefs ----
def check_crossrefs() -> int:
    headings = {
        p.name[:2]: set(re.findall(r"^#+ (\d+\.\d+[a-z]?)", p.read_text(), re.M))
        for p in chapters()
    }
    checked = 0
    for md in chapters():
        for m in re.finditer(r"(?:Chapter (\d\d)[^§\n]{0,60})?§(\d+)\.(\d+[a-z]?)", md.read_text()):
            checked += 1
            section = f"{m.group(2)}.{m.group(3)}"
            chapter = m.group(1) or f"{int(m.group(2)):02d}"
            if chapter in headings and section not in headings[chapter]:
                fail(f"bad xref   {md.name} -> §{section} (chapter {chapter}) is not a heading")
    return checked


# ------------------------------------------------------- 3+4. fenced blocks ----
def check_fenced_blocks() -> tuple[int, int]:
    import yaml  # pyyaml ships with the Toolkit

    n_yaml = n_python = 0
    for md in list(DOCS.glob("*.md")):
        text = md.read_text()
        for m in re.finditer(r"```yaml\n(.*?)```", text, re.S):
            n_yaml += 1
            try:
                yaml.safe_load(m.group(1))
            except Exception as exc:  # noqa: BLE001 - report, don't crash
                fail(f"bad yaml   {md.name}: {str(exc)[:120]}")
        for m in re.finditer(r"```python\n(.*?)```", text, re.S):
            n_python += 1
            try:
                ast.parse(m.group(1))
            except SyntaxError as exc:
                fail(f"bad python {md.name}: {exc}")
    return n_yaml, n_python


# ------------------------------------------------------- 5. notebook syntax ----
def check_notebook_syntax() -> int:
    cells = 0
    for nb_path in sorted(NOTEBOOKS.glob("*.ipynb")):
        for i, cell in enumerate(json.loads(nb_path.read_text())["cells"]):
            if cell["cell_type"] != "code":
                continue
            source = "".join(cell["source"])
            if source.lstrip().startswith(("!", "%")):
                continue
            cells += 1
            try:
                ast.parse(source)
            except SyntaxError as exc:
                fail(f"bad cell   {nb_path.name} cell {i}: {exc}")
    return cells


# ---------------------------------------------------- 6. [WRITE] block sync ----
WRITE_BLOCK = re.compile(
    r"\[WRITE\]`\s*`(?P<path>[^`]+?)`"
    r"(?:(?!```)[\s\S])*?"
    r"```yaml\n(?P<body>[\s\S]*?)```"
)


def check_write_blocks() -> int:
    by_name: dict[str, pathlib.Path] = {}
    for path in REFERENCE.rglob("*.yaml"):
        by_name.setdefault(path.name, path)

    checked = 0
    for md in chapters():
        for m in WRITE_BLOCK.finditer(md.read_text()):
            name = pathlib.PurePosixPath(m.group("path").strip()).name
            reference = by_name.get(name)
            if reference is None:
                continue  # a file the learner authors that the reference does not ship
            checked += 1
            if m.group("body").strip() != render(reference.read_text()).strip():
                fail(
                    f"drift      {md.name}: [WRITE] block for {name} no longer matches "
                    f"{reference.relative_to(ROOT)}"
                )
    return checked


# ------------------------------------------------- 7. notebook undefined names ----
def check_undefined_names() -> int:
    """Flag a cell using a name no earlier cell defined. Deliberately conservative."""
    checked = 0
    for nb_path in sorted(NOTEBOOKS.glob("*.ipynb")):
        defined: set[str] = set(dir(builtins))
        for i, cell in enumerate(json.loads(nb_path.read_text())["cells"]):
            if cell["cell_type"] != "code":
                continue
            source = "".join(cell["source"])
            if source.lstrip().startswith(("!", "%")):
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue  # already reported by check_notebook_syntax
            checked += 1

            bound: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    bound.add(node.id)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    bound.add(node.name)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        args = node.args
                        for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
                            bound.add(a.arg)
                        for a in (args.vararg, args.kwarg):
                            if a:
                                bound.add(a.arg)
                elif isinstance(node, ast.Lambda):
                    args = node.args
                    for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
                        bound.add(a.arg)
                    for a in (args.vararg, args.kwarg):
                        if a:
                            bound.add(a.arg)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        bound.add((alias.asname or alias.name).split(".")[0])
                elif isinstance(node, (ast.comprehension,)):
                    for n in ast.walk(node.target):
                        if isinstance(n, ast.Name):
                            bound.add(n.id)
                elif isinstance(node, ast.ExceptHandler) and node.name:
                    bound.add(node.name)
                elif isinstance(node, ast.Global):
                    bound.update(node.names)

            used = {
                n.id
                for n in ast.walk(tree)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
            }
            missing = sorted(used - bound - defined)
            if missing:
                fail(f"undefined  {nb_path.name} cell {i}: {missing}")
            defined |= bound
    return checked


# ------------------------------------------------------------ 8. chapter shape ----
def check_chapter_shape() -> int:
    checked = 0
    for md in chapters():
        number = md.name[:2]
        if number in NO_GATE_EXPECTED:
            continue
        checked += 1
        text = md.read_text()
        if not re.search(r"^## Gate", text, re.M):
            fail(f"no gate    {md.name} has no '## Gate' section")
        if number != "18" and not re.search(r"^→ \[Chapter", text, re.M):
            fail(f"no next    {md.name} has no '→ [Chapter NN]' link")
    return checked


def main() -> int:
    links = check_links()
    xrefs = check_crossrefs()
    n_yaml, n_python = check_fenced_blocks()
    cells = check_notebook_syntax()
    writes = check_write_blocks()
    names = check_undefined_names()
    shapes = check_chapter_shape()

    print(f"  links            {links:>4} checked")
    print(f"  cross-references {xrefs:>4} checked")
    print(f"  yaml blocks      {n_yaml:>4} checked")
    print(f"  python blocks    {n_python:>4} checked")
    print(f"  notebook cells   {cells:>4} parsed")
    print(f"  [WRITE] blocks   {writes:>4} compared against the reference module")
    print(f"  notebook scopes  {names:>4} cells scanned for undefined names")
    print(f"  chapter shape    {shapes:>4} chapters checked for Gate + next link")
    for note in notes:
        print(f"  note: {note}")

    if failures:
        print(f"\n  {len(failures)} PROBLEM(S):")
        for f in failures:
            print(f"    {f}")
        return 1
    print("\n  all offline checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
