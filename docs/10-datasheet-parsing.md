# Chapter 10 — Datasheet Parsing

**Goal:** populate the Equipment Health Profile using two techniques — deterministic
regex, and the agentic Cognite Document Parser API — and understand why
**description engineering on your view is the real lever** for the second one.

Both techniques converge on the exact same target: upserting node `ehp_21-PA-2001A`
(literal externalId, isolated by your own space — never `YOURNAME`-scoped, per §1.2)
into `viw_EquipmentHealthProfile_sdm`. The sequence is always: **model exists → file
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
in §10.5 is the Technique 2 version; keep this one as your own local comparison)*:

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

    v_wo = ViewId(schema_edm, "viw_WorkOrder_edm", model_version)
    work_orders = client.data_modeling.instances.list(instance_type="node", sources=[v_wo], space=space, limit=-1)
    open_count = 0
    for wo in work_orders:
        props = wo.properties.get(v_wo, {})
        status = (props.get("status") or "").upper()
        asset_ids = [r.external_id if hasattr(r, "external_id") else r.get("externalId") for r in (props.get("assets") or [])]
        if "21-PA-2001A" in asset_ids and status != "CLOSED":
            open_count += 1

    v_ehp = ViewId(schema_sdm, "viw_EquipmentHealthProfile_sdm", model_version)
    ehp_props = {
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
| `v_wo = ViewId(schema_edm, "viw_WorkOrder_edm", model_version)` | Points at **your** view | Note it uses `schema_edm` from env, not a literal — the same code works for every participant |
| the `for wo in work_orders` loop | Counts open work orders on `21-PA-2001A` | **This is the point of the exercise.** No regex can find this in the PDF — it is a *relational* fact that exists only in the graph. Technique 2 cannot read it either |
| `r.external_id if hasattr(r, "external_id") else r.get("externalId")` | Handles both shapes of a direct relation | The SDK returns a typed object in some paths and a plain dict in others |
| `status != "CLOSED"` | Counts anything not closed as open | Deliberately permissive — an unexpected status counts as open. For a *health* metric, over-reporting risk is the safer error |
| `isoformat(timespec="milliseconds")` | Timestamp with exactly 3 fractional digits | See the `[LIMITS]` note directly below — this is a hard API constraint, not a style choice |
| `NodeApply(external_id="ehp_21-PA-2001A")` | Writes the health profile node | The externalId stays **literal**, not name-scoped — your space already isolates it (§1.2) |
| `{k: v for k, v in parsed.items() if k not in ("manufacturer", "serialNumber")}` | Omits two fields from the return | They are parsed to prove the regex works, but they are not view properties, so they are not written or reported |

📚 `[DOCS]` [Data modeling](https://docs.cognite.com/cdf/dm/) ·
[Cognite Functions](https://docs.cognite.com/cdf/functions/)

🚧 `[LIMITS]` CDF `timestamp` properties accept at most **3 fractional digits**.
`datetime.now(timezone.utc).isoformat()` by default produces 6 (microseconds) and
will be **rejected**. Always call `isoformat(timespec="milliseconds")`.

---

## 10.3 [OPTIMIZE] Description engineering — the real lever for Technique 2

Before you touch the Document Parser API, understand this: `viewConfig` in the
`start` call (§10.4) points at your `viw_EquipmentHealthProfile_sdm` view — and
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

📝 `[WRITE]` update `participants/<YOURNAME>/data_modeling/con_TRAINING_sdm.Container.yaml`
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
maintain — one well-written description serves both audiences (§3.7 already told you
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
    "viewConfig": {"space": schema_sdm, "externalId": "viw_EquipmentHealthProfile_sdm", "version": "v1.0.0"},
    "files": [{"fileInstanceId": {"space": space, "externalId": file_xid}}],
    "node": {"space": space, "externalId": "ehp_21-PA-2001A"},
    "useVision": True,
    "userPrompt": "Extract pump datasheet specifications per the target view's property descriptions. If a value is absent from the document, leave it empty -- do not guess.",
}
job_id = client.post(f"{DOCPARSER}/jobs/start", json=start_body).json()["jobId"]
```

🛑 `[COMMON MISTAKE]` — **raw `client.post` needs the full project-scoped path.** Unlike
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

Then persist the result. **`jobs/write` is INTERNAL and currently returns `500` on the
training project**, so treat it as *best-effort* and never depend on it — you already
hold every extracted value in `result["rawResponses"]`, so write them into the node
yourself with the typed SDK (idempotent; the same `instances.apply` the Function uses):

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

v_ehp = ViewId(schema_sdm, "viw_EquipmentHealthProfile_sdm", "v1.0.0")
client.data_modeling.instances.apply(nodes=[NodeApply(
    space=space, external_id="ehp_21-PA-2001A",
    sources=[NodeOrEdgeData(source=v_ehp, properties=props)],
)])
print("wrote:", sorted(props))
```

🚧 `[LIMITS]` The `jobs/write` `500` is a **platform-side fault** on this preview
endpoint (it recurs on fresh `Completed` jobs with a valid body), not a bug in your code
— it is not enabled for your project. (It likely needs the job at `validation: approved`, for
which no endpoint is currently exposed.) The fallback above
reaches the same end state deterministically — which is the correct production posture:
never hard-fail on a flaky internal endpoint when you already hold the data it would
write. Instance writes are a property-level *merge* (`replace=False`), so this upsert
keeps the relational fields Technique 1 wrote in §10.2.

⚠️ `[COMMON MISTAKE]` Polling the single `GET /context/documentparser/{jobId}` — it
is **unreliable / 404s in practice**. Always use `POST /jobs/byids`. Also: forgetting
`useVision: true` — the non-vision path misses fields on this datasheet's layout.

✅ `[VERIFY]` notebook results in CDF:

```python
v_ehp = ViewId(schema_sdm, "viw_EquipmentHealthProfile_sdm", "v1.0.0")
node = client.data_modeling.instances.retrieve_nodes(nodes=[(space, "ehp_21-PA-2001A")], sources=[v_ehp])[0]
print(node.properties.get(v_ehp))
```

Compare this against Technique 1's `parsed` output from §10.2 — on this clean,
text-based training PDF both techniques should agree closely. Note where they don't,
and why (§10.6).

---

## 10.5 [WRITE] The Function: `ParseDatasheet` (Technique 2, deployed)

This is the version you actually ship — the agentic Document Parser API, since it's
the technique that scales past one hand-tuned regex per vendor template.

### What changes versus Technique 1 — and what doesn't

| | Technique 1 (regex) | Technique 2 (Document Parser) |
|---|---|---|
| How specs are found | Your `PATTERNS` dict | The API reads the PDF **and its own view property descriptions** |
| Where the instructions live | In the Python | In the **view's property descriptions** (§10.3) |
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
`viewConfig`, pointing at your `viw_EquipmentHealthProfile_sdm`, whose property descriptions
you wrote in §10.3.

Change what gets extracted by editing a **description in the data model**, not by editing and
redeploying Python. That is what makes this genuinely agentic rather than a fancier regex.

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/functions/fnc_<YOURNAME>_Training_ParseDatasheet/handler.py`

```python
"""Parse the pump datasheet via the Cognite Document Parser API, then compute the
relational/derived fields the parser cannot see in the PDF text (Technique 2)."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from cognite.client.data_classes.data_modeling import (
    DirectRelationReference, NodeApply, NodeOrEdgeData, ViewId,
)

POLL_BUDGET_SECONDS = 8 * 60
POLL_INTERVAL_SECONDS = 15
USER_PROMPT = (
    "Extract pump datasheet specifications per the target view's property "
    "descriptions. If a value is not explicitly present in the document, leave it "
    "empty -- do not guess or estimate."
)
# Spec fields the parser fills, by destination type (see con_TRAINING_sdm, §3.7).
FLOAT_FIELDS = ["ratedFlowM3h", "ratedHeadM", "ratedPowerKw",
                "designPressureBarg", "designTemperatureC", "dryWeightKg"]
TEXT_FIELDS = ["casingMaterial", "sealType"]


def _extracted_props(result: dict) -> dict:
    """Map the parser's per-field answers to typed EHP view properties.

    result["rawResponses"] is {propName: {"value": .., "pageNum": .., "spatialData": ..}}.
    """
    raw = (result or {}).get("rawResponses") or {}
    props: dict = {}
    for field in FLOAT_FIELDS:
        value = (raw.get(field) or {}).get("value")
        if value not in (None, ""):
            try:
                props[field] = float(str(value).split()[0])  # tolerate "320 m3/h"
            except (ValueError, IndexError):
                pass
    for field in TEXT_FIELDS:
        value = (raw.get(field) or {}).get("value")
        if value not in (None, ""):
            props[field] = str(value)
    return props


def handle(client, data=None, secrets=None, function_call_info=None) -> dict:
    participant = os.environ["PARTICIPANT"]
    space = os.environ["INSTANCE_SPACE"]
    schema_edm = os.environ["SCHEMA_SPACE_EDM"]
    schema_sdm = os.environ["SCHEMA_SPACE_SDM"]
    model_version = os.environ.get("MODEL_VERSION", "v1.0.0")
    file_xid = f"file_{participant}_TRN_DS_21_PA_2001A"
    # Raw client.post does NOT auto-prepend the project scope -- build the full path
    # (same reason Load3DRevision in Chapter 09 uses /api/v1/projects/{project}/...).
    DOCPARSER = f"/api/v1/projects/{client.config.project}/context/documentparser"

    # /jobs/start is single-job: a FLAT body, and it returns {jobId, status}
    # (the batch endpoint is POST /jobs with an items[] array).
    start_body = {
        "viewConfig": {"space": schema_sdm, "externalId": "viw_EquipmentHealthProfile_sdm", "version": model_version},
        "files": [{"fileInstanceId": {"space": space, "externalId": file_xid}}],
        "node": {"space": space, "externalId": "ehp_21-PA-2001A"},
        "useVision": True,
        "userPrompt": USER_PROMPT,
    }
    job_id = client.post(f"{DOCPARSER}/jobs/start", json=start_body).json()["jobId"]

    deadline = time.time() + POLL_BUDGET_SECONDS
    status, detail = "Queued", {}
    while status in ("Queued", "Running") and time.time() < deadline:
        time.sleep(POLL_INTERVAL_SECONDS)
        detail = client.post(f"{DOCPARSER}/jobs/byids", json={"items": [{"jobId": job_id}]}).json()["items"][0]
        status = detail["status"]["job"] if isinstance(detail.get("status"), dict) else detail.get("status")

    if status != "Completed":
        # Never block indefinitely -- report back and let the caller retry later.
        return {"jobId": job_id, "status": status, "resume": status in ("Queued", "Running")}

    result = detail.get("result") or {}          # scores + rawResponses live here
    spec_props = _extracted_props(result)

    # jobs/write is INTERNAL (public preview) and may return 500. Attempt it (so
    # this self-heals if the platform is fixed), but never depend on it -- we already
    # hold the extracted values, so we write them ourselves below (idempotent).
    write_status = "ok"
    try:
        client.post(f"{DOCPARSER}/jobs/write", json={"items": [{"jobId": job_id}]})
    except Exception as exc:
        write_status = f"failed: {exc}"

    # Relational/derived fields the extraction model cannot read off the page --
    # compute them yourself, same as Technique 1 did.
    v_wo = ViewId(schema_edm, "viw_WorkOrder_edm", model_version)
    work_orders = client.data_modeling.instances.list(instance_type="node", sources=[v_wo], space=space, limit=-1)
    open_count = 0
    for wo in work_orders:
        props = wo.properties.get(v_wo, {})
        wo_status = (props.get("status") or "").upper()
        asset_ids = [r.external_id if hasattr(r, "external_id") else r.get("externalId") for r in (props.get("assets") or [])]
        if "21-PA-2001A" in asset_ids and wo_status != "CLOSED":
            open_count += 1

    node_props = {
        **spec_props,  # extracted specs (parser) + relational/derived (computed here)
        "asset": DirectRelationReference(space, "21-PA-2001A"),
        "equipment": DirectRelationReference(space, "EQ-1002"),
        "datasheetFile": DirectRelationReference(space, file_xid),
        "openWorkOrderCount": open_count,
        "lastParsedTime": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    }
    v_ehp = ViewId(schema_sdm, "viw_EquipmentHealthProfile_sdm", model_version)
    client.data_modeling.instances.apply(nodes=[NodeApply(
        space=space, external_id="ehp_21-PA-2001A",
        sources=[NodeOrEdgeData(source=v_ehp, properties=node_props)],
    )])

    completeness = ((result.get("scores") or {}).get("completenessScore") or {}).get("score")
    return {
        "jobId": job_id, "status": status, "write_status": write_status,
        "completenessScore": completeness, "fieldsWritten": sorted(spec_props),
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
description: Parse pump datasheet via the Document Parser API into viw_EquipmentHealthProfile_sdm.
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
§2.4) — the same two-identity caveat as every other job-based call in this course. If a
call returns `403`, run `cdf auth verify` and ask your CDF administrator to grant the
missing capability.

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
expected `jobs/write` 500 (§10.4), and the deterministic fallback still populates the
node, so it's **not** a lab failure. Open `ehp_21-PA-2001A` in Fusion → confirm the
rated-spec fields are populated and `datasheetFile` links back to your PDF.

| Regex (Technique 1) | Document Parser API (Technique 2) |
|---|---|
| `missing_fields` list — deterministic, explainable | `scores.completenessScore` / `typeScore` — statistical confidence, per job |
| Zero cost, offline | Vision-capable, layout-tolerant, costs a job + polling budget |
| Breaks silently on format drift | Degrades gracefully — a confidence score flags weak extractions instead of returning nothing |
| No teardown obligation | No teardown obligation either (unlike entity-matching models, §7.4) — jobs are not global schema objects |

---

## Gate

**Do not proceed to Chapter 11 until:**

- `ehp_21-PA-2001A` is populated via the Document Parser API and verified in Fusion
- You ran Technique 1 in your notebook and can name at least one field where the two
  techniques agree, and explain what would make them disagree
- You can state, from memory, why `userPrompt` doesn't carry the schema and what does
- Your `con_TRAINING_sdm` container has real per-property descriptions, redeployed
- 📓 You have added your two or three lines for this chapter to `participants/<YOURNAME>/NOTES.md` — **now**, not tonight

→ [Chapter 11 — Datapoints](11-datapoints.md)
