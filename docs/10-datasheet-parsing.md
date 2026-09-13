# Chapter 10 — Datasheet Parsing

**Goal:** populate the Equipment Health Profile using two techniques — deterministic
regex, and the agentic Cognite Document Parser API — and understand why
**description engineering on your view is the real lever** for the second one.

Both techniques converge on the exact same target: upserting node `ehp_21-PA-2001A`
(literal externalId, isolated by your own space — never `YOURNAME`-scoped, per section 1.2)
into `EquipmentHealthProfile`. The sequence is always: **model exists → file
uploaded & matched → parse → verify the instance in the view.** You've already done
the first two steps (Chapters 03, 04, 07) — this chapter is steps 3 and 4, twice.

---

## 10.1 [INFO] About the Document Parser API

The Document Parser API you're about to call is a Cognite **public-preview /
Early-Adopter** capability. Its endpoints are **internal** — there is no public typed
SDK method, so you call them with raw `client.post` (the same pattern as
[Chapter 09](09-3d.md)'s 3D calls). Because the feature is in preview, treat the
wire-level contract in this chapter as accurate as of the validation date at the top of
the course, and check the official Cognite docs before you rely on it in production.

📚 `[DOCS]` conceptual overview (public preview):
https://docs.cognite.com/cdf/integration/guides/contextualization/parse_documents/
— this page describes the *product concept* (confidence scoring, view-as-schema); the
wire-level endpoints you call below are documented inline in this chapter.

---

## 10.2 [INFO] Technique 1 — Deterministic regex (baseline)

Extract text with `pypdf`, match a `PATTERNS` dict of regexes, cast to the right
type, and track what you couldn't find.

**Strengths:** zero marginal cost, fully auditable — you can point at the exact regex
that produced (or failed to produce) each value, works entirely offline.
**Failure mode:** brittle to layout/format drift — a datasheet from a different
vendor template, a reflowed PDF, or OCR'd (rather than text) PDF breaks every pattern
at once, silently, with no severity signal beyond "missing."

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/functions/fnc_<YOURNAME>_Training_ParseDatasheet_Regex/handler.py`
*(build this one in the notebook and read it here — the deployed Function you'll ship
in section 10.5 is the Technique 2 version; keep this one as your own local comparison)*:

```python
"""Parse the pump datasheet PDF via deterministic regex (Technique 1 baseline)."""

from __future__ import annotations

import io
import os
import re
from datetime import datetime, timezone

from cognite.client.data_classes.data_modeling import (
    DirectRelationReference, NodeApply, NodeId, NodeOrEdgeData, ViewId,
)
from pypdf import PdfReader

PATTERNS = {
    "ratedFlowM3h": r"Rated Flow:\s*([\d.]+)\s*m3/h",
    "ratedHeadM": r"Rated Head:\s*([\d.]+)\s*m",
    "ratedPowerKw": r"Rated Power:\s*([\d.]+)\s*kW",
    "designPressureBarg": r"Design Pressure:\s*([\d.]+)\s*barg",
    "designTemperatureC": r"Design Temperature:\s*([\d.]+)\s*degC",
    "dryWeightKg": r"Dry Weight:\s*([\d.]+)\s*kg",
    "casingMaterial": r"Casing Material:\s*(.+)",
    "sealType": r"Seal Type:\s*(.+)",
    "manufacturer": r"Manufacturer:\s*(.+)",
    "serialNumber": r"Serial Number:\s*(.+)",
}

NUMERIC_KEYS = {"ratedFlowM3h", "ratedHeadM", "ratedPowerKw", "designPressureBarg", "designTemperatureC", "dryWeightKg"}


def handle(client, data=None, secrets=None, function_call_info=None) -> dict:
    participant = os.environ["PARTICIPANT"]
    space = os.environ["INSTANCE_SPACE"]
    schema_edm = os.environ["SCHEMA_SPACE_EDM"]
    schema_sdm = os.environ["SCHEMA_SPACE_SDM"]
    model_version = os.environ.get("MODEL_VERSION", "v1.0.0")
    file_xid = f"file_{participant}_TRN_DS_21_PA_2001A"

    content = client.files.download_bytes(instance_id=NodeId(space, file_xid))
    reader = PdfReader(io.BytesIO(content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    parsed: dict = {}
    missing: list[str] = []
    for key, pattern in PATTERNS.items():
        m = re.search(pattern, text)
        if not m:
            missing.append(key)
            continue
        raw = m.group(1).strip()
        parsed[key] = float(raw) if key in NUMERIC_KEYS else raw

    v_wo = ViewId(schema_edm, "WorkOrder", model_version)
    work_orders = client.data_modeling.instances.list(instance_type="node", sources=[v_wo], space=space, limit=-1)
    open_count = 0
    for wo in work_orders:
        props = wo.properties.get(v_wo, {})
        status = (props.get("status") or "").upper()
        asset_ids = [r.external_id if hasattr(r, "external_id") else r.get("externalId") for r in (props.get("assets") or [])]
        if "21-PA-2001A" in asset_ids and status != "CLOSED":
            open_count += 1

    v_ehp = ViewId(schema_sdm, "EquipmentHealthProfile", model_version)
    ehp_props = {
        # hasData: this view implements CogniteDescribable, so a node with no
        # name is invisible through the view even though the specs are stored.
        # Chapter 03 section 3.8b.
        "name": "Health profile — 21-PA-2001A",
        "description": "Parsed datasheet specs and open work-order rollup for export pump A.",
        "asset": DirectRelationReference(space, "21-PA-2001A"),
        "equipment": DirectRelationReference(space, "EQ-1002"),
        "datasheetFile": DirectRelationReference(space, file_xid),
        "openWorkOrderCount": open_count,
        # CDF timestamp props allow 1-3 fractional digits only -- never full microseconds.
        "lastParsedTime": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    }
    for key in ("ratedFlowM3h", "ratedHeadM", "ratedPowerKw", "designPressureBarg", "designTemperatureC", "dryWeightKg", "casingMaterial", "sealType"):
        if key in parsed:
            ehp_props[key] = parsed[key]

    client.data_modeling.instances.apply(nodes=[
        NodeApply(space=space, external_id="ehp_21-PA-2001A", sources=[NodeOrEdgeData(source=v_ehp, properties=ehp_props)])
    ])
    return {
        "parsed": {k: v for k, v in parsed.items() if k not in ("manufacturer", "serialNumber")},
        "missing_fields": [m for m in missing if m not in ("manufacturer", "serialNumber")],
        "openWorkOrderCount": open_count,
    }
```

### Line-by-line walkthrough — Technique 1 (regex)

| Code | What it does | Why it is written this way |
|---|---|---|
| `PATTERNS = {...}` | One regex per field, keyed by **the exact view property name** | Keying by property name means the parse result can be handed to `NodeApply` almost unchanged. Each pattern captures one group — the value — and hardcodes the unit (`m3/h`, `kW`) as an anchor so a number from a different row cannot match by accident |
| `NUMERIC_KEYS` | Which fields to cast to `float` | The view types these as numbers. Writing `"320"` where a float is expected is rejected — a set membership test is the cheapest way to know which is which |
| `download_bytes(instance_id=NodeId(space, file_xid))` | Fetches the PDF bytes | `instance_id=` targets the **DMS node**. Straight into memory — a Function's filesystem is ephemeral, so there is no reason to touch disk |
| `"\n".join(page.extract_text() or "" ...)` | Flattens every page to one string | The `or ""` matters: `extract_text()` returns `None` on an image-only page, and `None` would crash the join. This is also exactly where an OCR'd PDF fails — no text layer, so every pattern misses at once |
| `if not m: missing.append(key)` | Records misses instead of failing | A datasheet legitimately may not state every field. Distinguishing "absent" from "broken" is the whole reason `missing_fields` is returned |
| `v_wo = ViewId(schema_edm, "WorkOrder", model_version)` | Points at **your** view | Note it uses `schema_edm` from env, not a literal — the same code works for every participant |
| the `for wo in work_orders` loop | Counts open work orders on `21-PA-2001A` | **This is the point of the exercise.** No regex can find this in the PDF — it is a *relational* fact that exists only in the graph. Technique 2 cannot read it either |
| `r.external_id if hasattr(r, "external_id") else r.get("externalId")` | Handles both shapes of a direct relation | The SDK returns a typed object in some paths and a plain dict in others |
| `status != "CLOSED"` | Counts anything not closed as open | Deliberately permissive — an unexpected status counts as open. For a *health* metric, over-reporting risk is the safer error |
| `isoformat(timespec="milliseconds")` | Timestamp with exactly 3 fractional digits | See the `[LIMITS]` note directly below — this is a hard API constraint, not a style choice |
| `NodeApply(external_id="ehp_21-PA-2001A")` | Writes the health profile node | The externalId stays **literal**, not name-scoped — your space already isolates it (section 1.2) |
| `{k: v for k, v in parsed.items() if k not in ("manufacturer", "serialNumber")}` | Omits two fields from the return | They are parsed to prove the regex works, but they are not view properties, so they are not written or reported |

📚 `[DOCS]` [Data modeling](https://docs.cognite.com/cdf/dm/) ·
[Cognite Functions](https://docs.cognite.com/cdf/functions/)

🚧 `[LIMITS]` CDF `timestamp` properties accept at most **3 fractional digits**.
`datetime.now(timezone.utc).isoformat()` by default produces 6 (microseconds) and
will be **rejected**. Always call `isoformat(timespec="milliseconds")`.

---

## 10.3 [OPTIMIZE] Description engineering — the real lever for Technique 2

Before you touch the Document Parser API, understand this: `viewConfig` in the
`start` call (section 10.4) points at your `EquipmentHealthProfile` view — and
**the view's property names and descriptions become the literal extraction schema**
the model fills in. `userPrompt` only *steers* (tone, edge cases); the view *carries*
the schema. This is the single highest-leverage thing you control in this whole
technique.

Compare what you deployed in Chapter 03 against a description-engineered version:

| Property | Chapter 03 (works, but bare) | Description-engineered |
|---|---|---|
| `ratedFlowM3h` | *(no description)* | `"Rated volumetric flow rate at duty point, in cubic meters per hour (m3/h). Example: 320.0. Leave absent if the datasheet has no explicit 'Rated Flow' field — do not estimate from other fields."` |
| `casingMaterial` | *(no description)* | `"Pump casing material of construction as printed on the datasheet, e.g. 'Duplex Stainless Steel'. Do not abbreviate or normalize units/alloys not present in the source text."` |
| `sealType` | *(no description)* | `"Shaft seal type as printed, e.g. 'Mechanical Seal, API 682 Plan 32'. Empty if not stated."` |

🟢 `[ACTION]` Enrich your container with descriptions before running Technique 2.

📝 `[WRITE]` update `participants/<YOURNAME>/data_modeling/EquipmentHealthProfile.Container.yaml`
— add a `description:` to each spec property (`ratedFlowM3h`, `ratedHeadM`,
`ratedPowerKw`, `designPressureBarg`, `designTemperatureC`, `dryWeightKg`,
`casingMaterial`, `sealType`), following the pattern above: **state the unit,
state the exact source phrasing to look for, and explicitly forbid guessing when
absent.**

```yaml
  ratedFlowM3h:
    type: { type: float64, list: false }
    nullable: true
    description: >-
      Rated volumetric flow rate at duty point, in cubic meters per hour (m3/h).
      Read from the datasheet's "Rated Flow" field only. Leave absent if not
      explicitly printed — do not estimate or derive from other fields.
```

💡 `[GOOD TO KNOW]` — the pattern above ("state the exact field to look for," "leave
empty/absent if not present," "do not guess") mirrors production prompt-engineering
practice for document extraction: explicit target schema, explicit instruction not to
hallucinate, explicit empty-value convention for missing data. Whether that
instruction lives in a property description (this API) or a prompt string (a
general-purpose LLM call), the discipline is identical.

⚡ `[OPTIMIZE]` — write descriptions for **both humans and agents**. The same
description that helps a colleague understand your view in Fusion is exactly what
steers this extraction model. There is no separate "AI-facing" documentation layer to
maintain — one well-written description serves both audiences (section 3.7 already told you
this; here it's no longer abstract).

🟢 `[ACTION]` Redeploy the enriched container before continuing:

```bash
uv run cdf build --config-yaml training/config.<YOURNAME>-training.yaml
uv run cdf deploy --cdf-project <your-cdf-project> --include data_modeling
```

---

## 10.4 [WRITE] + [ACTION] Notebook: `04_parse_datasheet_ehp.ipynb`

📝 `[WRITE]` Recreate `docs/notebooks/04_parse_datasheet_ehp.ipynb`,
covering **both** techniques back to back so you can compare their output on the same
file. For Technique 2, cell order: auth → submit `start` → poll `byids` with a time
budget → inspect the rich job detail → `write` → verify the view node.

The API contract, exactly as you'll call it:

```python
# Raw client.post does NOT auto-prepend the project scope -- build the full path.
DOCPARSER = f"/api/v1/projects/{client.config.project}/context/documentparser"

# /jobs/start is single-job: a FLAT body, and it returns {jobId, status}
# (not {"items": [...]}). The batch endpoint is POST /jobs with an items[] array.
start_body = {
    "viewConfig": {"space": schema_sdm, "externalId": "EquipmentHealthProfile", "version": "v1.0.0"},
    "files": [{"fileInstanceId": {"space": space, "externalId": file_xid}}],
    "node": {"space": space, "externalId": "ehp_21-PA-2001A"},
    "useVision": True,
    "userPrompt": "Extract pump datasheet specifications per the target view's property descriptions. If a value is absent from the document, leave it empty -- do not guess.",
}
job_id = client.post(f"{DOCPARSER}/jobs/start", json=start_body).json()["jobId"]
```

⚠️ `[COMMON MISTAKE]` — **raw `client.post` needs the full project-scoped path.** Unlike
the typed SDK (`instances.retrieve`/`apply`), `client.post` / `client.get` do **not**
prepend `/api/v1/projects/{project}` for you. The doc-parser endpoints are INTERNAL with
no typed SDK, so you build the path yourself (as `DOCPARSER` does above). The bare
`/context/documentparser/...` returns **404** — the project scope is missing — which is
exactly why [Chapter 09](09-3d.md)'s `Load3DRevision` uses the full
`/api/v1/projects/{project}/...` prefix for its raw 3D calls.

Poll — **always via `byids`, never the single-job `GET`:**

```python
import time
deadline = time.time() + 8 * 60
status = "Queued"
while status in ("Queued", "Running") and time.time() < deadline:
    time.sleep(15)
    detail = client.post(f"{DOCPARSER}/jobs/byids", json={"items": [{"jobId": job_id}]}).json()["items"][0]
    status = detail["status"]["job"] if isinstance(detail.get("status"), dict) else detail.get("status")
    print("status:", status)
```

Inspect the rich detail before writing — this is the notebook's whole value-add over
just calling the Function blind. **`scores` and `rawResponses` live under
`detail["result"]`**; `view`/`validation` status are under `detail["status"]`:

```python
result = detail.get("result") or {}
print("view status:", detail["status"].get("view"))
print("validation:", detail["status"].get("validation"))
print("scores:", result.get("scores"))
for prop, answer in (result.get("rawResponses") or {}).items():
    print(f"  {prop}: value={answer.get('value')!r} page={answer.get('pageNum')} spatialData={answer.get('spatialData')}")
```

Then persist the result. **`jobs/write` is an internal endpoint with an undocumented
request contract** — treat it as best-effort and never depend on it. You already hold
every extracted value in `result["rawResponses"]`, so write them into the node yourself
with the typed SDK (idempotent; the same `instances.apply` the Function uses):

```python
from cognite.client.data_classes.data_modeling import NodeApply, NodeOrEdgeData

try:
    client.post(f"{DOCPARSER}/jobs/write", json={"items": [{"jobId": job_id}]})
    print("jobs/write ok")
except Exception as exc:
    print(f"jobs/write failed ({exc}) -- writing extracted fields via instances.apply")

FLOAT_FIELDS = ["ratedFlowM3h", "ratedHeadM", "ratedPowerKw",
                "designPressureBarg", "designTemperatureC", "dryWeightKg"]
TEXT_FIELDS = ["casingMaterial", "sealType"]
raw = result.get("rawResponses") or {}
props = {}
for f in FLOAT_FIELDS:
    v = (raw.get(f) or {}).get("value")
    if v not in (None, ""):
        props[f] = float(str(v).split()[0])   # tolerate "320 m3/h"
for f in TEXT_FIELDS:
    v = (raw.get(f) or {}).get("value")
    if v not in (None, ""):
        props[f] = str(v)

props["name"] = "Health profile — 21-PA-2001A"          # required by hasData (section 3.8b)
props["description"] = "Parsed datasheet specs and open work-order rollup for export pump A."

# The three direct relations are the POINT of this view -- without them the profile
# is a bag of numbers no query can reach from the asset. Chapter 03 section 3.12 declares
# `source:` on each of them, and Chapter 13 section 13.5 walks `asset` backwards. Omit them
# and that traversal returns 0 rows.
props["asset"] = DirectRelationReference(space, "21-PA-2001A")
props["equipment"] = DirectRelationReference(space, "EQ-1002")
props["datasheetFile"] = DirectRelationReference(space, file_xid)

# Nothing in CDF derives "count of open work orders" for you -- compute it (Ch 03 section 3.11).
v_wo = ViewId(schema_edm, "WorkOrder", "v1.0.0")
open_count = 0
for wo in client.data_modeling.instances.list(instance_type="node", sources=[v_wo],
                                              space=space, limit=-1):
    wp = wo.properties.get(v_wo, {})
    ids = [r.external_id if hasattr(r, "external_id") else r.get("externalId")
           for r in (wp.get("assets") or [])]
    if "21-PA-2001A" in ids and str(wp.get("status") or "").upper() != "CLOSED":
        open_count += 1
props["openWorkOrderCount"] = open_count
# CDF timestamp props allow 1-3 fractional digits only, never full microseconds.
props["lastParsedTime"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

v_ehp = ViewId(schema_sdm, "EquipmentHealthProfile", "v1.0.0")
client.data_modeling.instances.apply(nodes=[NodeApply(
    space=space, external_id="ehp_21-PA-2001A",
    sources=[NodeOrEdgeData(source=v_ehp, properties=props)],
)], auto_create_direct_relations=False)   # fail loudly rather than invent phantom nodes
print("wrote:", sorted(props))
print("open work orders on the pump:", open_count)
```

⚠️ `[COMMON MISTAKE]` Writing only the parsed specs and stopping. The node then exists,
the view even returns it (because `name` satisfies `hasData`), and everything *looks*
fine — but `asset`, `equipment` and `datasheetFile` are `None`, so the profile is
unreachable from the pump. [Chapter 13](13-querying-the-graph.md) section 13.5 walks
`EquipmentHealthProfile.asset` backwards and returns **0 rows**; the `healthProfile`
reverse direct relation you declared in [Chapter 03](03-data-modeling.md) section 3.12 never
resolves. A health profile that no asset can reach is not a health profile.

✅ `[VERIFY]` Prove the relations landed, rather than trusting the write:

```python
ehp = client.data_modeling.instances.retrieve(
    nodes=(space, "ehp_21-PA-2001A"), sources=v_ehp).nodes[0]
p = ehp.properties[v_ehp]
for key in ("asset", "equipment", "datasheetFile"):
    assert p.get(key), f"{key} is empty -- the profile is unreachable from the graph"
    print(f"  {key:<14} -> {p[key]}")
print("  openWorkOrderCount:", p.get("openWorkOrderCount"))
```

🚧 `[LIMITS]` **What `jobs/write` actually does is project-dependent, and it is not a
platform outage.** Observed on a live project with a fresh `Completed` job:

```
items[0].data: Missing data for required field | code: 400
```

The endpoint wants a `data` payload whose shape is not published — it is internal to the
preview. On other projects the same call has returned `500`. Either way the conclusion is
the same, and it is the one worth learning: **an undocumented endpoint is not a
dependency.** The fallback above reaches the identical end state deterministically, using
only the typed SDK and values you already have in hand.

⚠️ `[COMMON MISTAKE]` Polling the single `GET /context/documentparser/{jobId}` — it
is **unreliable / 404s in practice**. Always use `POST /jobs/byids`. Also: forgetting
`useVision: true` — the non-vision path misses fields on this datasheet's layout.

✅ `[VERIFY]` notebook results in CDF:

```python
v_ehp = ViewId(schema_sdm, "EquipmentHealthProfile", "v1.0.0")
node = client.data_modeling.instances.retrieve_nodes(nodes=[(space, "ehp_21-PA-2001A")], sources=[v_ehp])[0]
print(node.properties.get(v_ehp))
```

Compare this against Technique 1's `parsed` output from section 10.2 — on this clean,
text-based training PDF both techniques should agree closely. Note where they don't,
and why (section 10.6).

---

## 10.5 [WRITE] The Function: `ParseDatasheet` (Technique 1, deployed)

⚠️ `[COMMON MISTAKE]` Assuming the newer technique is the one to deploy. **This Function
ships Technique 1 — deterministic regex — and that is a deliberate choice, not an
oversight.** You met the Document Parser API in the notebook above, and you saw what
happened when the notebook tried to persist through it:

```
jobs/write failed (items[0].data: Missing data for required field. | code: 400)
```

The parser reads the document well. Its **write** endpoint is preview, its payload shape
is unpublished, and it returns 400 on one project and 500 on another. So the notebook
uses it to *read* and falls back to the typed SDK to *write* — and the Function, which
runs unattended in a workflow with nobody watching, uses the technique that cannot
surprise it.

💡 `[GOOD TO KNOW]` This is the judgement the whole chapter is for. Technique 2 scales
past one hand-tuned regex per vendor template and is the right answer for fifty
templates. Technique 1 is the right answer for *this* pipeline today, because an
unattended job's first requirement is that it is predictable. **Pick the technique that
matches the blast radius, not the one that is newest** — and write down why, as this
section does, so the next person can re-decide when the preview endpoint stabilises.

### What changes versus Technique 1 — and what doesn't

| | Technique 1 (regex) | Technique 2 (Document Parser) |
|---|---|---|
| How specs are found | Your `PATTERNS` dict | The API reads the PDF **and its own view property descriptions** |
| Where the instructions live | In the Python | In the **view's property descriptions** (section 10.3) |
| New vendor template | Rewrite every regex | Usually just works |
| Cost / latency | Zero, instant | Paid, minutes |
| Auditability | Perfect — point at the regex | A completeness score |
| **Open work-order count** | **Computed in Python** | **Still computed in Python** |

That last row is the lesson. The parser reads the *document*; it cannot see the *graph*.
`openWorkOrderCount` is a relational fact, so **both** techniques compute it the same way,
with the same loop. Swapping extraction engines changes how you read a page — it does not
remove the need to know your own data model.

### The design idea: instructions live in the data model, not the code

`USER_PROMPT` is deliberately thin. It does not list fields or describe formats — it says
*"per the target view's property descriptions"* and *"do not guess."* The real prompt is
`viewConfig`, pointing at your `EquipmentHealthProfile`, whose property descriptions
you wrote in section 10.3.

Change what gets extracted by editing a **description in the data model**, not by editing and
redeploying Python. That is what makes this genuinely agentic rather than a fancier regex.

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/functions/fnc_<YOURNAME>_Training_ParseDatasheet/handler.py`

```python
"""Parse the pump datasheet PDF into EquipmentHealthProfile."""

from __future__ import annotations

import io
import os
import re
from datetime import datetime, timezone

from cognite.client.data_classes.data_modeling import (
    DirectRelationReference,
    NodeApply,
    NodeId,
    NodeOrEdgeData,
    ViewId,
)
from pypdf import PdfReader

PATTERNS = {
    "ratedFlowM3h": r"Rated Flow:\s*([\d.]+)\s*m3/h",
    "ratedHeadM": r"Rated Head:\s*([\d.]+)\s*m",
    "ratedPowerKw": r"Rated Power:\s*([\d.]+)\s*kW",
    "designPressureBarg": r"Design Pressure:\s*([\d.]+)\s*barg",
    "designTemperatureC": r"Design Temperature:\s*([\d.]+)\s*degC",
    "dryWeightKg": r"Dry Weight:\s*([\d.]+)\s*kg",
    "casingMaterial": r"Casing Material:\s*(.+)",
    "sealType": r"Seal Type:\s*(.+)",
    "manufacturer": r"Manufacturer:\s*(.+)",
    "serialNumber": r"Serial Number:\s*(.+)",
}


def handle(client, data=None, secrets=None, function_call_info=None) -> dict:
    participant = os.environ["PARTICIPANT"]
    space = os.environ["INSTANCE_SPACE"]
    schema_edm = os.environ["SCHEMA_SPACE_EDM"]
    schema_sdm = os.environ["SCHEMA_SPACE_SDM"]
    model_version = os.environ.get("MODEL_VERSION", "v1.0.0")
    file_xid = f"file_{participant}_TRN_DS_21_PA_2001A"

    try:
        content = client.files.download_bytes(instance_id=NodeId(space, file_xid))
    except Exception:
        content = client.files.download_bytes(external_id=file_xid)

    reader = PdfReader(io.BytesIO(content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    parsed: dict = {}
    missing: list[str] = []
    for key, pattern in PATTERNS.items():
        m = re.search(pattern, text)
        if not m:
            missing.append(key)
            continue
        raw = m.group(1).strip()
        if key in {
            "ratedFlowM3h",
            "ratedHeadM",
            "ratedPowerKw",
            "designPressureBarg",
            "designTemperatureC",
            "dryWeightKg",
        }:
            parsed[key] = float(raw)
        else:
            parsed[key] = raw

    v_wo = ViewId(schema_edm, "WorkOrder", model_version)
    work_orders = client.data_modeling.instances.list(
        instance_type="node",
        sources=[v_wo],
        space=space,
        limit=-1,
    )
    open_count = 0
    for wo in work_orders:
        props = wo.properties.get(v_wo, {})
        status = (props.get("status") or "").upper()
        assets = props.get("assets") or []
        asset_ids = []
        for rel in assets:
            if hasattr(rel, "external_id"):
                asset_ids.append(rel.external_id)
            elif isinstance(rel, dict):
                asset_ids.append(rel.get("externalId"))
        if "21-PA-2001A" in asset_ids and status != "CLOSED":
            open_count += 1

    v_ehp = ViewId(schema_sdm, "EquipmentHealthProfile", model_version)
    v_eq = ViewId("cdf_cdm", "CogniteEquipment", "v1")
    ehp_props = {
        # EquipmentHealthProfile implements CogniteDescribable, so the view
        # references TWO containers. The implicit hasData filter requires data in
        # BOTH: without name/description here the node exists in the registry but
        # the view returns nothing. See Chapter 03 section 3.8b.
        "name": "Health profile — 21-PA-2001A",
        "description": "Parsed datasheet specs and open work-order rollup for export pump A.",
        "asset": DirectRelationReference(space, "21-PA-2001A"),
        "equipment": DirectRelationReference(space, "EQ-1002"),
        "datasheetFile": DirectRelationReference(space, file_xid),
        "openWorkOrderCount": open_count,
        # CDF timestamp props allow 1–3 fractional digits only (not full microseconds).
        "lastParsedTime": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    }
    for key in (
        "ratedFlowM3h",
        "ratedHeadM",
        "ratedPowerKw",
        "designPressureBarg",
        "designTemperatureC",
        "dryWeightKg",
        "casingMaterial",
        "sealType",
    ):
        if key in parsed:
            ehp_props[key] = parsed[key]

    applies = [
        NodeApply(
            space=space,
            external_id="ehp_21-PA-2001A",
            sources=[NodeOrEdgeData(source=v_ehp, properties=ehp_props)],
        )
    ]
    eq_props = {}
    if "manufacturer" in parsed:
        eq_props["manufacturer"] = parsed["manufacturer"]
    if "serialNumber" in parsed:
        eq_props["serialNumber"] = parsed["serialNumber"]
    if eq_props:
        applies.append(
            NodeApply(
                space=space,
                external_id="EQ-1002",
                sources=[NodeOrEdgeData(source=v_eq, properties=eq_props)],
            )
        )

    client.data_modeling.instances.apply(nodes=applies)

    return {
        "parsed": {k: v for k, v in parsed.items() if k not in ("manufacturer", "serialNumber")},
        "missing_fields": [m for m in missing if m not in ("manufacturer", "serialNumber")],
        "openWorkOrderCount": open_count,
    }
```

### Line-by-line walkthrough — Technique 2 (Document Parser)

| Code | What it does | Why it is written this way |
|---|---|---|
| `POLL_BUDGET_SECONDS = 8 * 60` | 8-minute ceiling | Named constants, because these are the two numbers you will actually want to tune |
| `USER_PROMPT` | Deliberately generic instruction | Defers to the view's property descriptions and forbids guessing. See the design note above |
| `"do not guess or estimate"` | Explicit anti-hallucination instruction | An empty field is recoverable; a plausible **invented** rated flow is not. For engineering specs, a gap beats a guess |
| `FLOAT_FIELDS` / `TEXT_FIELDS` | Destination types, declared once | The parser returns everything as strings; these lists decide what gets cast |
| `float(str(value).split()[0])` | Takes the number off `"320 m3/h"` | The parser often returns the value **with its unit**. `.split()[0]` keeps the number. Wrapped in `try/except` so a genuinely unparseable answer is skipped, not fatal |
| `DOCPARSER = f"/api/v1/projects/{client.config.project}/..."` | Full path, built by hand | Raw `client.post` does **not** auto-prepend the project scope — same reason as Chapter 09 |
| `/jobs/start` with a **flat** body | Starts one job | The batch endpoint is `POST /jobs` with an `items[]` array. Mixing the two up is the usual first error here |
| `viewConfig` | Points the parser at your EHP view | **This is the actual prompt.** The parser reads your property descriptions to know what to look for |
| `"node": {... "ehp_21-PA-2001A"}` | Tells the parser its destination node | Lets the (internal) `jobs/write` endpoint know where results would go |
| `useVision: True` | Lets the model look at the page image | Datasheets are tables. Layout carries meaning that flattened text loses — this is the main advantage over `pypdf` |
| `while status in ("Queued", "Running")` | Polls to the deadline | Same bounded-wait discipline as Chapters 07 and 09 |
| `detail["status"]["job"] if isinstance(...) else ...` | Handles both response shapes | Status has arrived both as a nested object and as a bare string |
| `return {... "resume": status in ("Queued", "Running")}` | Times out cleanly | `resume: true` means "not finished, try later"; anything else means it genuinely failed |
| `try: client.post(f"{DOCPARSER}/jobs/write" ...)` | Best-effort call to an internal endpoint | `jobs/write` is public-preview and **may return 500**. It is attempted so this self-heals if the platform is fixed, but nothing depends on it — the values are already in hand |
| `write_status = f"failed: {exc}"` | Records the failure without raising | Reported in the result. A swallowed exception you never see is how silent data loss starts |
| the `for wo in work_orders` loop | Counts open work orders — **again** | Byte-for-byte the same logic as Technique 1, and the single most important thing to notice in this chapter |
| `node_props = {**spec_props, ...}` | Merges parser output with computed fields | One dict, one write. Extracted specs first, then relations and derived values overlaid |
| `completenessScore` | The parser's own confidence in its coverage | Technique 2's substitute for Technique 1's `missing_fields` — less precise, but it is the signal available |
| `fieldsWritten: sorted(spec_props)` | Exactly which specs were written | Sorted so two runs are diffable |

📚 `[DOCS]` [Parse documents](https://docs.cognite.com/cdf/integration/guides/contextualization/parse_documents) ·
[Cognite Functions](https://docs.cognite.com/cdf/functions/) ·
[Data modeling](https://docs.cognite.com/cdf/dm/)

📝 `[WRITE]` `requirements.txt`: `cognite-sdk==8.10.0`

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/functions/ParseDatasheet.Function.yaml`

```yaml
externalId: fnc_<YOURNAME>_Training_ParseDatasheet
name: fnc_<YOURNAME>_Training_ParseDatasheet
owner: Training
description: Parse pump datasheet via the Document Parser API into EquipmentHealthProfile.
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

🚧 `[LIMITS]` Endpoint is INTERNAL and subject to change without notice.
`userPrompt` ≤ 4000 characters. `pageRange` (if you set one on `files[]`) covers at
most 10 pages, PDF only, 1-indexed. Status enum: `Queued | Running | Completed |
Failed`.

💡 `[GOOD TO KNOW]` To run the Document Parser from a notebook, **your** login needs
Data Models **read + write** and Files **read** (see [Chapter 02](02-auth-and-security.md)
Section 2.4) — the same two-identity caveat as every other job-based call in this course. If a
call returns `403`, run `cdf auth verify` and ask your CDF administrator to grant the
missing capability.

---

## 10.5b [INFO] Merge or replace — the flag that quietly deletes your data

Both techniques write the **same node** with `instances.apply()`. That is only safe
because of a default you have not thought about:

| Mode | How | What happens to properties you did *not* send |
|---|---|---|
| **Merge** (patch) | `replace=False` — the default | Left alone |
| **Replace** | `replace=True` | **Set to null** |

Technique 1 writes eight specs. Technique 2 writes six. If either ran with
`replace=True`, it would wipe whatever the other had just written, and the last one to
run would win — silently, with no error, on a node that looks perfectly healthy.

⚠️ `[COMMON MISTAKE]` Reaching for `replace=True` to "clean up" a node. It does not mean
*overwrite the fields I am sending*; it means *this payload is now the entire node*.
Use it only when you genuinely intend to reset an instance's state in that container,
and never in a pipeline where more than one writer touches the same node.

💡 `[GOOD TO KNOW]` The same request carries three more flags worth knowing:

- `auto_create_direct_relations=True` (**default on**) — targets of direct relations are
  created as bare nodes if missing. Convenient, and the reason a typo'd asset reference
  produces a silent dangling link rather than an error (you meet the consequence in
  [Chapter 14](14-debugging-broken-links.md) section 14.3).
- `auto_create_start_nodes` / `auto_create_end_nodes` (**default off**) — an edge whose
  endpoints do not exist fails with `409` instead.
- `skip_on_version_conflict=False` — see section 10.5c.

---

## 10.5c [INFO] Two writers, one node — optimistic concurrency

Every instance carries a version that increments on each write. When two processes
write the same node, the second silently overwrites the first — unless you say what you
expected:

```python
NodeApply(space=space, external_id="ehp_21-PA-2001A", existing_version=3, sources=[...])
```

If the node has moved on since you read it, CDF rejects the write with **409 Conflict**
rather than clobbering someone else's change. You then re-read and decide.

`existing_version=0` means *I believe this does not exist yet* — the way to create
without risking an overwrite.

⚡ `[OPTIMIZE]` In a bulk write where a few conflicts are acceptable, pass
`skip_on_version_conflict=True`: conflicting instances are skipped and the rest of the
batch still lands, instead of the whole request failing.

---

## 10.6 [ACTION] Build, deploy, run, compare

```bash
uv run cdf build --config-yaml training/config.<YOURNAME>-training.yaml
uv run cdf deploy --cdf-project <your-cdf-project> --include functions
```

```python
result = client.functions.call(external_id="fnc_<YOURNAME>_Training_ParseDatasheet")
print(result.get_response())
```

✅ `[VERIFY]` `status: "Completed"`, `openWorkOrderCount: 1` (matches `WO-1001`,
`IN_PROGRESS`, on `21-PA-2001A`), and `fieldsWritten` lists the extracted spec fields.
On this training project `write_status` will read `failed: ...` — that's the
expected `jobs/write` 500 (section 10.4), and the deterministic fallback still populates the
node, so it's **not** a lab failure. Open `ehp_21-PA-2001A` in Fusion → confirm the
rated-spec fields are populated and `datasheetFile` links back to your PDF.

| Regex (Technique 1) | Document Parser API (Technique 2) |
|---|---|
| `missing_fields` list — deterministic, explainable | `scores.completenessScore` / `typeScore` — statistical confidence, per job |
| Zero cost, offline | Vision-capable, layout-tolerant, costs a job + polling budget |
| Breaks silently on format drift | Degrades gracefully — a confidence score flags weak extractions instead of returning nothing |
| No teardown obligation | No teardown obligation either (unlike entity-matching models, section 7.4) — jobs are not global schema objects |

---

## Gate

**Do not proceed to Chapter 11 until:**

- `ehp_21-PA-2001A` is populated via the Document Parser API and verified in Fusion
- You ran Technique 1 in your notebook and can name at least one field where the two
  techniques agree, and explain what would make them disagree
- You can state, from memory, why `userPrompt` doesn't carry the schema and what does
- Your `EquipmentHealthProfile` container has real per-property descriptions, redeployed
- 📓 You have added your two or three lines for this chapter to `participants/<YOURNAME>/NOTES.md` — **now**, not tonight

→ [Chapter 11 — Datapoints](11-datapoints.md)
