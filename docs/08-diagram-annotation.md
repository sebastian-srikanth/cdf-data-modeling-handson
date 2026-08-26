# Chapter 08 — Diagram Annotation

**Goal:** find every equipment tag written on the Area 21 P&ID and turn each into a
real, queryable graph edge — via notebook first, then a packaged Function — while
learning to probe a genuinely flaky platform job safely.

---

## 8.1 [INFO] Why this capability exists in the lab architecture

A P&ID is a picture with text on it. `diagrams.detect` is CDF's engineering-diagram
OCR + entity-matching pipeline: give it a list of "entities" (your assets, by name)
and a file, and it finds where each entity's name appears on the page, returning a
bounding box and confidence per hit. You turn each hit into a **diagram annotation
edge**: edge **type** `cdf_cdm:diagrams.AssetLink`, with properties from the edge
**view** `cdf_cdm:CogniteDiagramAnnotation/v1` (page box, confidence, status). That is
what lets Fusion draw a clickable highlight on the rendered PDF.

---

## 8.2 [INFO] The job lifecycle

```
Queued → Distributed → Completed | Failed | TimedOut
```

📚 `[DOCS]` https://docs.cognite.com/cdf/integration/guides/contextualization/diagram_parsing ·
https://docs.cognite.com/cdf/integration/guides/contextualization/parse_diagrams ·
https://docs.cognite.com/cdf/integration/guides/contextualization/troubleshooting

🚧 `[LIMITS]` / ⚠️ `[COMMON MISTAKE]` — **known platform caveat, verified in this
training project: detect jobs can get stuck at `Distributed` and stay there.** There
is **no cancel API**. Deleting the source file does **not** clear a stuck job. The
only safe response is: **stop submitting new detect jobs and escalate** — repeatedly
resubmitting does not un-stick anything, it just queues more jobs behind the stuck
one and makes the backlog worse.

This is exactly why the workflow you build in [Chapter 12](12-workflows.md)
**deliberately leaves `detect_diagram_tags` out of the orchestrated pipeline** — it's
called manually, once, exactly as you're about to do. Follow the same
discipline: call it once, verify the result, and don't loop retries against it hoping
for a different outcome.

---

## 8.3 [INFO] Annotations as edges, and the ACLs that gate them

A diagram hit is stored as an **edge** (not a node). Two CDM identifiers matter:

| Role | Value | Used where |
|---|---|---|
| Edge **type** | `cdf_cdm:diagrams.AssetLink` | `EdgeApply(..., type=DirectRelationReference(...))` |
| Edge **view** | `cdf_cdm:CogniteDiagramAnnotation/v1` | `sources=[NodeOrEdgeData(source=view, properties=...)]` |

The view (`used_for: edge`) defines properties — `startNodePageNumber`, `startNodeText`,
`startNodeXMin/XMax/YMin/YMax`, `confidence`, `status` (`Suggested` by default). Do
**not** put the view external id in `type=` — that returns HTTP 400
(*Node with external id 'CogniteDiagramAnnotation' was referenced…*).

Status **polling** for a detect job requires `diagramParsingAcl` +
`annotationsAcl` — both already verified present on the training SP
([Chapter 02](02-auth-and-security.md), §2.2). If your interactive login 403s on a
detect call but the SP-run transformation-equivalent would work, that's the
two-identity gap from §2.3 — not a bug in this chapter.

---

## 8.4 [WRITE] + [ACTION] Notebook: `02_diagram_detect.ipynb`

📝 `[WRITE]` Recreate `docs/notebooks/02_diagram_detect.ipynb`. Cell
order: auth → list your 5 equipment assets as detect "entities" → submit `detect` →
poll status **safely** (bounded attempts, not a tight loop) → inspect returned
annotations → create the edges → bridge to the Function.

🟢 `[ACTION]` Run it. Key moves inside:

```python
entities = [
    {"externalId": a.external_id, "space": space, "name": [props.get("name") or a.external_id, a.external_id]}
    for a, props in asset_props  # built from CogniteAsset properties
]

job = client.diagrams.detect(
    entities=entities,
    search_field="name",
    file_instance_ids=[NodeId(space, f"file_{YOURNAME}_TRN_PID_21_SEP")],
    partial_match=True,
    min_tokens=2,
)
```

Poll safely — a **small, bounded** number of attempts with sleeps, printing status
every time, never a silent infinite `while True`. **Call `job.update_status()` each
iteration** — reading a bare `job.status` does *not* refresh it:

```python
for attempt in range(20):
    status = job.update_status()   # refreshes .status; bare job.status stays stale
    print("attempt", attempt, "status", status)
    if status in ("Completed", "Failed", "TimedOut"):
        break
    time.sleep(10)
```

⚠️ `[COMMON MISTAKE]` Reading `job.status` in a loop **without** `job.update_status()`.
The attribute never refreshes on its own — the same trap as the entity-matching
`predict` job in [Chapter 07](07-entity-matching.md) — so you spin all 20 attempts on a
stale value and wrongly conclude the job "never finished." Refresh every iteration.

⚠️ `[COMMON MISTAKE]` Looping forever without a cap "just to be sure it finishes."
Given §8.2's caveat, an uncapped loop against a stuck `Distributed` job is precisely
how you turn a two-minute notebook cell into a hung kernel. Bound every poll.

💡 `[GOOD TO KNOW]` — **the result is two levels deep.** `job.result` (= `job.get_result()`)
returns `{"items": [...]}` where each `items[]` entry is one **file block**, and the
real detections live in that block's **`annotations`** list. Each annotation carries
**`entities`** (the matched assets) and a **`region`** whose box is a **`vertices`**
polygon (normalized `{x, y}` points), *not* `xMin/xMax`. So you walk
**`items[] → annotations[] → entities[]`** and build the bounding box from the `min`/`max`
of the vertices — exactly what the Function handler in §8.5 does. Reading
`entities`/`region` off the top-level `items[]` entry (the obvious first guess) finds
nothing and silently creates **zero** edges.

✅ `[VERIFY]` notebook results in CDF: after creating the edges, open the P&ID file in
Fusion — you should see clickable bounding boxes on the rendered PDF over the tags
`21-VG-2001`, `21-PA-2001A`, `21-PA-2001B`, `21-HA-2001`, `21-XV-2001` (or a subset,
if OCR didn't find every tag — see §8.6).

---

## 8.5 [WRITE] The Function: `DetectDiagramTags`

### What this Function does

It reads the **pixels** of your P&ID PDF, finds text that looks like one of your equipment
tags, and records *where on the page* each one appears. The output is not a list — it is a
set of **edges** in the graph, so a P&ID becomes navigable: click a pump, jump to its
drawing, with a highlight box already positioned.

### Why the output is edges, not properties

An annotation is inherently a **relationship between two things** — *this file* mentions
*this asset*, at *these coordinates*. A property on the file could hold a list of tags, but
it could not carry per-link data like the confidence score or the bounding box, and it could
not be traversed from the asset side. Modelling it as a diagram annotation **edge**
(`type=diagrams.AssetLink`, properties from view `CogniteDiagramAnnotation`)
gives you both directions and a place to hang the per-link attributes.

### The one thing that trips everyone up

The `detect` response is nested two levels deep, and the box is a **polygon**, not a
rectangle:

```
result["items"]           ← one block PER FILE (not per detection)
  └─ block["annotations"] ← the actual detections live here
       └─ ann["region"]["vertices"]  ← [{x,y}, {x,y}, …] normalized 0–1
                                        NOT xMin/xMax — you compute those yourself
```

Reaching for `result["annotations"]` or `region["xMin"]` is the most common way to get zero
annotations out of a job that actually succeeded.

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/functions/fnc_<YOURNAME>_Training_DetectDiagramTags/handler.py`

```python
"""Detect tags on the Area 21 P&ID and create CogniteDiagramAnnotation edges.

diagrams.detect returns items[] (one block per file); each block's annotations[] holds
the detections. Each annotation carries entities[] (the matched assets) and a region
whose box is a vertices[] polygon (normalized 0-1), not xMin/xMax.
"""

from __future__ import annotations

import os

from cognite.client.data_classes.data_modeling import (
    DirectRelationReference,
    EdgeApply,
    NodeId,
    NodeOrEdgeData,
    ViewId,
)

EQUIPMENT_TAGS = ["21-VG-2001", "21-PA-2001A", "21-PA-2001B", "21-HA-2001", "21-XV-2001"]


def _bbox(region: dict) -> tuple[float, float, float, float]:
    """(xMin, xMax, yMin, yMax) from a region's vertices polygon."""
    verts = region.get("vertices") or []
    xs = [float(v["x"]) for v in verts if isinstance(v, dict) and "x" in v]
    ys = [float(v["y"]) for v in verts if isinstance(v, dict) and "y" in v]
    if xs and ys:
        return min(xs), max(xs), min(ys), max(ys)
    return 0.0, 0.1, 0.0, 0.1  # degenerate fallback if the API omits vertices


def handle(client, data=None, secrets=None, function_call_info=None) -> dict:
    participant = os.environ["PARTICIPANT"]
    space = os.environ["INSTANCE_SPACE"]
    file_xid = f"file_{participant}_TRN_PID_21_SEP"
    v_asset = ViewId("cdf_cdm", "CogniteAsset", "v1")
    view = ViewId("cdf_cdm", "CogniteDiagramAnnotation", "v1")

    assets = client.data_modeling.instances.list(
        instance_type="node", sources=[v_asset], space=space, limit=-1,
    )
    asset_xids = {a.external_id for a in assets}
    entities = []
    for a in assets:
        name = a.properties.get(v_asset, {}).get("name") or a.external_id
        entities.append({"externalId": a.external_id, "space": space, "name": [name, a.external_id]})

    job = client.diagrams.detect(
        entities=entities, search_field="name",
        file_instance_ids=[NodeId(space, file_xid)],
        partial_match=True, min_tokens=2,
    )
    result = job.result  # blocks until the job completes; returns {"items": [...]}

    edges: list[EdgeApply] = []
    tags_found: list[str] = []
    idx = 0

    # items[] is one block PER FILE; the detections live in block["annotations"].
    for block in (result.get("items") if isinstance(result, dict) else []) or []:
        for ann in block.get("annotations") or []:
            region = ann.get("region") or {}
            page = int(region.get("page") or ann.get("page") or 1)
            text = ann.get("text") or ""
            confidence = float(ann.get("confidence") or 0.0)
            x_min, x_max, y_min, y_max = _bbox(region)

            seen: set[str] = set()  # the API can list the same entity twice
            for ent in ann.get("entities") or []:
                asset_xid = ent.get("externalId") if isinstance(ent, dict) else str(ent)
                if not asset_xid or asset_xid in seen or asset_xid not in asset_xids:
                    continue
                seen.add(asset_xid)
                edges.append(EdgeApply(
                    space=space,
                    external_id=f"anno_{file_xid}_{asset_xid}_{idx}",
                    # Edge TYPE (not the view externalId). View is CogniteDiagramAnnotation.
                    type=DirectRelationReference("cdf_cdm", "diagrams.AssetLink"),
                    start_node=DirectRelationReference(space, file_xid),
                    end_node=DirectRelationReference(space, asset_xid),
                    sources=[NodeOrEdgeData(source=view, properties={
                        "name": text or asset_xid,
                        "confidence": confidence,
                        "status": "Suggested",
                        "startNodePageNumber": page,
                        "startNodeText": text or asset_xid,
                        "startNodeXMin": x_min, "startNodeXMax": x_max,
                        "startNodeYMin": y_min, "startNodeYMax": y_max,
                    })],
                ))
                if asset_xid not in tags_found:
                    tags_found.append(asset_xid)
            idx += 1

    if edges:
        client.data_modeling.instances.apply(edges=edges)

    tags_missing = [t for t in EQUIPMENT_TAGS if t not in tags_found]
    return {
        "annotations_created": len(edges),
        "tags_found": tags_found,
        "tags_missing": tags_missing,
    }
```

### Line-by-line walkthrough

| Code | What it does | Why it is written this way |
|---|---|---|
| `EQUIPMENT_TAGS = [...]` | The five tags you *expect* on this drawing | Used only at the end to compute `tags_missing`. Declaring the expectation up front turns a silent partial result into a visible one |
| `_bbox(region)` | Converts a `vertices[]` polygon into `(xMin, xMax, yMin, yMax)` | The API returns a polygon because a detection can be rotated; the data model wants an axis-aligned box. `min`/`max` over the vertices is that conversion |
| `return 0.0, 0.1, 0.0, 0.1` | Degenerate fallback box | If the API omits `vertices`, a tiny corner box is written rather than crashing. You still get the annotation; only its highlight is wrong |
| `entities.append({... "name": [name, a.external_id]})` | Gives each asset **two** searchable names | A P&ID may print either the description or the tag. Supplying both as a list means either spelling matches — one asset, two aliases |
| `search_field="name"` | Tells `detect` which field to match on | Pairs with the `name` list built above |
| `file_instance_ids=[NodeId(space, file_xid)]` | Targets your P&ID **as a DMS node** | `NodeId(space, …)` again — the `(space, externalId)` identity pair. Your file, not anyone else's identically-named one |
| `partial_match=True` | Accepts near-misses in OCR text | Real drawings are noisy: a hyphen renders as an en-dash, a `0` reads as `O`. Exact-only matching finds almost nothing on a scanned P&ID |
| `min_tokens=2` | Requires ≥2 tokens to match | `21-PA-2001A` is several tokens. Allowing single-token matches makes bare numbers like `2001` match everything — this is the main precision dial |
| `result = job.result` | **Blocks** until the job finishes | Note the contrast with Chapter 07, which polls manually. Here the SDK does the waiting for you |
| `for block in result.get("items")` | Outer loop = one block **per file** | Not per detection. See the diagram above — this is the level everyone skips |
| `for ann in block.get("annotations")` | Inner loop = the actual detections | |
| `seen: set[str] = set()` | Dedupes entities inside one annotation | The API can list the same entity twice for a single detection; without this you would write two identical edges |
| `asset_xid not in asset_xids` | Ignores anything that is not one of **your** assets | A hard isolation guard — never write an edge pointing outside your own space |
| `external_id=f"anno_{file_xid}_{asset_xid}_{idx}"` | Deterministic edge ID | Same inputs produce the same ID, so re-running **overwrites** rather than duplicating. That is what makes this Function safe to re-run |
| `type=DirectRelationReference("cdf_cdm", "diagrams.AssetLink")` | Declares the edge **type** | Must be `diagrams.AssetLink`. The view `CogniteDiagramAnnotation` goes only in `sources=` — using it as `type=` causes HTTP 400 |
| `start_node` = file, `end_node` = asset | Direction: *file mentions asset* | Reversing this would read "asset mentions file", which is not what happened |
| `"status": "Suggested"` | Marks the annotation as machine-generated | The core model distinguishes suggested from human-approved. Never write `"Approved"` from an automated job — a person has not looked at it yet |
| `startNodeXMin` … `startNodeYMax` | Where the highlight box sits | Normalized 0–1, so it scales to any zoom level or render size |
| `instances.apply(edges=edges)` | One batched write | A single call for all edges, not one call per edge |
| `tags_missing = [...]` | What was expected but **not** found | An honest result. A Function that reports only successes hides its failures |

⚠️ `[COMMON MISTAKE]` `type=DirectRelationReference("cdf_cdm", "CogniteDiagramAnnotation")`
looks plausible because that is the view name, but CDF treats `type` as a separate
edge-type id. Live API check: that call returns 400
(*Node with external id 'CogniteDiagramAnnotation' was referenced…*). Use
`diagrams.AssetLink` instead.

📚 `[DOCS]` [Diagram parsing](https://docs.cognite.com/cdf/integration/guides/contextualization/parse_diagrams) ·
[Cognite Functions](https://docs.cognite.com/cdf/functions/) ·
[Data modeling](https://docs.cognite.com/cdf/dm/)

📝 `[WRITE]` `requirements.txt`: `cognite-sdk==8.10.0`

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/functions/DetectDiagramTags.Function.yaml`

```yaml
externalId: fnc_<YOURNAME>_Training_DetectDiagramTags
name: fnc_<YOURNAME>_Training_DetectDiagramTags
owner: Training
description: Run diagram detect on the Area 21 P&ID and create CogniteDiagramAnnotation edges.
functionPath: handler.py
runtime: py311
dataSetExternalId: dts_<YOURNAME>_Training_TRN
envVars:
  PARTICIPANT: "<YOURNAME>"
  INSTANCE_SPACE: "isp_<YOURNAME>_TRN"
  SCHEMA_SPACE_EDM: "ssp_<YOURNAME>_TrainingCore_edm"
  SCHEMA_SPACE_SDM: "ssp_<YOURNAME>_MaintenanceInsight_sdm"
  DATASET: "dts_<YOURNAME>_Training_TRN"
  MODEL_VERSION: "v1.0.0"
```

---

## 8.6 [ACTION] Build, deploy, run — once

```bash
uv run cdf build --config-yaml training/config.<YOURNAME>-training.yaml
uv run cdf deploy --cdf-project <your-cdf-project> --include functions
```

🟢 `[ACTION]` Call it **once**:

```python
result = client.functions.call(external_id="fnc_<YOURNAME>_Training_DetectDiagramTags")
print(result.get_response())
```

✅ `[VERIFY]` `annotations_created ≥ 1` and at least one tag appears in `tags_found`.
Open the P&ID in Fusion and confirm the bounding box renders.

⚠️ `[COMMON MISTAKE]` If `tags_missing` is non-empty, **do not immediately re-call the
Function** hoping for a better OCR pass. First check the P&ID visually — is the tag
actually legible at that zoom level/rotation? Diagram OCR confidence is genuinely
lower than the other techniques in this course; a partial `tags_found` list is an
expected, acceptable outcome for this lab, not a failure to chase.

🔀 `[PR]` Per §8.2, do **not** wire `detect_diagram_tags` into your workflow DAG in
[Chapter 12](12-workflows.md) — call it manually here, exactly once, and leave it out
of the orchestrated pipeline.

---

## Gate

**Do not proceed to Chapter 09 until:**

- You have called `DetectDiagramTags` **exactly once** and it returned successfully
- At least one `CogniteDiagramAnnotation` edge exists and renders in Fusion
- You can state, from memory, why there's no cancel API workaround for a stuck
  `Distributed` job, and why that means "stop submitting, don't retry-loop"
- 📓 You have added your two or three lines for this chapter to `participants/<YOURNAME>/NOTES.md` — **now**, not tonight

→ [Chapter 09 — 3D](09-3d.md)
