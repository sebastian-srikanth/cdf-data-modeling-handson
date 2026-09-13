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

This shapes how the task is orchestrated later. In
[Chapter 12](12-workflows.md) `detect_diagram_tags` **is** in the pipeline, but it is one
of only two tasks carrying `onFailure: skipTask` with `retries: 1` — the workflow is
allowed to finish without it, and it is never allowed to retry-loop. Contain a flaky
dependency; don't let it abort the run, and don't let it hammer the service. Right now,
before any of that, call it **once** by hand and read the result.

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
([Chapter 02](02-auth-and-security.md), section 2.2). If your interactive login 403s on a
detect call but the SP-run transformation-equivalent would work, that's the
two-identity gap from section 2.3 — not a bug in this chapter.

---

## 8.3b [INFO] What you can tune — and the symbol library you cannot deploy

Everyone asks the same question at this point: *can I load my own symbol library so it
recognises a pump from its shape?*

**Yes — but not with the API this chapter uses.** CDF has two different diagram
capabilities and conflating them is the mistake:

| | **Tag detection** (this chapter) | **Full diagram parsing** |
|---|---|---|
| What it matches | **text** — strings matching entities you supply | **symbols**, via a symbol library you choose |
| Also produces | tag annotations | geometries, connections between symbols, pipe-connectivity verification |
| Input | any PDF, scanned or vector | **vector diagrams only** |
| Driven from | `client.diagrams.detect` — automatable, what your Function calls | Fusion's parsing UI, with Symbols and Connections tabs for review |
| In the pinned SDK | yes | **no** — `client.diagrams` has exactly three methods: `detect`, `convert`, `get_detect_jobs` |

🚧 `[LIMITS]` So: **symbol libraries exist in CDF, and they are not reachable from the API
this Function uses.** If your drawings are vector and you need symbol and connection
topology — *which pipe runs from which pump to which valve* — that is Full diagram
parsing, and today you drive it from Fusion rather than from a Cognite Function. If your
drawings are scans, symbol detection is not available to you at all and tag detection is
the whole game.

📚 `[DOCS]` https://docs.cognite.com/cdf/integration/guides/contextualization/parse_diagrams

⚠️ `[COMMON MISTAKE]` Choosing the capability by ambition rather than by input. Full
diagram parsing is strictly better *if* your diagrams are vector. Run it on a scanned
1990s P&ID and you get nothing — and the failure is silent, because there are simply no
paths to detect.

### What you can tune on the path you are automating

Since this chapter automates tag detection, the quality levers are matching parameters,
and **that is where the real work is**:

| Parameter | What it decides |
|---|---|
| `substitutions` | which strings mean the same thing — `PMP` is a `PUMP`. **The closest thing to a library, and it is yours to maintain** |
| `min_fuzzy_score` / `customize_fuzziness` | how close is close enough. The precision/recall dial |
| `read_embedded_text` | vector PDFs carry real text. Read it; OCR is the fallback, not the default |
| `remove_leading_zeros` | `21-PA-2001` vs `21-PA-02001`. The same class of bug [Chapter 05](05-transformations.md) fixes with `lpad`, on the other side |
| `case_sensitive`, `partial_match`, `min_tokens` | matching strictness |
| `pattern_mode` | detect tags by *pattern* instead of a fixed entity list |

### The alias library belongs in RAW, for the same reason the mapping rules do

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/raw/rwt_Training_TRN_TagAliases.Table.yaml`

```yaml
dbName: rwd_<YOURNAME>_Training_TRN
tableName: rwt_Training_TRN_TagAliases
```

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/raw/rwt_Training_TRN_TagAliases.Table.csv`

```text
key,canonical,aliases,addedBy,reason
alias-001,PUMP,PMP|P,course,Older drawing revisions abbreviate PUMP; the 2011 sheets use P.
alias-002,VALVE,VLV|V,course,VLV is the vendor's abbreviation; V appears on the isometrics.
alias-003,SEPARATOR,SEP|SEPR,course,SEP is used on the P&ID title block and SEPR in the equipment list.
alias-004,HEAT EXCHANGER,HX|HE,course,HX on the P&ID, HE in the SAP equipment master.
```

Aliases are pipe-separated because a comma would fight the CSV. `addedBy` and `reason`
are here for the same reason as in [Chapter 07](07-entity-matching.md) section 7.2: in a
year, *"who decided VLV means VALVE, and is that still true for this vendor"* is the only
question that matters.

💡 `[GOOD TO KNOW]` An alias library is **not** a symbol library — it is the other half of
the problem. Full diagram parsing teaches CDF what a pump *looks like*; this teaches it
what a pump is *called* on your drawings. On scanned diagrams the second is all you have,
and even on vector ones a drawing office that changed its abbreviation in 2011 costs you
detections that no shape model recovers.

⚠️ `[COMMON MISTAKE]` Tuning `min_fuzzy_score` down until the count looks good. Every
point you lower it buys detections and sells precision, and a wrong annotation is worse
than a missing one — it silently attaches a document to the wrong asset, and nobody
checks a link that already exists. Raise the score, add an alias, and let the genuinely
ambiguous ones fail into review.

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
Given section 8.2's caveat, an uncapped loop against a stuck `Distributed` job is precisely
how you turn a two-minute notebook cell into a hung kernel. Bound every poll.

💡 `[GOOD TO KNOW]` — **the result is two levels deep.** `job.result` (= `job.get_result()`)
returns `{"items": [...]}` where each `items[]` entry is one **file block**, and the
real detections live in that block's **`annotations`** list. Each annotation carries
**`entities`** (the matched assets) and a **`region`** whose box is a **`vertices`**
polygon (normalized `{x, y}` points), *not* `xMin/xMax`. So you walk
**`items[] → annotations[] → entities[]`** and build the bounding box from the `min`/`max`
of the vertices — exactly what the Function handler in section 8.5 does. Reading
`entities`/`region` off the top-level `items[]` entry (the obvious first guess) finds
nothing and silently creates **zero** edges.

✅ `[VERIFY]` notebook results in CDF: after creating the edges, open the P&ID file in
Fusion — you should see clickable bounding boxes on the rendered PDF over the tags
`21-VG-2001`, `21-PA-2001A`, `21-PA-2001B`, `21-HA-2001`, `21-XV-2001` (or a subset,
if OCR didn't find every tag — see section 8.6).

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

Edge TYPE is cdf_cdm:diagrams.AssetLink. CogniteDiagramAnnotation is the edge VIEW only
(used in sources=). Using the view name as type= returns HTTP 400.
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


from cognite.client.data_classes.contextualization import DiagramDetectConfig


def _load_tag_aliases(client, raw_db: str) -> dict[str, list[str]]:
    """The nearest thing CDF offers to a custom symbol library.

    You cannot deploy a symbol recogniser into diagram detect -- there is no such API.
    What you CAN do is tell it which strings mean the same thing, and keep that list as
    data rather than in code, so a drawing-office engineer can add "the 2011 sheets
    abbreviate PUMP as P" without a deploy.

    Returns {canonical: [alias, ...]} for DiagramDetectConfig(substitutions=...).
    """
    try:
        rows = client.raw.rows.list(
            db_name=raw_db, table_name="rwt_Training_TRN_TagAliases", limit=-1)
    except Exception:  # noqa: BLE001 - an absent table means "no aliases", not a failure
        return {}
    aliases: dict[str, list[str]] = {}
    for row in rows:
        c = row.columns or {}
        canonical = (c.get("canonical") or "").strip()
        raw_aliases = (c.get("aliases") or "").strip()
        if not canonical or not raw_aliases:
            continue
        # pipe-separated, because a comma would fight the CSV
        aliases[canonical] = [a.strip() for a in raw_aliases.split("|") if a.strip()]
    return aliases


def handle(client, data=None, secrets=None, function_call_info=None) -> dict:
    participant = os.environ["PARTICIPANT"]
    space = os.environ["INSTANCE_SPACE"]
    raw_db = os.environ.get("RAW_DB", f"rwd_{participant}_Training_TRN")
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

    # The alias library, and the tuning that goes with it. Every one of these is a
    # precision/recall decision -- see Chapter 08 section 8.3b.
    substitutions = _load_tag_aliases(client, raw_db)
    config = DiagramDetectConfig(
        substitutions=substitutions or None,
        # Vector PDFs carry real text. Read it: OCR is the fallback, not the default.
        read_embedded_text=True,
        # RAW strips leading zeros from tag numbers; so does this, on the other side.
        remove_leading_zeros=True,
        case_sensitive=False,
        # Below this, a "match" is a guess. Raise it to cut false positives, lower it
        # to catch more and accept review cost.
        min_fuzzy_score=0.7,
    )

    job = client.diagrams.detect(
        entities=entities, search_field="name",
        file_instance_ids=[NodeId(space, file_xid)],
        partial_match=True, min_tokens=2,
        configuration=config,
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
                    # Edge TYPE in cdf_cdm (not the view/container externalId).
                    # File→asset diagram hits use diagrams.AssetLink; CogniteDiagramAnnotation is the view.
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

🔀 `[PR]` Per section 8.2, when you wire this into your workflow DAG in
[Chapter 12](12-workflows.md) it gets `onFailure: skipTask` and `retries: 1` — never
`abortWorkflow`, and never a high retry count. Here, call it manually exactly once.

---

## 8.7 [ACTION] Read the edges back — from both ends

Section 8.5 claimed edges "give you both directions". Prove it, because this is the payoff for
the `diagramAnnotations` connection you declared on your `Asset` view in
[Chapter 03](03-data-modeling.md) section 3.12.

🟢 `[ACTION]` First, the edges themselves — the raw instances your Function wrote:

```python
from cognite.client.data_classes.data_modeling import ViewId
from cognite.client.data_classes import filters as flt

ANNOTATION = ViewId("cdf_cdm", "CogniteDiagramAnnotation", "v1")

edges = client.data_modeling.instances.list(
    instance_type="edge", sources=ANNOTATION,
    space=space, limit=-1)          # `space` from the notebook setup, section 8.4

for e in edges:
    p = e.properties[ANNOTATION]
    print(f"{e.start_node.external_id:<28} -> {e.end_node.external_id:<14} "
          f"'{p.get('startNodeText')}' conf={p.get('confidence')}")
```

✅ `[VERIFY]` One line per annotation your Function created. `start_node` is the P&ID
file, `end_node` is the asset — which is exactly why the connection you declared uses
`direction: inwards`: the asset sits at the **end** of the edge.

⚠️ `[COMMON MISTAKE]` Omitting `instance_type="edge"`. The default is `"node"`, and the
error names neither the parameter nor the view:

```
CogniteAPIError: A property from a node or edge only container was referenced
in a context where it is not allowed. | code: 400
```

Translated: you asked for **nodes** while selecting properties from
`CogniteDiagramAnnotation`, whose container is `usedFor: edge`. Annotations are edges, so
you must ask for edges. Whenever you meet that sentence, check `instance_type` first.

🟢 `[ACTION]` Now traverse from the asset back to the files that mention it:

```python
from cognite.client.data_classes.data_modeling.query import (
    Query, Select, SourceSelector, NodeResultSetExpression, EdgeResultSetExpression)

FILE = ViewId("cdf_cdm", "CogniteFile", "v1")

q = Query(
    with_={
        "pump": NodeResultSetExpression(
            filter=flt.And(
                flt.SpaceFilter(INSTANCE_SPACE, "node"),
                flt.HasData(views=[ASSET]),
                flt.Equals(["node", "externalId"], "21-PA-2001A"),
            ),
            limit=1),
        "links": EdgeResultSetExpression(
            from_="pump", direction="inwards", max_distance=1, limit=100,
            filter=flt.Equals(["edge", "type"],
                              {"space": "cdf_cdm", "externalId": "diagrams.AssetLink"})),
        "diagrams": NodeResultSetExpression(from_="links", limit=100),
    },
    select={
        "links": Select([SourceSelector(ANNOTATION, ["startNodeText", "confidence"])]),
        "diagrams": Select([SourceSelector(FILE, ["name"])]),
    },
)
res = client.data_modeling.instances.query(q)
print("annotations:", len(res["links"]), "| diagrams:", len(res["diagrams"]))
for n in res["diagrams"]:
    print("  ", n.properties[FILE].get("name"))
```

✅ `[VERIFY]` At least one annotation and your P&ID PDF by name. If `annotations` is
non-zero but `diagrams` is empty, your edge is pointing the wrong way — re-read which
side your Function used as `start_node`.

💡 `[GOOD TO KNOW]` `direction="inwards"` on the **edge** step means "edges arriving at
`pump`". The third step then follows each edge to its *other* node. That is three
result-set expressions to express one English sentence: *the diagrams that mention this
pump*. Declaring the connection in Chapter 03 is what lets Fusion, Canvas and an Atlas AI
agent ask the same question without writing any of this — see
[Chapter 13](13-querying-the-graph.md) section 13.5 for why "the query works anyway" is not an
argument against declaring it.

✅ `[VERIFY]` In Fusion, open your `MaintenanceInsight` model → `Asset` → `21-PA-2001A`.
The `diagramAnnotations` property now lists the annotations it showed as empty at the end
of Chapter 03.

---

## Gate

**Do not proceed to Chapter 09 until:**

- You have called `DetectDiagramTags` **exactly once** and it returned successfully
- At least one `CogniteDiagramAnnotation` edge exists and renders in Fusion
- section 8.7 ran: you listed the edges with `instance_type="edge"` and traversed from the
  pump back to the P&ID, and `diagramAnnotations` on your `Asset` view is no longer
  empty in Fusion
- You can state, from memory, why there's no cancel API workaround for a stuck
  `Distributed` job, and why that means "stop submitting, don't retry-loop"
- 📓 You have added your two or three lines for this chapter to `participants/<YOURNAME>/NOTES.md` — **now**, not tonight

→ [Chapter 09 — 3D](09-3d.md)
