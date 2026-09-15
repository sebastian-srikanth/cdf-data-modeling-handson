#!/usr/bin/env python3
"""Classify every Toolkit build insight. Fail on anything unexplained.

    CI=true uv run cdf build --config-yaml training/config.REFERENCE-training.yaml
    uv run python tools/check_build_insights.py

An offline build prints fifteen findings and "Do not proceed to deploy", then exits 0.
Both halves are defensible on their own and together they are a trap: a real modelling
error would print among fourteen expected ones, under a banner everybody has learned to
ignore, with a passing exit code.

So every insight must match a rule that says why it is expected. Anything else fails.
This does not weaken the build -- it is the only thing here that reads its output.
"""
from __future__ import annotations

import csv
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
INSIGHTS = ROOT / "build" / "insights.csv"

# (pattern, why it is expected). Each is a claim that has been checked, not a mute button.
EXPECTED = [
    (re.compile(r"cdf_cdm", re.I),
     "reference to the CDF core model. A build makes no network calls, so it cannot "
     "resolve cdf_cdm; with credentials these same resources report Ready to deploy "
     "(Chapter 00 section 0.7)"),
    (re.compile(r"Missing node .*isp_\w+_TRN:(TRN-21-SEP|21-PA-2001A)", re.I),
     "a CogniteFile names an asset node that a Chapter 05 transformation creates at run "
     "time. The reference participant is not deployed, so the build cannot see it"),
    (re.compile(r"unit\.space\[key\]|Expected one of 'externalId' or 'sourceUnit'", re.I),
     "space: cdf_units is written deliberately. Measured: with it, 0 to update; without "
     "it, 1 container to update forever (Chapter 03 section 3.7)"),
]


def main() -> int:
    if not INSIGHTS.exists():
        print(f"  no {INSIGHTS.relative_to(ROOT)} — run cdf build first")
        return 1

    rows = list(csv.DictReader(INSIGHTS.open()))
    counts: dict[str, int] = {}
    unexplained: list[dict] = []

    for row in rows:
        blob = " ".join(str(v) for v in row.values())
        for pattern, why in EXPECTED:
            if pattern.search(blob):
                counts[why] = counts.get(why, 0) + 1
                break
        else:
            unexplained.append(row)

    print(f"\n  {len(rows)} build insight(s) classified\n")
    for why, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>3} expected  {why}")

    if unexplained:
        print(f"\n  {len(unexplained)} UNEXPLAINED — these are real:")
        for row in unexplained:
            print(f"    {row.get('insight_type')}  {row.get('source_file')}")
            print(f"      {row.get('message', '')[:160]}")
        print("\n  A build insight nobody has classified is a modelling error hiding in "
              "a crowd of expected ones.")
        return 1

    print("\n  every insight is accounted for")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
