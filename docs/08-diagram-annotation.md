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
| `substitutions` | which **single characters** the OCR confuses — `0` for `O`, `1` for `I`. **Keys must be one character; the API rejects longer ones** |
| `min_fuzzy_score` / `customize_fuzziness` | how close is close enough. The precision/recall dial |
| `read_embedded_text` | vector PDFs carry real text. Read it; OCR is the fallback, not the default |
| `remove_leading_zeros` | `21-PA-2001` vs `21-PA-02001`. The same class of bug [Chapter 05](05-transformations.md) fixes with `lpad`, on the other side |
| `case_sensitive`, `partial_match`, `min_tokens` | matching strictness |
| `pattern_mode` | detect tags by *pattern* instead of a fixed entity list |

### The character-substitution library belongs in RAW

⚠️ `[COMMON MISTAKE]` Reading `substitutions` as a word-alias feature — *"tell it that PMP
means PUMP"*. It is not, and the API says so:

```
configuration.substitutions.PUMP.key: Length must be 1. | code: 400
```

**Keys must be a single character.** This is an *OCR confusion* table: which characters
the reader mistakes for which. On a scanned P&ID that is where most misses come from —
`21-PA-2001A` read as `21-PA-2OO1A`, zero for the letter O.

💡 `[GOOD TO KNOW]` Word-level aliases are a different mechanism entirely: you pass
**several strings per entity** in `name`. Your handler already does it —
`"name": [name, a.external_id]` gives every asset two spellings to match on. If you need
`PMP` to find `PUMP`, add it there, not here.

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/03_data/raw/rwt_Training_TRN_TagAliases.Table.yaml`

```yaml
dbName: rwd_<YOURNAME>_Training_TRN
tableName: rwt_Training_TRN_TagAliases
```

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/03_data/raw/rwt_Training_TRN_TagAliases.Table.csv`

```text
key,character,alternatives,addedBy,reason
sub-001,0,O|o,course,OCR reads the digit zero as a letter O on scanned sheets; 21-PA-2OO1A is the classic miss.
sub-002,1,I|l,course,Digit one versus capital I and lowercase L in the drawing-office font.
sub-003,5,S,course,Digit five versus capital S in stencilled tag numbers.
sub-004,8,B,course,Digit eight versus capital B when the scan is poor.
```

Alternatives are pipe-separated because a comma would fight the CSV. `addedBy` and
`reason` are here for the same reason as in [Chapter 07](07-entity-matching.md) section
7.2: in a year, *"who decided 5 and S are interchangeable, and is that still true for this
scanner"* is the only question that matters.

⚠️ `[COMMON MISTAKE]` Calling `.strip()` on what you read back from that table. **RAW
types its values** — a column containing `0`, `1`, `5`, `8` comes back as `int`, not
`str`, and the Function dies with `AttributeError: 'int' object has no attribute 'strip'`
*inside* the detect job, where you will not see it until you read the logs. Coerce with
`str(...)` first. This is the same family as the leading-zero trap in
[Chapter 05](05-transformations.md): **never assume a RAW column is text.**

🚧 `[LIMITS]` Every substitution you add widens the match space for **every** tag, so each
one buys recall and sells precision globally. Four well-chosen character pairs are worth
more than twenty speculative ones — and the handler skips any row whose key is not exactly
one character rather than letting a bad row fail the whole detect job.

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

### What makes two detections the same detection

An edge needs an external ID, and the obvious choice is a counter over the results —
`anno_<file>_<tag>_0`, `_1`, `_2`. It is wrong, and it fails in the direction that looks
fine.

✅ `[VERIFY]` Run the Function twice against the same unchanged P&ID and count the edges.
Measured here, with the counter version:

```
edges before: 9
call: Completed
edges after : 17
```

Every one of those 17 is a "correct" annotation. None is a duplicate *by external ID*.
The detector simply returned its results in a different order, so every ID shifted, and
`apply` created a second full set alongside the first. Nothing errors. Fusion shows the
drawing twice-annotated, and the count grows every night.

⚠️ `[COMMON MISTAKE]` Keying anything on result *order*. An external ID has to be derived
from what the thing **is**, never from where it happened to appear in a list. This is the
same rule as [Chapter 03](03-data-modeling.md)'s `(space, externalId)` identity: identity
is a statement about the world, not about your loop.

So what *is* a detection? A tag, at a place, on a page, of a drawing — and that is exactly
what `_annotation_id` hashes. Three decisions in four lines:

- **The geometry is in the key.** The same tag can legitimately appear twice on one
  drawing — a pump on the process line and again in the equipment list. Those are two
  annotations, and a key without coordinates would collapse them into one.
- **The coordinates are rounded first.** The service is free to return `0.1000000001`
  where it returned `0.1` last night. An identity that changes on a floating-point wobble
  is not an identity. Four decimal places on a normalised box is finer than any real
  detection moves and coarser than any noise.
- **The tag stays readable in the ID.** A pure hash is correct and useless the moment you
  are staring at a list of them trying to work out which drawing is wrong.

### And what a re-run must take away

Stable IDs stop the pile-up. They do not handle the opposite case: a detection that was
there last week and is **not** there now, because somebody uploaded a new revision of the
drawing or you tightened `min_fuzzy_score`.

The Function reconciles: anything on this file that this run did not produce is deleted,
and counted as `annotations_removed`.

⚠️ `[COMMON MISTAKE]` Reconciling without checking `status`. `CogniteDiagramAnnotation`
carries one — `Suggested` is the detector's guess, anything else means a **person**
approved or rejected it. Delete those and you have thrown away human review work that
cannot be recovered, on a schedule, silently. The handler skips them and reports
`reviewed_annotations_kept`, and it is the same rule the contextualization spine applies
in [Chapter 17](17-cross-cutting-mastery.md) section 17.1c: *a person's decision outranks
the machine's, every time.*

---

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

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/04_compute/functions/fnc_<YOURNAME>_Training_DetectDiagramTags/handler.py`

```python
"""Detect tags on the Area 21 P&ID and create CogniteDiagramAnnotation edges.

diagrams.detect returns items[] (one block per file); each block's annotations[] holds
the detections. Each annotation carries entities[] (the matched assets) and a region
whose box is a vertices[] polygon (normalized 0-1), not xMin/xMax.

Edge TYPE is cdf_cdm:diagrams.AssetLink. CogniteDiagramAnnotation is the edge VIEW only
(used in sources=). Using the view name as type= returns HTTP 400.
"""

from __future__ import annotations

import hashlib
import os
import time

from cognite.client.data_classes.data_modeling import (
    DirectRelationReference,
    EdgeApply,
    EdgeId,
    NodeId,
    NodeOrEdgeData,
    ViewId,
)

EQUIPMENT_TAGS = ["21-VG-2001", "21-PA-2001A", "21-PA-2001B", "21-HA-2001", "21-XV-2001"]


def _bbox(region: dict):
    """(xMin, xMax, yMin, yMax) from a region's vertices polygon, or None.

    **None, not a default box.** This used to return a small rectangle at the origin
    when the API omitted vertices, and that was wrong twice over. A fabricated box is
    written to CDF as though it were measured, so Fusion draws a highlight over a part
    of the drawing where nothing was found; and annotation identity is derived from the
    geometry, so every placeless detection of the same tag collapses onto one node.

    Inventing data to keep a write path happy is the most expensive kind of convenience.
    A detection nobody can point at on the page is a *review item*, not an annotation.
    """
    verts = region.get("vertices") or []
    xs = [float(v["x"]) for v in verts if isinstance(v, dict) and "x" in v]
    ys = [float(v["y"]) for v in verts if isinstance(v, dict) and "y" in v]
    if xs and ys:
        return min(xs), max(xs), min(ys), max(ys)
    return None


from cognite.client.data_classes.contextualization import DiagramDetectConfig


def _load_tag_aliases(client, raw_db: str) -> dict[str, list[str]]:
    """Character substitutions for the OCR, from RAW.

    `substitutions` keys must be a SINGLE CHARACTER -- the API rejects anything longer
    with `configuration.substitutions.PUMP.key: Length must be 1`. This is not a
    word-alias feature. It tells the matcher which characters the OCR confuses, which on
    a scanned P&ID is where most misses come from: 21-PA-2001A read as 21-PA-2OO1A.

    Word-level aliases are a different mechanism -- you pass several strings per entity
    in `name`, which this handler already does.

    Returns {character: [alternative, ...]} for DiagramDetectConfig(substitutions=...).
    """
    try:
        rows = client.raw.rows.list(
            db_name=raw_db, table_name="rwt_Training_TRN_TagAliases", limit=-1)
    except Exception:  # noqa: BLE001 - an absent table means "no aliases", not a failure
        return {}
    aliases: dict[str, list[str]] = {}
    for row in rows:
        c = row.columns or {}
        # RAW TYPES its values: a column of 0, 1, 5, 8 comes back as int, not str, and
        # .strip() on an int raises AttributeError. Same family as the leading-zero trap
        # in Chapter 05 -- never assume a RAW column is text.
        character = str(c.get("character") if c.get("character") is not None else "").strip()
        alternatives = str(c.get("alternatives") or "").strip()
        # Skip anything the API would reject rather than failing the whole detect job.
        if len(character) != 1 or not alternatives:
            continue
        # pipe-separated, because a comma would fight the CSV
        aliases[character] = [a.strip() for a in alternatives.split("|") if a.strip()]
    return aliases


def _annotation_id(file_xid: str, asset_xid: str, page: int, bbox: tuple) -> str:
    """A stable external ID for one detection.

    The obvious key -- a counter over the results -- is the one that does not work, and
    it fails in the direction that looks fine: every re-run produces a *new* set of IDs,
    so the edges accumulate instead of updating. Measured here, one re-run took a P&ID
    from 9 annotation edges to 17, all of them "correct", none of them duplicates by
    external ID.

    What makes two detections the same detection is *where they are*: the same tag, at
    the same place, on the same page, of the same drawing. So that is the key. The
    coordinates are rounded before hashing because the service is free to return
    1.0000000001 where it returned 1.0 last night, and an identity that changes on a
    floating-point wobble is not an identity.
    """
    x_min, x_max, y_min, y_max = (round(float(v), 4) for v in bbox)
    fingerprint = f"{file_xid}|{asset_xid}|{page}|{x_min}|{x_max}|{y_min}|{y_max}"
    digest = hashlib.sha1(fingerprint.encode()).hexdigest()[:12]
    return f"anno_{file_xid}_{asset_xid}_{digest}"[:255]


def _record_for_review(client, space, sdm, version, file_xid, placeless, run_id):
    """Persist detections we could not place as ContextualizationSuggestion rows.

    The same spine Chapter 17 section 17.1c builds for entity matching. A detection the
    detector made but nobody can point at is exactly the middle band: not good enough to
    write, far too informative to drop. Dropping it is how a reviewer never learns that
    the P&ID they just approved had five tags the system saw and silently discarded.
    """
    if not placeless:
        return 0
    from cognite.client.data_classes.data_modeling import NodeApply, NodeOrEdgeData
    view = ViewId(sdm, "ContextualizationSuggestion", version)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    nodes = []
    for row in placeless:
        xid = f"sug_{row['source']}_{row['target']}_noplace"[:255]
        nodes.append(NodeApply(space=space, external_id=xid,
            sources=[NodeOrEdgeData(source=view, properties={
                "name": f"{row['target']} detected on {row['source']} with no coordinates",
                "runId": run_id,
                "sourceExternalId": row["source"],
                "targetExternalId": row["target"],
                "method": "diagram-detect",
                "confidence": row.get("confidence"),
                "decision": "needs-review",
                "decidedBy": "pipeline",
                "decidedTime": now,
                "evidenceText": (f"detected text {row['text']!r} on page {row['page']}, "
                                 "but the API returned no vertices -- it cannot be placed "
                                 "on the drawing, so it was not written as an annotation"),
                "evidencePage": row.get("page"),
            })]))
    try:
        client.data_modeling.instances.apply(nodes=nodes, auto_create_direct_relations=False)
    except Exception:  # noqa: BLE001 - the spine view may not be deployed yet
        return 0
    return len(nodes)


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
    placeless: list[dict] = []          # detected, but the API gave us no coordinates
    tags_found: list[str] = []
    idx = 0

    # items[] is one block PER FILE; the detections live in block["annotations"].
    for block in (result.get("items") if isinstance(result, dict) else []) or []:
        for ann in block.get("annotations") or []:
            region = ann.get("region") or {}
            page = int(region.get("page") or ann.get("page") or 1)
            text = ann.get("text") or ""
            confidence = float(ann.get("confidence") or 0.0)
            box = _bbox(region)

            seen: set[str] = set()  # the API can list the same entity twice
            for ent in ann.get("entities") or []:
                asset_xid = ent.get("externalId") if isinstance(ent, dict) else str(ent)
                if not asset_xid or asset_xid in seen or asset_xid not in asset_xids:
                    continue
                seen.add(asset_xid)

                # No geometry means we cannot say WHERE on the drawing this is, so it
                # cannot become an annotation -- an annotation without a location is a
                # claim a reviewer has no way to check. It becomes a review item instead.
                if box is None:
                    placeless.append({
                        "source": file_xid, "target": asset_xid,
                        "page": page, "text": text or asset_xid,
                        "confidence": confidence,
                    })
                    continue

                x_min, x_max, y_min, y_max = box
                edges.append(EdgeApply(
                    space=space,
                    external_id=_annotation_id(
                        file_xid, asset_xid, page, (x_min, x_max, y_min, y_max)),
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

    # ---- reconcile before writing -------------------------------------------------
    # Silence is not agreement. A detection this drawing carried last week and does not
    # carry today is a *change* -- somebody uploaded a new revision of the P&ID, or the
    # tuning changed -- and leaving the old edge in place means the graph asserts a tag
    # is on a drawing that no longer shows it.
    #
    # The one thing that must never be removed is an edge a person ruled on. A
    # CogniteDiagramAnnotation carries `status`; anything other than "Suggested" means a
    # human approved or rejected it, and that decision outranks the detector -- exactly
    # the rule the contextualization spine applies in Chapter 17 section 17.1c.
    produced = {e.external_id for e in edges}
    stale: list[EdgeId] = []
    reviewed_kept = 0
    try:
        existing = client.data_modeling.instances.list(
            instance_type="edge", sources=view, space=space, limit=-1)
    except Exception:  # noqa: BLE001 - nothing written yet is a valid first-run state
        existing = []
    for edge in existing:
        if edge.start_node.external_id != file_xid:
            continue                       # another drawing's annotations
        if edge.external_id in produced:
            continue
        status = (edge.properties.get(view) or {}).get("status")
        if status not in (None, "", "Suggested"):
            reviewed_kept += 1             # a person owns this one
            continue
        stale.append(EdgeId(space, edge.external_id))

    if edges:
        client.data_modeling.instances.apply(edges=edges)
    if stale:
        client.data_modeling.instances.delete(edges=stale)

    sdm = os.environ.get("SCHEMA_SPACE_SDM", "")
    version = os.environ.get("MODEL_VERSION", "v1.0.0")
    run_id = (data or {}).get("runId") or f"ctxrun-{int(time.time())}-diagramdetect"
    review_written = _record_for_review(
        client, space, sdm, version, file_xid, placeless, run_id)

    tags_missing = [t for t in EQUIPMENT_TAGS if t not in tags_found]
    return {
        "annotations_created": len(edges),
        "detections_without_geometry": len(placeless),
        "review_rows_written": review_written,
        "run_id": run_id,
        "annotations_removed": len(stale),
        "reviewed_annotations_kept": reviewed_kept,
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

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/04_compute/functions/DetectDiagramTags.Function.yaml`

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
- The acceptance contract passes for this capability: `uv run python tools/acceptance.py <YOURNAME> diagram-annotation` ([Chapter 17](17-cross-cutting-mastery.md) section 17.2c)
- 📓 You have added your two or three lines for this chapter to `participants/<YOURNAME>/NOTES.md` — **now**, not tonight

→ [Chapter 09 — 3D](09-3d.md)
