#!/usr/bin/env python3
"""Score what you BUILT, not what you can remember.

    uv run python tools/assess.py              # score yourself
    uv run python tools/assess.py --tasks      # show Part B tasks and stop
    uv run python tools/assess.py --json out.json

Part A (60 pts) re-uses the chapter self-checks: did the thing the course asked for
actually land in CDF?

Part B (40 pts) is four tasks that are NOT in any chapter. You cannot copy them from the
text -- you have to understand the model well enough to extend it. Each is graded from
CDF state, so there is nothing to mark by hand and nothing to argue about.

Read-only. It never writes to your project.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from datetime import datetime, timezone

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _client import Report, cdf_client, participant  # noqa: E402

import selfcheck  # noqa: E402

from cognite.client.data_classes import filters as flt  # noqa: E402
from cognite.client.data_classes.data_modeling import ViewId  # noqa: E402

MODEL_VERSION = "v1.0.0"

# Part A: the chapter checks, weighted. Chapter 03 carries the most because the model is
# what everything else depends on.
PART_A_WEIGHTS = {
    "03": 14, "04": 6, "05": 8, "06": 2, "07": 4,
    "08": 4, "09": 4, "10": 8, "11": 3, "12": 4, "13": 3,
}

TASKS_HELP = """
PART B — four tasks. None of these appear in any chapter.

  B1  Add a `criticality` property to your WorkOrder container and expose it on the
      WorkOrder view. It must be TEXT, NOT nullable, with a default value of "MEDIUM",
      and it must carry a description. Deploy it.
      (Tests: container vs view, property attributes, redeploying a live container.)

  B2  Give CogniteEquipment a reverse route to its health profile. Create a view
      `Equipment` in your SDM space that implements cdf_cdm:CogniteEquipment and adds a
      `healthProfile` single reverse direct relation through EquipmentHealthProfile.equipment.
      Deploy it and add it to the MaintenanceInsight data model.
      (Tests: you understood section 3.9 well enough to build a second one unaided.)

  B3  The phantom asset 21-XX-9999 from Chapter 14 should not be in your graph. Remove the
      node AND make sure no work-order operation still points at it.
      (Tests: you can find and repair a dangling direct relation, not just describe one.)

  B4  Write at least 24 hourly datapoints to 21-PT-2001 for the LAST 24 HOURS, where every
      value is between 4.0 and 6.0 barg.
      (Tests: datapoints against a DMS-backed time series, with a constraint to satisfy.)

Grading is from CDF state. Run `uv run python tools/assess.py` when you are done.
"""


def part_a(client, name: str) -> tuple[float, list[tuple[str, int, int, float]]]:
    """Re-run the chapter self-checks and convert them to a weighted score."""
    rows = []
    earned = 0.0
    for chapter, weight in sorted(PART_A_WEIGHTS.items()):
        report = Report(chapter)
        try:
            selfcheck.CHECKS[chapter](client, name, report)
        except Exception as exc:  # noqa: BLE001
            report.check(f"chapter {chapter} check failed ({type(exc).__name__})",
                         str(exc)[:90], ok=False)
        checks = [r for r in report.rows if not r[1].startswith("[note]")]
        passed = sum(1 for ok, _, _ in checks if ok)
        total = len(checks)
        points = weight * (passed / total) if total else 0.0
        earned += points
        rows.append((chapter, passed, total, points))
    return earned, rows


def part_b(client, name: str, r: Report) -> None:
    isp, edm, sdm = selfcheck.spaces_for(name)

    # ---- B1: a new container property, correctly attributed ---------------------
    wo_container = client.data_modeling.containers.retrieve((edm, "WorkOrder"))
    prop = (wo_container.properties or {}).get("criticality") if wo_container else None
    r.check("B1 criticality exists on the WorkOrder container", prop is not None, True)
    if prop is not None:
        type_name = type(prop.type).__name__.lower()
        r.check("B1   it is a text property", "text" in type_name, True)
        r.check("B1   it is not nullable", prop.nullable is False, True)
        r.check("B1   its default is MEDIUM", prop.default_value, "MEDIUM")
        r.check("B1   it has a description", bool(prop.description), True)
    try:
        wo_view = client.data_modeling.views.retrieve((edm, "WorkOrder", MODEL_VERSION))[0]
        r.check("B1   it is exposed on the WorkOrder view",
                "criticality" in wo_view.properties, True)
    except IndexError:
        r.check("B1   WorkOrder view retrievable", False, True)

    # ---- B2: a second reverse direct relation, built unaided ---------------------
    try:
        equipment_view = client.data_modeling.views.retrieve((sdm, "Equipment", MODEL_VERSION))[0]
    except IndexError:
        equipment_view = None
    r.check("B2 an Equipment view exists in your SDM space", equipment_view is not None, True)
    if equipment_view is not None:
        implements = [(v.space, v.external_id) for v in (equipment_view.implements or [])]
        r.check("B2   it implements CogniteEquipment",
                ("cdf_cdm", "CogniteEquipment") in implements, True)
        hp = equipment_view.properties.get("healthProfile")
        r.check("B2   healthProfile is a single reverse direct relation",
                type(hp).__name__, "SingleReverseDirectRelation")
        if hp is not None and hasattr(hp, "through"):
            r.check("B2   it traverses EquipmentHealthProfile.equipment",
                    getattr(hp.through, "identifier", None), "equipment")
        models = client.data_modeling.data_models.retrieve((sdm, "MaintenanceInsight", MODEL_VERSION))
        listed = [v.external_id if hasattr(v, "external_id") else v[1]
                  for v in (models[0].views if models else [])]
        r.check("B2   it is published in MaintenanceInsight", "Equipment" in listed, True)

    # ---- B3: the phantom is gone, and nothing points at it ----------------------
    phantom = client.data_modeling.instances.retrieve(nodes=(isp, "21-XX-9999")).nodes
    r.check("B3 the phantom node 21-XX-9999 is gone", len(phantom), 0)
    activity = ViewId("cdf_cdm", "CogniteActivity", "v1")
    still_pointing = client.data_modeling.instances.list(
        sources=activity, space=isp, limit=-1,
        filter=flt.ContainsAny(activity.as_property_ref("assets"),
                               [{"space": isp, "externalId": "21-XX-9999"}]))
    r.check("B3   nothing still references it",
            sorted(n.external_id for n in still_pointing), [])

    # ---- B4: datapoints, in range, in the right window --------------------------
    now = datetime.now(timezone.utc)
    points = client.time_series.data.retrieve(
        instance_id=(isp, "21-PT-2001"),
        start="24h-ago", end="now", limit=None)
    values = list(getattr(points, "value", []) or [])
    r.check("B4 at least 24 datapoints in the last 24 h on 21-PT-2001",
            len(values) >= 24, True)
    r.note("B4   datapoints found", len(values))
    if values:
        lo, hi = min(values), max(values)
        r.check("B4   every value is between 4.0 and 6.0", 4.0 <= lo and hi <= 6.0, True)
        r.note("B4   observed range", f"{lo:.3f} .. {hi:.3f}")


def grade(score: float) -> str:
    if score >= 90:
        return "DISTINCTION"
    if score >= 75:
        return "PASS"
    if score >= 60:
        return "PASS (marginal)"
    return "NOT YET"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", action="store_true", help="print Part B tasks and exit")
    parser.add_argument("--json", metavar="PATH", help="write the result to a JSON file")
    args = parser.parse_args()

    if args.tasks:
        print(TASKS_HELP)
        return 0

    client = cdf_client("course-assessment")
    name = participant()
    print(f"\n  ASSESSMENT · {name} · project {client.config.project}")
    print("  " + "=" * 62)

    print("\n  PART A — what the course asked you to build (60 pts)\n")
    a_points, a_rows = part_a(client, name)
    for chapter, passed, total, points in a_rows:
        bar = "." * (18 - len(f"Chapter {chapter}"))
        flag = "" if passed == total else "   <-- incomplete"
        print(f"    Chapter {chapter}{bar} {passed}/{total} checks"
              f"   {points:5.1f} / {PART_A_WEIGHTS[chapter]:>2} pts{flag}")
    print(f"\n    Part A subtotal: {a_points:.1f} / 60")

    print("\n  PART B — four tasks that are in no chapter (40 pts)\n")
    report = Report("B")
    try:
        part_b(client, name, report)
    except Exception as exc:  # noqa: BLE001
        report.check(f"Part B could not run ({type(exc).__name__})", str(exc)[:90], ok=False)
    checks = [r for r in report.rows if not r[1].startswith("[note]")]
    b_passed = sum(1 for ok, _, _ in checks if ok)
    b_points = 40 * (b_passed / len(checks)) if checks else 0.0
    width = max(len(label) for _, label, _ in report.rows)
    for ok, label, detail in report.rows:
        if label.startswith("[note]"):
            print(f"         {label[6:].strip():<{width}}  {detail}")
        else:
            print(f"    [{'PASS' if ok else 'FAIL'}] {label:<{width}}  {detail}")
    print(f"\n    Part B subtotal: {b_points:.1f} / 40  ({b_passed}/{len(checks)} checks)")

    total = a_points + b_points
    verdict = grade(total)
    print("\n  " + "=" * 62)
    print(f"  TOTAL {total:.1f} / 100 — {verdict}")
    if verdict == "NOT YET":
        print("  Re-read the incomplete chapters above, fix, and run this again.")
    print("  " + "=" * 62 + "\n")

    result = {
        "participant": name,
        "project": client.config.project,
        "assessed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "part_a": round(a_points, 1),
        "part_b": round(b_points, 1),
        "total": round(total, 1),
        "verdict": verdict,
        "chapters": {c: f"{p}/{t}" for c, p, t, _ in a_rows},
        "part_b_checks": {label: ok for ok, label, _ in report.rows
                          if not label.startswith("[note]")},
    }
    # Tamper-EVIDENT, not tamper-proof: anyone can recompute this. It exists so an
    # accidentally edited result is obvious, not to stop a determined forger.
    payload = json.dumps(result, sort_keys=True, separators=(",", ":"))
    result["checksum"] = hashlib.sha256(payload.encode()).hexdigest()[:16]

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(result, indent=2) + "\n")
        print(f"  result written to {args.json} (checksum {result['checksum']})\n")

    return 0 if total >= 75 else 1


if __name__ == "__main__":
    sys.exit(main())
