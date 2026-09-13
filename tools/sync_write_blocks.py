"""Regenerate the YAML in chapter [WRITE] blocks from the reference module.

The companion to sync_handlers.py, and the fix side of check_docs.py's `drift`
check: the chapters and training/modules/reference/ must never disagree, because
a learner types what the chapter shows and the live checks grade what the
reference deploys.

Anchored on the [WRITE] label, which names the target file -- never on block
content, because `space: isp_...` opens many different resource types.

    uv run python tools/sync_write_blocks.py            # report
    uv run python tools/sync_write_blocks.py --write    # apply
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REF = ROOT / "training" / "modules" / "reference"
DOCS = ROOT / "docs"

SUBS = [
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

# a chapter names the participant-prefixed file; the reference module does not
PREFIXES = ("tra_", "fnc_", "wkf_", "rwt_", "dts_", "loc_", "rwd_")


def render(text: str) -> str:
    for a, b in SUBS:
        text = text.replace(a, b)
    return text.rstrip("\n")


def reference_files() -> dict:
    by_name = {}
    for path in REF.rglob("*.yaml"):
        by_name.setdefault(path.name, path)
        for prefix in PREFIXES:
            if path.name.startswith(prefix):
                aliased = path.name.replace(prefix, f"{prefix}<YOURNAME>_", 1)
                by_name.setdefault(aliased, path)
    return by_name


PAT = re.compile(
    r"(\[WRITE\]`\s*`(?P<path>[^`]+?)`.*?\n)"      # the label, capturing the path
    r"(?P<between>(?:(?!```)[\s\S])*?)"            # prose up to the fence
    r"```yaml\n(?P<body>[\s\S]*?)```",
    re.M,
)


def main() -> int:
    write = "--write" in sys.argv
    by_name = reference_files()
    rewritten = insync = unknown = touched = 0
    report = []

    for md in sorted(DOCS.glob("*.md")):
        text = md.read_text()
        out, last, dirty = [], 0, False
        for m in PAT.finditer(text):
            name = pathlib.PurePosixPath(m.group("path").strip()).name
            ref = by_name.get(name)
            if ref is None:
                unknown += 1
                continue
            want = render(ref.read_text())
            if m.group("body").rstrip("\n").strip() == want.strip():
                insync += 1
                continue
            rewritten += 1
            report.append(f"  {md.name}: {name}")
            out.append(text[last:m.start("body")])
            out.append(want + "\n")
            last = m.end("body")
            dirty = True
        if dirty and write:
            out.append(text[last:])
            md.write_text("".join(out))
            touched += 1

    for line in report:
        print(line)
    verb = "rewritten" if write else "would change"
    print(f"\n  {rewritten} [WRITE] yaml block(s) {verb}, {insync} already in sync, "
          f"{unknown} label(s) with no reference file")
    if rewritten and not write:
        print("  re-run with --write to apply")
    if write and touched:
        print(f"  {touched} chapter(s) touched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
