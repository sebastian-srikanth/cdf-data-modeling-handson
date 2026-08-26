# Chapter 13 — Cross-Cutting Mastery

**Goal:** step back from individual resources and see the system: why every handler
you wrote is safe to re-run, how to debug any of them when something's wrong, what
this course costs at cohort scale, the one picture that makes the whole graph click,
and how to leave cleanly.

---

## 13.1 [INFO] When to use Transformation vs Function vs Workflow vs UI

| Tool | Use when |
|---|---|
| **Transformation** | Clean, deterministic RAW → model key mapping (§5.1) |
| **Function** | Fuzzy/ML/job-based/multi-step logic; anything calling an async CDF job API |
| **Workflow** | You need to encode order, parallelism, retries, and failure policy across multiple Transformations/Functions as one deployable resource |
| **UI (Fusion)** | Verifying every step above, and one-off manual inspection — never your primary deployment mechanism |

---

## 13.2 [INFO] Idempotency & re-runnability — why every handler upserts

Look back across every handler you wrote: `client.data_modeling.instances.apply(...)`
is **always** an upsert, never "create, and error if it already exists." Every
transformation sets `conflictMode: upsert` + `ignoreNullFields: true`. This isn't
incidental — it's the property that makes it *safe to run the workflow again* without
first checking "did this already run?"

⚠️ `[COMMON MISTAKE]` — **the state-pointer trap.** If you ever extend this lab with
an incremental sync Function (not part of this course, but a pattern you'll meet in
real projects), the classic bug is advancing a "last synced" checkpoint
*unconditionally* every run — even when the run found nothing new. The next run then
starts from that later point and **silently skips** whatever the source produced in
between, with no error. The fix: only advance a state pointer on **confirmed new work
done**; if a run finds nothing, leave the checkpoint where it was. None of this
course's handlers carry a state pointer (they're idempotent full-recompute instead),
which is exactly why they dodge this bug entirely — worth knowing for the day you
*do* need incremental state.

---

## 13.3 [INFO] Observability & debugging

| Resource | Where to look |
|---|---|
| Function call | Fusion → Functions → your function → Calls tab → response + logs; or `client.functions.calls.retrieve(...)` / `call.get_response()` / `call.get_logs()` |
| Transformation | Fusion → Transformations → your transformation → run history — check row counts and error messages per run |
| Workflow | Fusion → Workflows → your workflow → execution graph — per-task status, retries, and timing at a glance |
| Diagram-detect job | `POST /context/documentparser/jobs/byids`-style polling — for diagrams specifically, use `client.diagrams.retrieve_detect_jobs(...)` rather than trusting a single job object's cached status |
| Document Parser job | `POST /context/documentparser/jobs/byids` — the rich `status.job` / `status.view` / `status.validation` / `scores` breakdown from [Chapter 10](10-datasheet-parsing.md) |

⚡ `[OPTIMIZE]` — a useful debugging discipline for this whole course: when a
Function's returned dict shows something wrong (a missing field, an empty `matches`
list, an unexpected `status`), **reproduce it in the matching notebook first**, not by
re-deploying the Function with print statements sprinkled in. Every Function in this
course has a notebook sibling that runs the identical logic interactively — use it as
your debugger.

---

## 13.4 [LIMITS] Cost & quota at cohort scale

Per participant, this lab costs roughly:

| Resource | Approx. cost |
|---|---|
| Function image builds | ~5 builds × 2–10 min each |
| Data sets | 1 (archive-only at teardown — never hard-deleted) |
| Spaces | 3 (`isp_*`, two `ssp_*`) |
| 3D revisions | 1 conversion job |
| Entity-matching models | 1 per `MatchDocuments` call (always deleted after — §7.4) |

🚧 `[LIMITS]` **Multiply by cohort size.** 15 participants × 5 function builds is 75
concurrent-ish image builds if everyone starts Chapter 07 at the same moment — enough
to stall a shared build cluster. **Stagger function deploys across the cohort** rather
than having everyone hit `cdf deploy --include functions` in the same 60-second window.

---

## 13.5 [INFO] The end-state graph — one picture, not a paragraph

Everything you built converges on one hub node: `21-PA-2001A`.

```mermaid
graph TD
    FPSO["TRN-FPSO (Site)"] --> AREA["TRN-21 (Area)"]
    AREA --> SEP["TRN-21-SEP (System)"]
    SEP --> VG["21-VG-2001"]
    SEP --> PUMP["21-PA-2001A — the hero tag"]
    SEP --> PUMPB["21-PA-2001B"]
    SEP --> HA["21-HA-2001"]
    SEP --> XV["21-XV-2001"]

    EQ["EQ-1002 (Equipment)"] -->|asset| PUMP
    VT["21-VT-2002 (vibration, rising)"] -->|assets| PUMP
    FT["21-FT-2002 (flow, falling)"] -->|assets| PUMP
    PT3["21-PT-2003 (pressure)"] -->|assets| PUMP
    WO["WO-1001, IN_PROGRESS"] -->|assets| PUMP
    PID["P&ID file"] -.->|CogniteDiagramAnnotation edge| PUMP
    DS["Datasheet file"] -->|matched via entity matching| PUMP
    EHP["ehp_21-PA-2001A"] -->|asset| PUMP
    EHP -->|equipment| EQ
    EHP -->|datasheetFile| DS
    OBJ["3D CAD node"] -->|object3D| PUMP
```

**The aha moment:** `21-VT-2002` rising and `21-FT-2002` falling ([Chapter 11](11-datapoints.md))
*is* the story behind `WO-1001` ([Chapter 05](05-transformations.md)) — and now every
piece of evidence for that story (sensors, work order, datasheet, P&ID, 3D position)
is one graph walk away from the same node, in your own isolated space.

🟢 `[ACTION]` Open your location filter ([Chapter 06](06-location-filters.md)) →
`21-PA-2001A` → confirm you can reach every neighbor in the diagram above by clicking
through Fusion, not just by trusting this picture.

---

## 13.6 [PR] Self-verification checklist before you open a PR

Run this before Chapter 14. Catch problems yourself first — these are exactly the
checks a reviewer applies after merge.

```python
from cognite.client import CogniteClient
from cognite.client.data_classes.data_modeling import ViewId

client = CogniteClient()
name = "<YOURNAME>"
space = f"isp_{name}_TRN"

checks = []

spaces = {s.space for s in client.data_modeling.spaces.list(limit=-1)}
for s in (f"isp_{name}_TRN", f"ssp_{name}_TrainingCore_edm", f"ssp_{name}_MaintenanceInsight_sdm"):
    checks.append((f"space {s}", s in spaces))

ds = client.data_sets.retrieve(external_id=f"dts_{name}_Training_TRN")
checks.append(("dataset", ds is not None))

raw_dbs = {db.name for db in client.raw.databases.list(limit=-1)}
checks.append((f"raw db rwd_{name}_Training_TRN", f"rwd_{name}_Training_TRN" in raw_dbs))

for suffix in ("Assets", "Equipment", "TimeSeries", "WorkOrders"):
    xid = f"tra_{name}_Training_TRN_Load_{suffix}"
    checks.append((f"transformation {xid}", client.transformations.retrieve(external_id=xid) is not None))

for fn in ("GenerateDatapoints", "Load3DRevision", "DetectDiagramTags", "MatchDocuments", "ParseDatasheet"):
    xid = f"fnc_{name}_Training_{fn}"
    checks.append((f"function {xid}", client.functions.retrieve(external_id=xid) is not None))

checks.append(("workflow", client.workflows.retrieve(external_id=f"wkf_{name}_Training_TRN") is not None))

for view_id, expected in [
    (ViewId("cdf_cdm", "CogniteAsset", "v1"), 8),
    (ViewId("cdf_cdm", "CogniteEquipment", "v1"), 5),
    (ViewId("cdf_cdm", "CogniteTimeSeries", "v1"), 6),
]:
    n = len(client.data_modeling.instances.list(instance_type="node", sources=[view_id], space=space, limit=-1))
    checks.append((f"{view_id.external_id} count == {expected}", n == expected))

for label, ok in checks:
    print(f"  [{'OK' if ok else 'FAIL'}] {label}")
print("PASS" if all(ok for _, ok in checks) else "FAIL")
```

📋 Also confirm by hand (not scriptable, or not worth scripting for a one-person
check):

- [ ] `ehp_21-PA-2001A` is populated with `openWorkOrderCount == 1` and no glaring
  empty rated-spec fields
- [ ] Your location filter shows only your own 8 assets
- [ ] At least one `CogniteDiagramAnnotation` edge exists on your P&ID
- [ ] Your entity-matching model from Chapter 07 is confirmed **deleted**
- [ ] `21-VT-2002` visibly ramps over the last 5 days in the Fusion chart view
- [ ] Your workflow's last execution completed (3D task may show `skipped`)

---

## 13.7 [PR] Teardown literacy

You are not tearing down yet — that happens after your PR is merged and you're done
with the lab for the day, or if you need to reset and start clean. When you get there,
**[Chapter 15 — Teardown](15-teardown.md)** and its companion notebook
(`notebooks/06_teardown.ipynb`) walk the exact sequence: SDK deletes for your global
resources, then `cdf data purge space` for your spaces (instance space first, then
schema spaces; data sets archive, never hard-delete).

⚠️ `[COMMON MISTAKE]` Treating a data set like anything else you can delete. CDF has
**no hard delete** for data sets — the clean end state is *archived*, not gone.

`cdf data purge space` is **manual-confirmation only** by design — you must type the
CDF project name at the prompt, not just `y`. This is a deliberate speed bump on a
destructive, irreversible operation.

---

## Gate

**Do not proceed to Chapter 14 until:**

- The self-verification script above prints `PASS`
- Every item in the manual checklist is checked
- You can explain what makes a handler "idempotent" and name which course pattern
  this lab deliberately avoids needing (the state-pointer trap)
- You know where you'll look first when a Function, Transformation, or Workflow task
  fails, for each of the three
- 📓 You have added your two or three lines for this chapter to `participants/<YOURNAME>/NOTES.md` — **now**, not tonight

→ [Chapter 14 — PR & Merge](14-pr-and-merge.md)
