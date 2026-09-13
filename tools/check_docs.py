#!/usr/bin/env python3
"""Offline correctness checks for the course. No credentials, no network.

Run:  uv run python tools/check_docs.py
Exit: 0 if everything passes, 1 otherwise (so CI fails the build).

Checks
  1. every relative markdown link resolves
  2. every "section N.M" cross-reference names a heading that exists
  3. every ```yaml block parses
  4. every ```python block parses
  5. every notebook code cell parses
  6. every [WRITE] yaml block matches the reference module byte for byte
  7. no notebook cell uses a name it never defines
  8. every hands-on chapter has a Gate and a next-chapter link
  9. every Python tool imports successfully
 10. query-story contracts preserve safe scoping, bounded traversal, batching, and
     the Atlas AI tool coverage required by the exercises
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
    ("{{ idp_group_reader }}", "<your-idp-group-object-id>"),
    ("{{ idp_group_developer }}", "<your-idp-group-object-id>"),
]

# Chapters that are pure process (tooling, naming, git) and deploy nothing to CDF.
NO_GATE_EXPECTED = {"13", "14", "18", "19"}

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
        for m in re.finditer(r"(?:Chapter (\d\d)[^\n]{0,60}?)?\bsections? (\d+)\.(\d+[a-z]?)",
                             md.read_text(), re.I):
            checked += 1
            section = f"{m.group(2)}.{m.group(3)}"
            chapter = m.group(1) or f"{int(m.group(2)):02d}"
            if chapter in headings and section not in headings[chapter]:
                fail(f"bad xref   {md.name} -> section {section} (chapter {chapter}) is not a heading")
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
        if number != "19" and not re.search(r"^→ \[Chapter", text, re.M):
            fail(f"no next    {md.name} has no '→ [Chapter NN]' link")
    return checked


# ------------------------------------------- 6b. [WRITE] python handler blocks ----
# The YAML check above has been catching schema drift while six Cognite Function
# handlers quietly diverged from the chapters that teach them -- because nothing
# compared Python. Every handler block presents itself as a complete file, with no
# elision markers, so a participant who types one gets something the reference module
# does not ship and live_e2e never exercises.
WRITE_PY = re.compile(
    r"\[WRITE\]`\s*`(?P<path>[^`]+?\.py)`"
    r"(?:(?!```)[\s\S])*?"
    r"```python\n(?P<body>[\s\S]*?)```"
)
FUNCTION_FOLDER = re.compile(r"fnc_.*?_Training_(\w+)")


def _reference_handler(path: str):
    parts = pathlib.PurePosixPath(path).parts
    if "functions" not in parts:
        return None
    m = FUNCTION_FOLDER.match(parts[parts.index("functions") + 1])
    if not m:
        return None
    candidate = REFERENCE / "functions" / f"fnc_REFERENCE_Training_{m.group(1)}" / "handler.py"
    return candidate if candidate.exists() else None


def check_write_python() -> int:
    checked = 0
    for md in chapters():
        for m in WRITE_PY.finditer(md.read_text()):
            reference = _reference_handler(m.group("path").strip())
            if reference is None:
                continue
            checked += 1
            if render(m.group("body")).strip() != reference.read_text().strip():
                fail(f"drift      {md.name}: the handler it tells you to write differs "
                     f"from {reference.relative_to(ROOT)}")
    return checked


# ---------------------------------------------- 7b. marker emoji consistency ----
# The one emoji each paragraph marker is allowed to carry. A reader learns to skim by
# these, so a [COMMON MISTAKE] wearing a different face costs them that shortcut.
MARKER_EMOJI = {
    "WRITE": "📝", "ACTION": "🟢", "CHANGE": "🔧", "VERIFY": "✅",
    "INFO": "ℹ️", "GOOD TO KNOW": "💡", "COMMON MISTAKE": "⚠️", "LIMITS": "🚧",
    "OPTIMIZE": "⚡", "SECURITY": "🔒", "DOCS": "📚", "PR": "🔀",
}
# Only a line that OPENS with a non-ASCII glyph is a marker paragraph. A numbered
# recap list ("2. `[WRITE]` …") legitimately references markers without wearing one.
MARKER_AT_START = re.compile(r"^([^\x00-\x7F]\S{0,2})\s*`\[([A-Z][A-Z ]*)\]`", re.M)


def check_marker_emoji() -> int:
    checked = 0
    for md in chapters():
        for m in MARKER_AT_START.finditer(md.read_text()):
            emoji, marker = m.group(1), m.group(2)
            want = MARKER_EMOJI.get(marker)
            if want is None:
                continue
            checked += 1
            if emoji != want:
                fail(f"marker     {md.name}: [{marker}] uses {emoji}, expected {want}")
    return checked


# ------------------------------------------------ 8b. chapter table integrity ----
CHAPTER_ROW = re.compile(r"\[(\d\d) — [^\]]+\]\((?:docs/)?(\d\d)-[^)]+\.md\)")


def check_chapter_tables() -> int:
    """A chapter row must link to the chapter its label names.

    Renumbering rewrites link targets but not the bare "16 — " label in a table cell,
    so the two silently drift apart. This has happened on every renumber so far.
    """
    checked = 0
    for md in (ROOT / "README.md", DOCS / "README.md"):
        if not md.exists():
            continue
        for m in CHAPTER_ROW.finditer(md.read_text()):
            checked += 1
            if m.group(1) != m.group(2):
                fail(f"row        {md.relative_to(ROOT)}: label says {m.group(1)} "
                     f"but links to {m.group(2)}-…")
    return checked


# ------------------------------------------------------- 8e. .env.example ----
# Step one of the course is `cp .env.example .env`, so anything the tooling needs must
# be in that template. PARTICIPANT in particular: selfcheck.py refuses to run without
# it, and a participant meets that at their very first Gate in Chapter 03.
ENV_REQUIRED = ["PARTICIPANT", "CDF_PROJECT", "CDF_CLUSTER", "IDP_CLIENT_ID"]


def check_env_example() -> int:
    example = ROOT / ".env.example"
    if not example.exists():
        fail("env        .env.example is missing, but the README tells you to copy it")
        return 0
    keys = {line.split("=", 1)[0].strip().lstrip("# ").strip()
            for line in example.read_text().splitlines() if "=" in line}
    for required in ENV_REQUIRED:
        if required not in keys:
            fail(f"env        .env.example has no {required}= line, but the tooling needs it")
    return len(ENV_REQUIRED)


# ----------------------------------------------------- 8d. advertised counts ----
# Numbers in the prose rot silently. The README claimed "16 chapters" when there were
# 20, and "four transformations" when there were five -- three false statements in the
# first paragraph a visitor reads. Tie the claims to the files.
COUNT_CLAIMS = [
    (re.compile(r"(\d+) chapters"),
     lambda: len(list(DOCS.glob("[0-9][0-9]-*.md"))), "chapters"),
    (re.compile(r"(\d+) Jupyter notebooks"),
     lambda: len(list(NOTEBOOKS.glob("*.ipynb"))), "notebooks"),
]
WORD_NUMBERS = {"four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
SPELLED = [
    (re.compile(r"(\w+) transformations"),
     lambda: len(list((ROOT / "training/modules/reference/transformations")
                      .glob("*.Transformation.yaml"))), "transformations"),
    (re.compile(r"(\w+) Cognite Functions"),
     lambda: len(list((ROOT / "training/modules/reference/functions").glob("fnc_*"))),
     "functions"),
]


def check_advertised_counts() -> int:
    checked = 0
    for md in (ROOT / "README.md", DOCS / "README.md", ROOT / "PREREQUISITES.md"):
        if not md.exists():
            continue
        text = md.read_text()
        for pattern, actual, label in COUNT_CLAIMS:
            for m in pattern.finditer(text):
                checked += 1
                if int(m.group(1)) != actual():
                    fail(f"count      {md.name}: says {m.group(0)!r}, there are {actual()}")
        for pattern, actual, label in SPELLED:
            for m in pattern.finditer(text):
                claimed = WORD_NUMBERS.get(m.group(1).lower())
                if claimed is None:
                    continue
                checked += 1
                if claimed != actual():
                    fail(f"count      {md.name}: says {m.group(0)!r}, there are {actual()}")
    return checked


# ------------------------------------------------- 8c. no tooling attribution ----
# This repository is Sebastian's work and carries no tool attribution. The patterns are
# assembled from fragments on purpose: spelling the vendor names literally here would
# put the very strings this check exists to forbid back into the repository.
_FRAGMENTS = [
    ("cla", "ude"), ("anthro", "pic"), ("chat", "gpt"), ("open", "ai"),
    ("copi", "lot"), ("co-authored", "-by"), ("generated", " with"),
]
ATTRIBUTION = re.compile("|".join(a + b for a, b in _FRAGMENTS), re.I)

# Legitimate hits that have nothing to do with tooling.
ATTRIBUTION_ALLOWED = re.compile(
    r"cursor"          # the CDF pagination cursor, all through chapters 09 and 14
    r"|_FRAGMENTS"     # this check's own machinery
    r"|ATTRIBUTION",
    re.I)


def check_no_attribution() -> int:
    """Nothing in this repository should credit a tool."""
    checked = 0
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in {".git", ".venv", "site", "build", "__pycache__", "node_modules"}
               for part in rel.parts):
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        checked += 1
        for i, line in enumerate(text.splitlines(), 1):
            if ATTRIBUTION.search(line) and not ATTRIBUTION_ALLOWED.search(line):
                fail(f"attribution {rel}:{i}: {line.strip()[:70]}")
    return checked


# ------------------------------------------------------- 9. the tools import ----
def check_tools_import() -> int:
    """Every tool must at least import.

    `check_docs.py` used to pass while `selfcheck.py` was broken -- its CHECKS dict
    named three functions that did not exist. Nothing imported the tools, so CI was
    green and the tool was unusable. Parsing is not enough; import is the real test,
    because it resolves names.
    """
    import importlib.util

    checked = 0
    for path in sorted(pathlib.Path(__file__).resolve().parent.glob("*.py")):
        if path.name == pathlib.Path(__file__).name:
            continue
        checked += 1
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules.setdefault(path.stem, module)
        try:
            spec.loader.exec_module(module)
        except SystemExit:
            pass  # a tool whose import path calls sys.exit is still importable
        except Exception as exc:  # noqa: BLE001
            fail(f"tool       {path.name} does not import: {type(exc).__name__}: {exc}")
    return checked


# ---------------------------------------------------- 10. query story contracts ----
def check_query_story_contracts() -> int:
    """Protect the course's architectural promises, not just its syntax.

    These checks are intentionally few and semantic. They cover regressions that all
    produce valid Python while making the multi-participant exercise wrong, expensive,
    or unable to answer the question it asks.
    """
    query_chapter = (DOCS / "13-querying-the-graph.md").read_text()
    query_notebook = (NOTEBOOKS / "07_query_the_graph.ipynb").read_text()
    diagram_notebook = (NOTEBOOKS / "02_diagram_detect.ipynb").read_text()
    atlas_chapter = (DOCS / "15-atlas-ai-agent.md").read_text()
    atlas_notebook = (NOTEBOOKS / "09_atlas_ai_agent.ipynb").read_text()

    contracts = {
        "chapter 13 scopes the hero-pump anchor to its instance space":
            'flt.SpaceFilter(INSTANCE_SPACE, "node")' in query_chapter,
        "query notebook scopes the hero-pump anchor to its instance space":
            'flt.SpaceFilter(INSTANCE_SPACE, \\"node\\")' in query_notebook,
        "graph traversals are explicitly bounded to one edge":
            "max_distance=1" in query_chapter
            and "max_distance=1" in query_notebook
            and "max_distance=1" in diagram_notebook,
        "latest datapoints are retrieved in one batch":
            "retrieve_latest(" in query_chapter
            and "instance_id=[" in query_chapter
            and "retrieve_latest(\\n" in query_notebook
            and "instance_id=[" in query_notebook,
        "sync selects only work-order instances":
            "NodeResultSetExpressionSync" in query_chapter
            and "HasData(views=[WORKORDER])" in query_chapter
            and "NodeResultSetExpressionSync" in query_notebook
            and "HasData(views=[WORKORDER])" in query_notebook,
        "Atlas AI has a datapoints tool, not only graph metadata":
            "QueryTimeSeriesDatapointsAgentToolUpsert" in atlas_chapter
            and "QueryTimeSeriesDatapointsAgentToolUpsert" in atlas_notebook,
        "Atlas AI graph scope includes evidence-bearing CDM views":
            all(view in atlas_chapter and view in atlas_notebook for view in (
                "CogniteTimeSeries", "CogniteFile", "CogniteDiagramAnnotation"
            )),
    }
    for description, holds in contracts.items():
        if not holds:
            fail(f"contract   {description}")
    return len(contracts)


def main() -> int:
    links = check_links()
    xrefs = check_crossrefs()
    n_yaml, n_python = check_fenced_blocks()
    cells = check_notebook_syntax()
    writes = check_write_blocks()
    handlers = check_write_python()
    names = check_undefined_names()
    shapes = check_chapter_shape()
    markers = check_marker_emoji()
    tables = check_chapter_tables()
    envkeys = check_env_example()
    counts = check_advertised_counts()
    attribution = check_no_attribution()
    tools = check_tools_import()
    contracts = check_query_story_contracts()

    print(f"  links            {links:>4} checked")
    print(f"  cross-references {xrefs:>4} checked")
    print(f"  yaml blocks      {n_yaml:>4} checked")
    print(f"  python blocks    {n_python:>4} checked")
    print(f"  notebook cells   {cells:>4} parsed")
    print(f"  [WRITE] blocks   {writes:>4} compared against the reference module")
    print(f"  handler blocks   {handlers:>4} compared against the reference module")
    print(f"  notebook scopes  {names:>4} cells scanned for undefined names")
    print(f"  chapter shape    {shapes:>4} chapters checked for Gate + next link")
    print(f"  marker emoji     {markers:>4} markers: consistent emoji")
    print(f"  chapter tables   {tables:>4} rows: label matches link target")
    print(f"  .env.example     {envkeys:>4} required keys present")
    print(f"  advertised counts{counts:>4} claims match the files")
    print(f"  attribution      {attribution:>4} files: no tool attribution")
    print(f"  tools import     {tools:>4} tools imported")
    print(f"  story contracts  {contracts:>4} query/agent invariants checked")
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
