#!/usr/bin/env python3
"""Run a room, not one laptop.

    uv run python tools/cohort.py preflight  roster.txt   # can this project take them?
    uv run python tools/cohort.py board      roster.txt   # who is where, right now
    uv run python tools/cohort.py provision  roster.txt   # write each module + config
    uv run python tools/cohort.py sweep      roster.txt   # what is left behind afterwards

A roster is a text file, one participant name per line. Blank lines and #comments are
ignored. Names become isp_<NAME>_TRN and friends, so use the same casing the participant
will put in their .env.

`board` is the one that matters. It runs the chapter self-checks for every participant and
prints a grid, so you can see that four people are stuck on Chapter 05 before any of them
puts a hand up. Read-only.
"""
from __future__ import annotations

import pathlib
import sys

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _client import ROOT, Report, cdf_client, load_env  # noqa: E402

import selfcheck  # noqa: E402

# Deploying the course costs this much per participant. The Functions number is the one
# that bites: projects are commonly capped at 100.
PER_PARTICIPANT = {"functions": 5, "spaces": 3, "transformations": 5,
                   "raw databases": 1, "data sets": 1, "workflows": 1}
FUNCTION_CAP = 100   # the usual project limit; override with --cap

# The chapters the board reports on, in course order. 18 is excluded: it asserts the
# opposite of the others and would read as failure for everyone mid-course.
BOARD = ["03", "04", "05", "06", "07", "08", "09", "10", "11", "12", "13", "15"]


def read_roster(path: str) -> list[str]:
    roster = pathlib.Path(path)
    if not roster.is_file():
        raise SystemExit(
            f"  no roster at {roster}\n"
            f"  Expected a text file with one participant name per line, for example:\n"
            f"      ALICE\n      BRUNO\n      CHIOMA")
    lines = roster.read_text().splitlines()
    names = [l.strip() for l in lines if l.strip() and not l.lstrip().startswith("#")]
    if not names:
        raise SystemExit(f"  {path} has no names in it")
    return names


def preflight(client, names: list[str], cap: int) -> int:
    print(f"\n  PREFLIGHT · {len(names)} participant(s) · project {client.config.project}\n")
    existing = {
        "functions": len(client.functions.list(limit=-1)),
        "spaces": len(client.data_modeling.spaces.list(limit=-1)),
        "transformations": len(client.transformations.list(limit=-1)),
        "raw databases": len(client.raw.databases.list(limit=-1)),
        "data sets": len(client.data_sets.list(limit=-1)),
        "workflows": len(client.workflows.list(limit=-1)),
    }
    print(f"    {'resource':<18}{'now':>6}{'+cohort':>9}{'after':>8}")
    for resource, per in PER_PARTICIPANT.items():
        added = per * len(names)
        print(f"    {resource:<18}{existing[resource]:>6}{added:>9}{existing[resource]+added:>8}")

    problems = []
    after_functions = existing["functions"] + PER_PARTICIPANT["functions"] * len(names)
    if after_functions > cap:
        room = max(0, (cap - existing["functions"]) // PER_PARTICIPANT["functions"])
        problems.append(
            f"Functions would reach {after_functions}, over the {cap} cap. "
            f"This project has room for about {room} participant(s). "
            f"Raise the cap or split the cohort.")

    clashes = sorted(n for n in names
                     if f"isp_{n}_TRN" in {s.space for s in client.data_modeling.spaces.list(limit=-1)})
    if clashes:
        problems.append(f"these names already have spaces in this project: {clashes}")

    if problems:
        print("\n    PROBLEMS")
        for p in problems:
            print(f"      - {p}")
        return 1
    print("\n    OK — this project can take the cohort")
    return 0


def board(client, names: list[str]) -> int:
    print(f"\n  PROGRESS · {len(names)} participant(s) · project {client.config.project}")
    print(f"  a chapter is complete only when every one of its checks passes\n")
    header = "".join(f"{c:>5}" for c in BOARD)
    print(f"    {'participant':<16}{header}   up to")
    print(f"    {'-' * (16 + len(header) + 11)}")

    stuck: dict[str, list[str]] = {}
    for name in names:
        cells, done = [], []
        for chapter in BOARD:
            report = Report(chapter)
            try:
                selfcheck.CHECKS[chapter](client, name, report)
                checks = [r for r in report.rows if not r[1].startswith("[note]")]
                passed = sum(1 for ok, _, _ in checks if ok)
                total = len(checks)
            except Exception:  # noqa: BLE001 - one bad chapter must not kill the board
                passed, total = 0, 1
            if total and passed == total:
                cells.append("  ok ")
                done.append(chapter)
            elif passed:
                cells.append(f" {passed}/{total:<2}")
                stuck.setdefault(chapter, []).append(name)
            else:
                cells.append("  .  ")
        # "up to" means the last UNBROKEN run of passes. Reporting the highest chapter
        # that happens to pass would say 15 for someone who has not finished 05.
        up_to = "-"
        for chapter in BOARD:
            if chapter in done:
                up_to = chapter
            else:
                break
        print(f"    {name:<16}{''.join(cells)}   {up_to}")

    if stuck:
        print("\n    partially done — likely where they are working, or stuck:")
        for chapter, who in sorted(stuck.items()):
            print(f"      Chapter {chapter}: {', '.join(who)}")
    return 0


def provision(names: list[str]) -> int:
    """Write a participant module and config per person, from the reference module."""
    import os
    sys.path.insert(0, str(ROOT / "tools"))
    from live_e2e import materialise  # reuse the one implementation

    load_env()
    if not os.environ.get("CDF_PROJECT"):
        raise SystemExit("  CDF_PROJECT must be set — materialise writes it into each config")
    for name in names:
        materialise(name)
        print(f"    wrote training/modules/participants/{name} and config.{name}-training.yaml")
    print(f"\n    {len(names)} module(s) written. Nothing deployed — each participant "
          f"runs `cdf deploy` themselves.")
    return 0


def sweep(client, names: list[str]) -> int:
    """After the cohort: what is still out there with someone's name on it?"""
    print(f"\n  SWEEP · {len(names)} participant(s) · project {client.config.project}\n")
    spaces = {s.space for s in client.data_modeling.spaces.list(limit=-1)}
    functions = [f.external_id or "" for f in client.functions.list(limit=-1)]
    transformations = [t.external_id or "" for t in client.transformations.list(limit=-1)]
    databases = [d.name or "" for d in client.raw.databases.list(limit=-1)]
    files = [f.external_id or "" for f in client.files.list(limit=1000)]

    dirty = 0
    for name in names:
        left = []
        left += [s for s in spaces if f"_{name}_" in s or s.startswith(f"isp_{name}")]
        left += [x for x in functions if name in x]
        left += [x for x in transformations if name in x]
        left += [x for x in databases if name in x]
        left += [x for x in files if x.startswith(f"fnc_{name}_")]
        if left:
            dirty += 1
            print(f"    {name:<16} {len(left)} item(s): {left[:4]}{' …' if len(left) > 4 else ''}")
        else:
            print(f"    {name:<16} clean")
    print(f"\n    {dirty} participant(s) still have resources. Data sets are excluded — "
          f"CDF can never delete those; archived is the clean end state.")
    return 1 if dirty else 0


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["preflight", "board", "provision", "sweep"])
    parser.add_argument("roster")
    parser.add_argument("--cap", type=int, default=FUNCTION_CAP,
                        help=f"project Function limit (default {FUNCTION_CAP})")
    args = parser.parse_args()

    names = read_roster(args.roster)
    if args.command == "provision":
        return provision(names)

    client = cdf_client("course-cohort")
    if args.command == "preflight":
        return preflight(client, names, args.cap)
    if args.command == "board":
        return board(client, names)
    return sweep(client, names)


if __name__ == "__main__":
    sys.exit(main())
