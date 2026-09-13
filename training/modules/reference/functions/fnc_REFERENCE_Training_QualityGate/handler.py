"""The quality gate: assert the last contextualization run, and fail if it is bad.

A count is not a gate until something goes red on it. Every number written by
`_write_spine` in MatchDocuments is checked here, and the distinction that matters is
between two kinds of failure:

* `failedCount` and a `status` that is not `completed` are **bugs** -- code that threw,
  or a job that died. They are never acceptable at any threshold.
* `unresolvedCount`, `reviewCount` and `staleRemovedCount` are **data quality**. They
  have budgets, the budgets live in envVars, and exceeding one is a business decision
  to make, not a crash to debug.

Conflating those two is how a crashing pipeline gets explained away as "the data is
messy this week" for six months.

Returns a report and raises on failure, because a Workflow task only goes red if the
Function does. Returning `{"passed": false}` produces a green workflow with a sad
message in it, which nobody will ever see.
"""

import os

from cognite.client.data_classes.data_modeling import ViewId


class QualityGateFailed(AssertionError):
    """Raised when a run breaches a threshold. The Workflow task fails with this."""


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def handle(client, data=None, secrets=None, function_call_info=None) -> dict:
    space = os.environ["INSTANCE_SPACE"]
    sdm = os.environ["SCHEMA_SPACE_SDM"]
    version = os.environ.get("MODEL_VERSION", "v1.0.0")
    data = data or {}

    run_view = ViewId(sdm, "ContextualizationRun", version)
    runs = client.data_modeling.instances.list(sources=run_view, space=space, limit=-1)
    if not runs:
        raise QualityGateFailed(
            "no ContextualizationRun records exist -- either contextualization never "
            "ran, or it ran and wrote no provenance at all. Both are failures.")

    # A caller can pin the gate to one run; a Workflow passes the ID its own first task
    # produced, so the gate cannot accidentally pass on last night's healthy run.
    wanted = data.get("runId")
    if wanted:
        picked = [n for n in runs if n.properties[run_view].get("runId") == wanted]
        if not picked:
            raise QualityGateFailed(f"run {wanted!r} was never recorded")
        run = picked[0]
    else:
        run = max(runs, key=lambda n: n.properties[run_view].get("startedTime") or "")

    p = dict(run.properties[run_view])
    failures: list[str] = []

    # ---- bugs: never acceptable ---------------------------------------------------
    if p.get("status") != "completed":
        failures.append(
            f"status is {p.get('status')!r}, not 'completed' -- the run never finished. "
            "A run still marked 'running' is a Function that died without saying so.")
    if (p.get("failedCount") or 0) > 0:
        failures.append(
            f"failedCount={p.get('failedCount')} -- items errored. This is a bug in the "
            "pipeline, not a data quality problem, and no threshold makes it acceptable.")

    # ---- data quality: budgeted ---------------------------------------------------
    budgets = [
        ("unresolvedCount", _int("MAX_UNRESOLVED", 0),
         "documents no rung could resolve"),
        ("reviewCount", _int("MAX_REVIEW_BACKLOG", 10),
         "suggestions waiting on a human -- the backlog is growing faster than it is worked"),
        ("staleRemovedCount", _int("MAX_STALE_REMOVED", 5),
         "links a previous run made and this one no longer produces -- somebody changed "
         "a rule, or a source system renamed things"),
    ]
    for field, budget, why in budgets:
        actual = p.get(field) or 0
        if actual > budget:
            failures.append(f"{field}={actual} exceeds the budget of {budget}: {why}")

    report = {
        "runId": p.get("runId"),
        "technique": p.get("technique"),
        "rulesVersion": p.get("rulesVersion"),
        "checked": {f: p.get(f) or 0 for f, _, _ in budgets},
        "budgets": {f: b for f, b, _ in budgets},
        "status": p.get("status"),
        "failedCount": p.get("failedCount") or 0,
        "passed": not failures,
    }
    if failures:
        report["failures"] = failures
        raise QualityGateFailed(
            f"quality gate failed for run {p.get('runId')}:\n  - "
            + "\n  - ".join(failures))
    return report
