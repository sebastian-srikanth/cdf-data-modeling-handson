# Chapter 07 — Entity Matching

**Goal:** contextualize your two PDF files to the assets they describe, using three
different techniques, understanding the tradeoffs of each — then package the one that
scales into a Cognite Function.

This is the first **Function chapter**, and it introduces the fixed pedagogy every
remaining Function chapter follows:

1. `[INFO]` why this capability exists in the lab architecture
2. `[WRITE]` + `[ACTION]` a Jupyter notebook — cell-by-cell exploration
3. `[VERIFY]` notebook results in CDF
4. `[WRITE]` the Cognite Function, derived from the notebook
5. `[ACTION]` build / dry-run / deploy
6. `[VERIFY]` the Function's execution matches what the notebook taught you
7. Gate

---

## 7.1 [INFO] Why entity matching exists here

You uploaded two files in [Chapter 04](04-data-sets-raw-and-files.md):
`file_<YOURNAME>_TRN_PID_21_SEP` and `file_<YOURNAME>_TRN_DS_21_PA_2001A`, each already
carrying a hardcoded `assets:` link because *you* knew which asset each belonged to
when you wrote the YAML. That doesn't scale — a real ingestion pipeline receives
hundreds of files with no CDF-native link to an asset at all, only a filename, a
title, or free text. **Contextualization** is the general problem of resolving that
missing link. This chapter teaches three ways to solve it, deliberately in increasing
order of effort and decreasing order of "you know exactly what's happening."

---

## 7.2 [INFO] Technique 1 — Manual matching

You explicitly hardcode `file → asset`, because you (a human) already know the
mapping — exactly what you did in Chapter 04's `assets:` block.

**Correct for:** small, known sets; demos; establishing *ground truth* you'll later
use to check an automated technique's accuracy against.
**Wrong for:** anything that doesn't fit in your head or a spreadsheet.

---

## 7.3 [INFO] Technique 2 — Regex / rule-based matching

Extract a recognizable tag pattern from a filename or title
(`TRN-21-PA-2001A-Datasheet.pdf` → `21-PA-2001A`) with a regular expression, then
resolve that string directly to an asset externalId.

```python
import re
m = re.search(r"(\d{2}-[A-Z]{2}-\d{4}[A-Z]?)", filename)
asset_xid = m.group(1) if m else None
```

**Strengths:** deterministic, fully auditable (you can point at the exact regex that
produced a match), zero marginal cost per file, no model to manage.
**Failure mode:** brittle to format drift — a renamed file, an inconsistent naming
convention from a different site, or a typo silently produces no match (or worse, a
wrong one) with no confidence score to flag it.

---

## 7.4 [INFO] Technique 3 — CDF Entity Matching API

For genuinely fuzzy cases (titles that don't contain a clean tag, OCR'd text,
inconsistent naming across source systems), CDF offers a statistical matcher:

```python
model = client.entity_matching.fit(
    sources=sources,          # [{"id": ..., "name": ...}, ...] — your files
    targets=targets,          # [{"id": ..., "name": ...}, ...] — your assets
    match_fields=[("name", "name")],
    feature_type="bigram",
    external_id=model_xid,
)
predictions = client.entity_matching.predict(id=model.id, sources=sources, targets=targets)
```

`fit` trains an **unsupervised** model on string similarity between your source and
target name fields; `predict` scores every source against every target and returns
ranked matches. `feature_type` controls the similarity algorithm (`simple`,
`bigram`, `frequencyweightedbigram`, and combinations — Fusion's UI exposes these as
"Simple / Insensitive / Bigram / Frequency weighted bigram / Bigram combo").

⚠️ `[COMMON MISTAKE]` Entity-matching **models are global to the CDF project**,
not scoped to your space. The training project already has other unsupervised
bigram-combo models sitting in it from other work — proof this isn't hypothetical.
**You must delete your model when you're done with it** (the notebook and the
Function both do this — see §7.6 and §7.8). Leaving models behind pollutes a shared,
project-wide namespace that has nothing to do with your instance space isolation.

📚 `[DOCS]` https://docs.cognite.com/cdf/integration/concepts/contextualization/overview ·
https://docs.cognite.com/cdf/integration/guides/contextualization/matching ·
https://docs.cognite.com/cdf/integration/guides/contextualization/match_entities

---

## 7.5 [INFO] Side-by-side comparison

| | Manual | Regex | Entity Matching API |
|---|---|---|---|
| Accuracy | Perfect (it's ground truth) | High if format is stable; brittle otherwise | Good on fuzzy text; needs score-threshold tuning |
| Effort per file | High (human time) | Near-zero after the regex is written | Near-zero after `fit` — but `fit`/`predict` cost job time |
| Scales to 1000s of files? | No | Yes, if format is consistent | Yes |
| Observability | Perfect — you wrote it | High — the matching regex is inspectable | Medium — a similarity **score**, not a reason |
| Auditability | Perfect | High | Medium (score + fields used, not a human-readable "why") |
| Teardown obligation | None | None | **Must delete the model** (global resource) |

**How a production Function combines them — and how yours does:** try regex first
(cheap, deterministic); fall through to the Entity Matching API only for files the regex
couldn't resolve; treat matches below a score threshold (e.g. `< 0.5`) the same as "no
match" and route them to manual review rather than silently accepting a low-confidence
guess; and let a caller pass explicit overrides for known exceptions. The
`MatchDocuments` Function you write in §7.7 implements this **full cascade**: optional
manual overrides → regex → EM-on-miss → threshold gate. Because the regex resolves both
of this lab's PDFs, a normal call **never reaches EM** (`em_ran: false`, no model
created) — which is exactly right: EM is the expensive fallback, not the default. You
watch `fit`/`predict` run for real in the **notebook** (§7.6), where you can see and
interpret the scores — including the P&ID's weak, below-threshold hit that is *why* you
don't call EM first.

---

## 7.6 [WRITE] + [ACTION] Notebook: `01_entity_matching.ipynb`

📝 `[WRITE]` Recreate this notebook yourself at
`docs/notebooks/01_entity_matching.ipynb` (a starting template exists in
this course's `notebooks/` folder — open it, then **run every cell yourself**,
one at a time, reading the output before moving to the next).

The cell order mirrors the eventual Function handler exactly: **auth → list/retrieve →
mutate/job submit → poll with timeout → inspect result → cleanup.**

🟢 `[ACTION]` Work through the notebook now. It will, in order:

1. Authenticate and list your two files and your eight assets
2. Demonstrate Technique 1 (manual dict) and Technique 2 (regex) resolving both files
3. Run Technique 3 for real: `fit` a bigram model on your files vs. assets, poll until
   `Completed`, `predict`, and print each match's score
4. Apply the matches scoring `≥ 0.5` as real `assets` updates on the file nodes (a
   real, idempotent SDK write — not a simulation)
5. **Delete the entity-matching model** — the mandatory cleanup step
6. End with the explicit bridge question: *"Now package this into a Cognite
   Function — what changes (env vars instead of hardcoded names, no interactive
   auth, a timeout budget, structured logging, idempotent re-runs)?"*

✅ `[VERIFY]` notebook results in CDF: open `file_<YOURNAME>_TRN_PID_21_SEP` and
`file_<YOURNAME>_TRN_DS_21_PA_2001A` in Fusion → confirm both now show an `assets`
relation to `TRN-21-SEP` and `21-PA-2001A` respectively (matching what you already
hardcoded in Chapter 04 — the automated match should agree with your ground truth).
Then confirm the model is **gone**:

```python
try:
    client.entity_matching.retrieve(external_id="emp_<YOURNAME>_Datasheet_TRN")
    print("STILL THERE — delete it")
except Exception:
    print("confirmed deleted")
```

---

## 7.7 [WRITE] The Function: `MatchDocuments`

### What this Function does

It answers one question for each PDF you uploaded in [Chapter 04](04-data-sets-raw-and-files.md):
**which equipment is this document about?** Then it writes that answer back into CDF as a
direct relation, so that opening `21-PA-2001A` in Fusion shows its datasheet attached.

### Why it is built as a cascade

The three techniques from §7.2–7.4 are not alternatives here — they run **in order, cheapest
first**, and each one only sees what the previous could not resolve:

```
manual override  ──►  regex on filename  ──►  Entity Matching API  ──►  score gate
(free, certain)       (free, deterministic)   (costs a model + polling)  (≥ 0.5 applies)
```

That ordering is the whole design. Machine learning is the **last** resort, not the first,
because it is the only step that costs money, takes time, and can be wrong. A production
contextualization pipeline looks exactly like this: exhaust the deterministic options, then
spend compute only on the genuine leftovers.

> ⚠️ The EM model is **deleted on every exit path**. Entity-matching models are *global* to
> the CDF project — unlike your spaces, they are **not** namespaced by participant, so a
> model left behind is visible to and collides with everyone else in the cohort. This is the
> one resource in the whole lab that does not isolate itself. See
> [Chapter 13](13-cross-cutting-mastery.md) §13.7.

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/functions/fnc_<YOURNAME>_Training_MatchDocuments/handler.py`

```python
"""Match PDF CogniteFile nodes to CogniteAsset nodes.

Production-shaped cascade:
  1) optional manual overrides from the call payload (`data["manual"]`)
  2) regex on the file name (cheap, deterministic)
  3) Entity Matching API only for files regex/manual did not resolve
Always deletes any EM model this call created.
"""

from __future__ import annotations

import os
import re
import time

from cognite.client.data_classes.data_modeling import (
    DirectRelationReference,
    NodeApply,
    NodeOrEdgeData,
    ViewId,
)

TAG_RE = re.compile(r"(\d{2}-[A-Z]{2}-\d{4}[A-Z]?)")
AREA_RE = re.compile(r"(TRN-\d{2}-[A-Z]+)")


def handle(client, data=None, secrets=None, function_call_info=None) -> dict:
    participant = os.environ["PARTICIPANT"]
    space = os.environ["INSTANCE_SPACE"]
    model_xid = f"emp_{participant}_Datasheet_TRN"
    data = data or {}

    file_xids = [
        f"file_{participant}_TRN_PID_21_SEP",
        f"file_{participant}_TRN_DS_21_PA_2001A",
    ]
    v_file = ViewId("cdf_cdm", "CogniteFile", "v1")
    v_asset = ViewId("cdf_cdm", "CogniteAsset", "v1")

    files = client.data_modeling.instances.retrieve_nodes(
        nodes=[(space, xid) for xid in file_xids],
        sources=[v_file],
    )
    assets = client.data_modeling.instances.list(
        instance_type="node", sources=[v_asset], space=space, limit=-1,
    )
    asset_xids = {a.external_id for a in assets}

    # Optional human overrides: {"manual": {"file_...": "21-PA-2001A", ...}}
    manual_map = data.get("manual") or {}

    matches, below, applies = [], [], []
    unresolved = []  # files that still need EM

    for f in files:
        name = f.properties.get(v_file, {}).get("name") or f.external_id
        src_id = f.external_id

        # 1) Manual override (production: review queue / known exceptions)
        if src_id in manual_map and manual_map[src_id] in asset_xids:
            tgt_id = manual_map[src_id]
            matches.append({"source": src_id, "target": tgt_id, "method": "manual"})
            applies.append(_apply_asset(space, src_id, v_file, tgt_id))
            continue

        # 2) Regex on filename
        m = TAG_RE.search(name) or AREA_RE.search(name)
        candidate = m.group(1) if m else None
        if candidate and candidate in asset_xids:
            matches.append({"source": src_id, "target": candidate, "method": "regex"})
            applies.append(_apply_asset(space, src_id, v_file, candidate))
            continue

        unresolved.append(f)

    # 3) EM only for leftovers
    em_matches, em_below, em_applies, em_meta = [], [], [], {}
    if unresolved:
        em_matches, em_below, em_applies, em_meta = _entity_match(
            client, space, v_file, v_asset, unresolved, assets, model_xid,
        )
        matches.extend(em_matches)
        below.extend(em_below)
        applies.extend(em_applies)

    if applies:
        client.data_modeling.instances.apply(nodes=applies)

    result = {
        "matches": matches,
        "below_threshold": below,
        "unresolved_count": len(unresolved),
        "em_ran": bool(unresolved),
    }
    if em_meta.get("model_delete_warning"):
        result["model_delete_warning"] = em_meta["model_delete_warning"]
    if em_meta.get("error"):
        result["error"] = em_meta["error"]
    return result


def _apply_asset(space, src_id, v_file, tgt_id) -> NodeApply:
    return NodeApply(
        space=space,
        external_id=src_id,
        sources=[NodeOrEdgeData(source=v_file, properties={
            "assets": [DirectRelationReference(space, tgt_id)]
        })],
    )


def _entity_match(client, space, v_file, v_asset, files, assets, model_xid):
    sources = [
        {"id": f.external_id, "name": f.properties.get(v_file, {}).get("name") or f.external_id}
        for f in files
    ]
    targets = [
        {"id": a.external_id, "name": a.properties.get(v_asset, {}).get("name") or a.external_id}
        for a in assets
    ]

    try:
        client.entity_matching.delete(external_id=model_xid)
    except Exception:
        pass

    model = client.entity_matching.fit(
        sources=sources, targets=targets,
        match_fields=[("name", "name")], feature_type="bigram",
        external_id=model_xid, name=model_xid,
    )
    deadline = time.time() + 300
    while getattr(model, "status", "Completed") not in ("Completed", "Failed") and time.time() < deadline:
        time.sleep(5)
        model = client.entity_matching.retrieve(id=model.id)

    if getattr(model, "status", None) != "Completed":
        try:
            client.entity_matching.delete(id=model.id)
        except Exception:
            pass
        return [], [], [], {"error": f"entity matching fit status={getattr(model, 'status', None)!r}"}

    predict = client.entity_matching.predict(
        id=model.id, num_matches=1, sources=sources, targets=targets,
    )
    # Fresh deadline; poll via update_status() — do not use retrieve_predict_job.
    deadline = time.time() + 300
    while predict.status not in ("Completed", "Failed") and time.time() < deadline:
        time.sleep(5)
        predict.update_status()

    if predict.status != "Completed":
        try:
            client.entity_matching.delete(id=model.id)
        except Exception:
            pass
        return [], [], [], {"error": f"entity matching predict status={predict.status!r}"}

    result = predict.get_result() if hasattr(predict, "get_result") else None
    result_items = result if isinstance(result, list) else (
        (result or {}).get("items") if isinstance(result, dict) else None
    )
    if result_items is None:
        result_items = getattr(predict, "result", None) or getattr(predict, "matches", None) or []
        if isinstance(result_items, dict):
            result_items = result_items.get("items") or []

    matches, below, applies = [], [], []
    for item in result_items:
        src = item.get("source") or item.get("sourceId") or {}
        src_id = src.get("id") if isinstance(src, dict) else src
        match_list = item.get("matches") or []
        if not match_list:
            continue
        best = match_list[0]
        score = float(best.get("score") or 0.0)
        tgt = best.get("target") or best.get("targetId") or {}
        tgt_id = tgt.get("id") if isinstance(tgt, dict) else tgt
        row = {"source": src_id, "target": tgt_id, "score": score, "method": "entity_matching"}
        if score < 0.5:
            below.append(row)
            continue
        matches.append(row)
        applies.append(_apply_asset(space, src_id, v_file, tgt_id))

    meta = {}
    try:
        client.entity_matching.delete(id=model.id)
    except Exception as exc:
        meta["model_delete_warning"] = str(exc)

    return matches, below, applies, meta
```

### Line-by-line walkthrough

| Code | What it does | Why it is written this way |
|---|---|---|
| `TAG_RE = r"(\d{2}-[A-Z]{2}-\d{4}[A-Z]?)"` | Finds an equipment tag like `21-PA-2001A` in a filename | Mirrors the site tag convention: *area–type–number–suffix*. The trailing `[A-Z]?` catches the `A`/`B` that distinguishes duty and standby pumps |
| `AREA_RE = r"(TRN-\d{2}-[A-Z]+)"` | Fallback: finds an area tag like `TRN-21-SEP` | A P&ID covers a whole separation area, not one pump — so it matches at area level. Tried **only if** `TAG_RE` misses |
| `def handle(client, ...)` | Entry point — must be named `handle` | `client` arrives **already authenticated** as the Function's own identity. Never construct a `CogniteClient` inside a Function. [Functions](https://docs.cognite.com/cdf/functions/) |
| `os.environ["PARTICIPANT"]` / `["INSTANCE_SPACE"]` | Reads your name and space | Injected via `envVars` in the `.Function.yaml` below. This is precisely why the Python is byte-identical for 15 people |
| `model_xid = f"emp_{participant}_..."` | Names the EM model with **your** name | EM models are project-global, so unlike a view or container this one **must** be name-scoped or it collides |
| `retrieve_nodes(nodes=[...], sources=[v_file])` | Fetches your two PDF nodes | `sources=` asks for properties *as seen through* the `CogniteFile` view. Without it you get the node but not its typed properties. [Data modeling](https://docs.cognite.com/cdf/dm/) |
| `instances.list(..., space=space, limit=-1)` | Fetches all your assets as match candidates | `space=space` is the isolation boundary — you can only ever match against your own 8 assets. `limit=-1` means "all" |
| `manual_map = data.get("manual")` | Human overrides passed in the call payload | Stage 1. In production this is the review queue: a person has already decided, so nothing should second-guess them |
| `if src_id in manual_map and manual_map[src_id] in asset_xids` | Accepts an override **only** if the target really exists | Never trust a payload blindly — a typo in an override would otherwise write a dangling relation |
| `TAG_RE.search(name) or AREA_RE.search(name)` | Stage 2: deterministic filename match | Free, instant, and explainable. Resolves the common case before any ML is considered |
| `unresolved.append(f)` | Collects the leftovers | Only these reach the paid API. On a good day this list is empty and `_entity_match` never runs |
| `_apply_asset(...)` → `DirectRelationReference(space, tgt_id)` | Writes the answer into `CogniteFile.assets` | **This is the actual contextualization.** Everything before it is just deciding; this line is what makes the link appear in Fusion |
| `client.entity_matching.fit(...)` | Trains a model on name→name similarity | `feature_type="bigram"` compares two-character sequences, so it tolerates punctuation and spacing differences that exact matching would fail on |
| `deadline = time.time() + 300` | Hard 300-second poll ceiling | A Function has a wall-clock limit. An unbounded `while` would burn the whole budget and be killed with no result and no cleanup |
| `predict.update_status()` | Polls the predict job | Deliberately **not** `retrieve_predict_job` — see the inline note. The job object refreshes itself |
| `result_items = ...` (the 5 defensive lines) | Normalises the response shape | The predict result has arrived as a list, as `{"items": [...]}`, and as an attribute across SDK versions. Written defensively so a minor version bump does not silently return zero matches |
| `if score < 0.5: below.append(row); continue` | The confidence gate | Low-confidence matches are **reported but never written**. Auto-applying a bad match is worse than applying nothing — a wrong link is silently believed by every downstream consumer |
| `client.entity_matching.delete(...)` in `try/except` × 3 | Deletes the model on **every** exit path | Success, fit failure, predict failure. `except: pass` on the pre-emptive delete because "it was not there" is the expected case, not an error |
| `meta["model_delete_warning"]` | Surfaces a failed cleanup instead of hiding it | If deletion fails you **must** know — you now own a global object that collides with the rest of the cohort |
| `return {...}` | Counts and lists, JSON-serializable | This dict is what appears in the Function's call-result log. Note it reports `below_threshold` and `unresolved_count` too — an honest result says what it did *not* do |

📚 `[DOCS]` [Cognite Functions](https://docs.cognite.com/cdf/functions/) ·
[Entity matching](https://docs.cognite.com/cdf/integration/guides/contextualization/match_entities) ·
[Data modeling](https://docs.cognite.com/cdf/dm/)

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/functions/fnc_<YOURNAME>_Training_MatchDocuments/requirements.txt`

```
cognite-sdk==8.10.0
```

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/functions/MatchDocuments.Function.yaml`

```yaml
externalId: fnc_<YOURNAME>_Training_MatchDocuments
name: fnc_<YOURNAME>_Training_MatchDocuments
owner: Training
description: Entity-match PDF files to CogniteAsset nodes and update file.assets.
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

🔧 `[CHANGE]` `handler.py` is **byte-identical** for every participant — same
argument as containers/views in §1.2. Only `Function.yaml`'s `externalId`, `name`,
and `envVars` values carry `YOURNAME`.

💡 `[GOOD TO KNOW]` — **notebook vs. Function, concretely.** The notebook runs the three
techniques *side by side* so you can compare them; the Function composes them into one
production **cascade** (manual override → regex → EM-on-miss → threshold gate). Other
differences: no interactive login (the Function runs under its own managed identity), no
hardcoded space string (it reads `INSTANCE_SPACE` from `envVars`), a hard 300-second
poll deadline on the EM path instead of "just wait and see," and it returns a
JSON-serializable dict instead of printing — that dict (`matches`, `below_threshold`,
`em_ran`, `unresolved_count`) is what shows up in the Function's call-result log
([Chapter 13](13-cross-cutting-mastery.md)).

---

## 7.8 [ACTION] Build, deploy, run

```bash
uv run cdf build --config-yaml training/config.<YOURNAME>-training.yaml
uv run cdf deploy --cdf-project <your-cdf-project> --include functions
```

🚧 `[LIMITS]` Function image builds take **2–10 minutes**. Kick this off, then keep
reading/working on the next section rather than watching a spinner.

🟢 `[ACTION]` Once the Function shows `status: Ready` in Fusion, call it once:

```python
result = client.functions.call(external_id="fnc_<YOURNAME>_Training_MatchDocuments")
print(result.get_response())
```

✅ `[VERIFY]` On this lab's two PDFs the regex resolves both, so the response should
show: `matches` = two entries each with `"method": "regex"`, `below_threshold` empty,
`unresolved_count: 0`, and **`em_ran: false`** — no entity-matching model is created or
deleted on this call. Then open both files in Fusion and confirm the `assets` relation
(`TRN-21-SEP`, `21-PA-2001A`). *Files linked correctly* is the success criterion —
**not** "EM scored them." You saw `fit`/`predict` run for real in the notebook (§7.6);
the Function reaches EM only for a file the regex can't resolve.

💡 `[GOOD TO KNOW]` To watch the EM branch fire in the *deployed* Function (not only the
notebook), call it with a payload that forces a miss — or pass explicit human overrides,
which the handler applies before regex:

```python
client.functions.call(
    external_id="fnc_<YOURNAME>_Training_MatchDocuments",
    data={"manual": {"file_<YOURNAME>_TRN_PID_21_SEP": "TRN-21-SEP"}},
)
```

⚡ `[OPTIMIZE]` The cascade **is** the optimization: the deterministic regex handles the
common case at zero job cost, so EM — the expensive part — runs only for files nothing
cheaper could resolve. And when EM *does* run, the handler `fit`/`predict`/`delete`s
from scratch every call rather than reusing a model: correct here, because the model is
cheap to rebuild and a stale one risks matching against assets that no longer exist.
Don't over-optimize away the "always start clean, always clean up" discipline for a
training-scale problem this small.

---

## Gate

**Do not proceed to Chapter 08 until:**

- The notebook ran end to end and you personally watched a `fit`/`predict` cycle
  complete (the notebook is where EM actually runs)
- Both files show the correct `assets` relation in Fusion — linked by the Function's
  **regex** path (the call returned `em_ran: false`)
- The entity-matching model is confirmed deleted after the **notebook** run; and you've
  confirmed the **Function** call created **no** model (regex resolved both files, so
  there was nothing to clean up)
- You can explain when you'd reach for each of the three techniques — and why a normal
  Function call returns `em_ran: false` while the notebook's EM cell does not
- 📓 You have added your two or three lines for this chapter to `participants/<YOURNAME>/NOTES.md` — **now**, not tonight

→ [Chapter 08 — Diagram Annotation](08-diagram-annotation.md)
