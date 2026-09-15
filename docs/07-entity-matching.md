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

### Where the rules live is the whole question

Hardcoding the mapping in a handler works exactly once. The moment an engineer finds a
wrong match at 23:00, the fix is a code change, a review, a deploy, and a pipeline re-run.

So in production the rules do not live in code. **They live in a RAW table**, and the
pipeline reads them on every run:

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/03_data/raw/rwt_Training_TRN_MappingRules.Table.yaml`

```yaml
dbName: rwd_<YOURNAME>_Training_TRN
tableName: rwt_Training_TRN_MappingRules
```

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/03_data/raw/rwt_Training_TRN_MappingRules.Table.csv`

```text
key,sourcePattern,targetExternalId,matchType,addedBy,reason
rule-001,TRN-21-SEP-PID.pdf,TRN-21-SEP,exact,course,The P&ID is the separation train drawing; its name carries no tag to match on.
rule-002,^TRN-21-PA-2001A-Datasheet,21-PA-2001A,regex,course,Vendor datasheets are named <tag>-Datasheet.pdf; anchor on the prefix.
```

Five columns, and each one is there for a reason:

| Column | Why it exists |
|---|---|
| `sourcePattern` | what to look for, in the file's name or external ID |
| `targetExternalId` | the asset it resolves to |
| `matchType` | `exact` or `regex`. Exact rules are evaluated first — a specific fix should always beat a general pattern |
| `addedBy` | who decided this. Six months later, this is the column you will care about |
| `reason` | why. A rule with no reason is a rule nobody dares delete |

💡 `[GOOD TO KNOW]` `addedBy` and `reason` do nothing technically and are the two most
valuable columns in the table. A mapping table without them becomes untouchable within a
year — everyone can see *what* it does and nobody knows *whether it is still true*.

⚠️ `[COMMON MISTAKE]` Treating the rules table as configuration and putting it in git
instead. It is **data**: a control-room engineer who cannot open a pull request must be
able to correct a bad match. This repository seeds two starter rows precisely because
they are a starting point, not the whole truth.

🚧 `[LIMITS]` A rule pointing at an asset that does not exist is a data error, not a
match. The handler checks the target against the real asset list and ignores rules that
fail it — otherwise a typo in a spreadsheet silently writes a dangling direct relation,
which is exactly the phantom-node problem from
[Chapter 14](14-debugging-broken-links.md).

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


⚠️ `[COMMON MISTAKE]` Verifying the cleanup with `try: retrieve(...) except:`.
`entity_matching.retrieve()` returns **`None`** for a model that is gone — it does not
raise — so the `except` branch never runs and a *successful* delete reports failure.
Compare against `None` instead:

```python
client.entity_matching.delete(id=model.id)
still = client.entity_matching.retrieve(external_id=model_xid)
print("confirmed deleted" if still is None else f"STILL THERE (id={still.id})")
```

💡 `[GOOD TO KNOW]` Across cognite-sdk 8.x, `retrieve()` returns `None` when nothing
matches and `list()` returns an empty list. Exceptions are for *errors*, not for
absence. Any `try/except` you write around a lookup is probably testing the wrong thing.

---

⚠️ `[COMMON MISTAKE]` **`get_result()` is a method. There is no `.result` property.**

This one is worth dwelling on, because of *how* it fails. Write the defensive-looking

```python
result_items = getattr(predict, "result", None) or getattr(predict, "matches", None) or []
```

and on cognite-sdk 8.x every one of those lookups misses. `result_items` becomes `[]`,
the function returns `{"matches": [], "below_threshold": []}`, the call is reported
**Completed**, and nothing anywhere raises. You get a green tick and an empty graph.

The correct form is the boring one:

```python
predict.wait_for_completion(timeout=600)
result_items = (predict.get_result() or {}).get("items") or []
```

💡 `[GOOD TO KNOW]` The general lesson outlives this API. `getattr(x, "name", None) or ...`
chains are a way of saying *"I am not sure what this object is"*, and they convert a
loud `AttributeError` into a silent wrong answer. Look the attribute up once, then call
it directly.

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
Function both do this — see section 7.6 and section 7.8). Leaving models behind pollutes a shared,
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
`MatchDocuments` Function you write in section 7.7 implements this **full cascade**: optional
manual overrides → regex → EM-on-miss → threshold gate. Because the regex resolves both
of this lab's PDFs, a normal call **never reaches EM** (`entity_matching_used: false`,
no model created) — which is exactly right: EM is the expensive fallback, not the default. You
watch `fit`/`predict` run for real in the **notebook** (section 7.6), where you can see and
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
still = client.entity_matching.retrieve(external_id="emp_<YOURNAME>_Datasheet_TRN")
print("confirmed deleted" if still is None else f"STILL THERE (id={still.id}) — delete it")

# models are global, so also check nothing else of yours is lingering
mine = [m for m in client.entity_matching.list(limit=-1)
        if "<YOURNAME>" in str(m.external_id)]
print("models still carrying your name:", [m.external_id for m in mine])
```

---

## 7.7 [WRITE] The Function: `MatchDocuments`

### What this Function does

It answers one question for each PDF you uploaded in [Chapter 04](04-data-sets-raw-and-files.md):
**which equipment is this document about?** Then it writes that answer back into CDF as a
direct relation, so that opening `21-PA-2001A` in Fusion shows its datasheet attached.

### Why it is built as a cascade

The three techniques from section 7.2–7.4 are not alternatives here — they run **in order, cheapest
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
> [Chapter 17](17-cross-cutting-mastery.md) section 17.7.

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/04_compute/functions/fnc_<YOURNAME>_Training_MatchDocuments/handler.py`

```python
"""Match PDF CogniteFile nodes to CogniteAsset nodes, cheapest technique first.

The cascade, in cost order:

  1. Mapping rules from RAW   free, deterministic, auditable, editable by a human
                              who cannot deploy code
  2. Regex on the file name   free, deterministic, but only as good as the naming
                              convention
  3. Entity Matching API      costs a model, a fit, a predict and polling -- run it
                              only on what is left, and gate the result on a score

Every rung that resolves a file removes it from the next rung's input. Entity Matching
is the fallback, not the default. A production contextualization pipeline is this shape
whatever the domain.
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

# Rung 2. Matches a tag embedded anywhere in a file name: TRN-21-PA-2001A-Datasheet.pdf
TAG_IN_FILENAME = re.compile(r"\b(\d{2}-[A-Z]{2}-\d{4}[A-Z]?)\b")

# Three bands, not one threshold. A single cut-off forces every uncertain match into
# one of two wrong answers: apply it silently, or throw it away. Bands give the middle
# case somewhere to go -- a review queue -- which is where contextualization actually
# lives in production. Calibrate these against a labelled set; do not guess them.
AUTO_APPLY_AT = 0.80      # at or above: write the link, record why
REVIEW_AT = 0.45          # between: suggest it, let a human decide
                          # below REVIEW_AT: reject, but still record that you looked


def _load_mapping_rules(client, raw_db: str, table: str) -> list[dict]:
    """Rung 1. Rules live in RAW so an engineer can correct a bad match by editing a
    row, with no code change and no deploy. Returns [] if the table is absent -- the
    cascade must still work for someone who has not created it yet."""
    try:
        rows = client.raw.rows.list(db_name=raw_db, table_name=table, limit=-1)
    except Exception:  # noqa: BLE001 - an absent table is a valid state, not an error
        return []
    rules = []
    for row in rows:
        c = row.columns or {}
        pattern = (c.get("sourcePattern") or "").strip()
        target = (c.get("targetExternalId") or "").strip()
        if pattern and target:
            rules.append({
                "pattern": pattern,
                "target": target,
                "matchType": (c.get("matchType") or "exact").strip().lower(),
                "addedBy": c.get("addedBy") or "",
                "reason": c.get("reason") or "",
            })
    return rules


def _apply_rules(rules: list[dict], file_xid: str, file_name: str) -> str | None:
    """First matching rule wins, so order in the table is policy. Exact before regex."""
    for rule in sorted(rules, key=lambda r: r["matchType"] != "exact"):
        if rule["matchType"] == "exact":
            if file_xid == rule["pattern"] or file_name == rule["pattern"]:
                return rule["target"]
        elif rule["matchType"] == "regex":
            try:
                if re.search(rule["pattern"], file_name) or re.search(rule["pattern"], file_xid):
                    return rule["target"]
            except re.error:
                continue  # a bad regex in a data row must not break the pipeline
    return None


def _rules_version(rules: list[dict]) -> str:
    """A stable identity for the rule set, so a change in results can be attributed.

    Hashes the content, sorted, so the value changes when a rule is added, removed OR
    edited, and does not change merely because RAW returned the rows in another order.
    """
    import hashlib
    material = "|".join(sorted(
        f"{r.get('matchType')}~{r.get('pattern')}~{r.get('target')}" for r in rules))
    digest = hashlib.sha1(material.encode()).hexdigest()[:8]
    return f"rules:{len(rules)}:{digest}"


def _band(score: float) -> str:
    if score >= AUTO_APPLY_AT:
        return "auto-applied"
    if score >= REVIEW_AT:
        return "needs-review"
    return "rejected"


def _existing_decisions(client, space: str, sdm: str, version: str) -> dict:
    """Every suggestion this space already holds, keyed by node externalId.

    Loaded **before** the handler does any work, because it drives two rules:

    * a person's decision outranks the machine's, on every rung, every run;
    * a pair a previous run proposed and this one does not is stale, not absent.

    Get the first one wrong once -- silently reverse an approval somebody made this
    morning -- and they stop trusting the system permanently.
    """
    from cognite.client.data_classes.data_modeling import ViewId as _ViewId
    view = _ViewId(sdm, "ContextualizationSuggestion", version)
    try:
        rows = client.data_modeling.instances.list(sources=view, space=space, limit=-1)
    except Exception:  # noqa: BLE001 - first run, the view has no data yet
        return {}
    return {row.external_id: dict(row.properties[view]) for row in rows}


def _human_vetoes(prior: dict) -> dict:
    """The subset of `prior` a person ruled on, keyed source|target."""
    out = {}
    for props in prior.values():
        if props.get("decidedBy") not in (None, "", "pipeline"):
            out[f"{props.get('sourceExternalId')}|{props.get('targetExternalId')}"] = \
                props.get("decision")
    return out


def handle(client, data=None, secrets=None, function_call_info=None) -> dict:
    participant = os.environ["PARTICIPANT"]
    space = os.environ["INSTANCE_SPACE"]
    raw_db = os.environ.get("RAW_DB", f"rwd_{participant}_Training_TRN")
    sdm = os.environ["SCHEMA_SPACE_SDM"]
    version = os.environ.get("MODEL_VERSION", "v1.0.0")
    model_xid = f"emp_{participant}_Datasheet_TRN"

    from datetime import datetime, timezone
    started = datetime.now(timezone.utc)
    # One correlation ID for everything this run produces. Callers can pass their own
    # so a Workflow can stamp every task in one execution with the same ID.
    data = data or {}
    run_id = data.get("runId") or f"ctxrun-{started:%Y%m%dT%H%M%SZ}-matchdocuments"
    workflow_execution = data.get("workflowExecutionId")

    # A person's decision outranks the machine's. Load them before doing anything.
    prior = _existing_decisions(client, space, sdm, version)
    human_decisions = _human_vetoes(prior)

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
    # retrieve_nodes returns a NodeList directly (not an object with .nodes)
    assets = client.data_modeling.instances.list(
        instance_type="node",
        sources=[v_asset],
        space=space,
        limit=-1,
    )

    asset_ids = {a.external_id for a in assets}

    # ---- rungs 1 and 2: resolve everything free before spending money -------------
    rules = _load_mapping_rules(client, raw_db, "rwt_Training_TRN_MappingRules")
    resolved: dict[str, dict] = {}          # file externalId -> {target, how}
    unresolved = []
    below: list[dict] = []                  # recorded, not applied
    vetoed: set[str] = set()                # a human said no; do not re-propose

    for f in files:
        name = f.properties.get(v_file, {}).get("name") or f.external_id

        target = _apply_rules(rules, f.external_id, name)
        how = "rule"

        if target is None:                                    # rung 2
            m = TAG_IN_FILENAME.search(name) or TAG_IN_FILENAME.search(f.external_id)
            if m and m.group(1) in asset_ids:
                target, how = m.group(1), "regex"

        # A rule naming an asset that does not exist is a data error, not a match.
        if target is not None and target not in asset_ids:
            target = None

        # A person's decision outranks the machine's -- on EVERY rung, not just on
        # the model. A rule is not more authoritative than a human who looked at the
        # link and said no; it is only cheaper. Without this check the rule rung
        # silently re-applies every rejection on the next run.
        if target is not None and human_decisions.get(f"{f.external_id}|{target}") == "rejected":
            below.append({"source": f.external_id, "target": target, "score": 1.0,
                          "method": how, "decision": "rejected-by-human"})
            target = None
            vetoed.add(f.external_id)

        if target is None:
            # A vetoed file does not go to the model. Escalating to a paid rung to
            # re-propose a link a person already rejected is the worst of both.
            if f.external_id not in vetoed:
                unresolved.append(f)
        else:
            evidence = (f"rule matched {name!r}" if how == "rule"
                        else f"tag {target!r} found in {name!r}")
            resolved[f.external_id] = {"target": target, "how": how,
                                       "score": 1.0, "evidence": evidence}

    # ---- rung 3: Entity Matching, on the remainder only --------------------------
    sources = []
    for f in unresolved:
        props = f.properties.get(v_file, {})
        sources.append({"id": f.external_id, "name": props.get("name") or f.external_id})

    targets = []
    for a in assets:
        props = a.properties.get(v_asset, {})
        targets.append({"id": a.external_id, "name": props.get("name") or a.external_id})

    matches: list[dict] = []
    model = None

    # If rules and regex resolved everything, there is nothing to fit a model on -- and
    # fitting one anyway is exactly the waste this cascade exists to avoid.
    if not sources:
        result = _write_and_report(
            client, space, v_file, files, resolved, matches, below, rules,
            model_used=False, retract=_retractions(prior, resolved),
            unresolved=unresolved
        )
        result["suggestions_recorded"] = _write_spine(
            client, space, sdm, version, run_id, resolved, below, unresolved, rules,
            started, prior=prior, workflow_execution=workflow_execution,
            retracted=result.get("links_retracted", 0))
        result["run_id"] = run_id
        return result

    # Drop a leftover model from a previous failed run (same externalId).
    try:
        client.entity_matching.delete(external_id=model_xid)
    except Exception:
        pass

    model = client.entity_matching.fit(
        sources=sources,
        targets=targets,
        match_fields=[("name", "name")],
        feature_type="bigram",
        external_id=model_xid,
        name=model_xid,
    )
    # Both fit and predict return job objects with a blocking wait. Use it.
    # A hand-rolled polling loop is what produced the "completed with zero
    # matches, no error" bug this handler used to have.
    model.wait_for_completion(timeout=600)
    if model.status == "Failed":
        try:
            client.entity_matching.delete(id=model.id)
        except Exception:
            pass
        return {"error": "entity matching fit failed", "model": model_xid}

    predict = client.entity_matching.predict(
        id=model.id,
        num_matches=1,
        sources=sources,
        targets=targets,
    )
    predict.wait_for_completion(timeout=600)

    # cognite-sdk 8.x: get_result() is a METHOD on the prediction job. There is
    # no `.result` property -- getattr(predict, "result", None) returns None and
    # you get zero matches with no error at all.
    result_items = (predict.get_result() or {}).get("items") or []

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
        row = {"source": src_id, "target": tgt_id, "score": score}
        band = _band(score)
        # If somebody already ruled on this pair, their decision stands.
        # NOTE the name. This used to be called `prior`, which shadowed the dict of
        # existing suggestions loaded at the top of handle() -- so after the first
        # entity-matching result, `prior` was a string and _retractions() crashed on
        # it. Nothing caught it for weeks, because every test resolved both documents
        # on the rule rung and this loop never executed.
        ruled = human_decisions.get(f"{src_id}|{tgt_id}")
        if ruled == "rejected":
            below.append({**row, "decision": "rejected-by-human"})
            continue
        if ruled == "approved":
            band = "auto-applied"
        if band != "auto-applied":
            # Still recorded. "We looked at this and were not sure" is information;
            # throwing it away is how a backlog becomes invisible.
            below.append({**row, "decision": band})
            continue
        resolved[src_id] = {"target": tgt_id, "how": "entity-matching", "score": score,
                            "evidence": f"entity matching scored {score:.3f}"}

    result = _write_and_report(
        client, space, v_file, files, resolved, matches, below, rules,
        model_used=True, retract=_retractions(prior, resolved),
        unresolved=[f for f in unresolved if f.external_id not in resolved]
    )
    result["suggestions_recorded"] = _write_spine(
        client, space, sdm, version, run_id, resolved, below, unresolved, rules,
        started, prior=prior, workflow_execution=workflow_execution,
        retracted=result.get("links_retracted", 0))
    result["run_id"] = run_id

    try:
        client.entity_matching.delete(id=model.id)
    except Exception as exc:  # noqa: BLE001 - cleanup is best-effort
        result["model_delete_warning"] = str(exc)
    return result


def _write_spine(client, space, sdm, version, run_id, resolved, below, unresolved,
                 rules, started, prior=None, technique="entity-matching",
                 workflow_execution=None, retracted=0):
    """Persist the run and the current state of every suggestion it considered.

    This is the difference between a pipeline you can operate and one you can only
    re-run and hope. `file.assets` tells you a link exists; these records tell you which
    rung made it, on what evidence, how confident it was, and who signed it off.

    Two identity decisions carry the whole design:

    * **A run is keyed by its run ID** -- immutable history. Every execution adds one.
    * **A suggestion is keyed by (source, target)** -- current state, not history. Run
      seventeen updates the same node run one created. That is what lets a person's
      decision survive: the handler refuses to overwrite a node whose `decidedBy` is
      anybody but `pipeline`. Key suggestions by run instead and you get an
      ever-growing pile in which this morning's approval is indistinguishable from a
      stale proposal nobody has looked at since March.
    """
    from datetime import datetime, timezone
    from cognite.client.data_classes.data_modeling import NodeApply, NodeOrEdgeData, ViewId

    def _ts(dt):
        return dt.isoformat(timespec="milliseconds")

    run_view = ViewId(sdm, "ContextualizationRun", version)
    sug_view = ViewId(sdm, "ContextualizationSuggestion", version)
    now = datetime.now(timezone.utc)
    prior = prior or {}

    nodes = []
    seen: set[str] = set()

    def _suggestion(source, target, method, confidence, decision, evidence):
        # Deterministic, run-independent external ID: the same pair is the same node
        # every run, so a re-run updates in place instead of duplicating.
        xid = f"sug_{source}_{target or 'none'}"[:255]
        seen.add(xid)
        # A person outranks the pipeline. Their row is left exactly as they left it.
        if prior.get(xid, {}).get("decidedBy") not in (None, "", "pipeline"):
            return None
        return NodeApply(space=space, external_id=xid,
            sources=[NodeOrEdgeData(source=sug_view, properties={
                "name": f"{source} -> {target or 'unresolved'}",
                "runId": run_id,
                "sourceExternalId": source,
                "targetExternalId": target,
                "method": method,
                "confidence": confidence,
                "decision": decision,
                "decidedBy": "pipeline",
                "decidedTime": _ts(now),
                "evidenceText": evidence,
            })])

    for src, info in resolved.items():
        nodes.append(_suggestion(src, info["target"], info["how"],
                                 info.get("score", 1.0), "auto-applied",
                                 info.get("evidence")))
    for row in below:
        decision = row.get("decision", "needs-review")
        method = row.get("method", "entity-matching")
        evidence = (row.get("evidence")
                    or ("a person rejected this pair" if decision == "rejected-by-human"
                        else f"scored {row.get('score') or 0:.3f}"))
        nodes.append(_suggestion(row["source"], row.get("target"), method,
                                 row.get("score"), decision, evidence))
    for f in unresolved:
        nodes.append(_suggestion(f.external_id, None, "none", 0.0, "unresolved",
                                 "no rung resolved this"))

    # ---- reconciliation: what a previous run proposed and this one no longer does ----
    # Silence is not agreement. A pair the pipeline applied last week and did not
    # produce today is a *change*, and leaving its row reading `auto-applied` is how a
    # link nobody can justify any more survives an audit.
    superseded = 0
    for xid, props in prior.items():
        if xid in seen:
            continue
        if props.get("decidedBy") not in (None, "", "pipeline"):
            continue                      # a person owns this row; it is not stale
        if props.get("decision") == "superseded":
            continue                      # already reconciled by an earlier run
        superseded += 1
        nodes.append(NodeApply(space=space, external_id=xid,
            sources=[NodeOrEdgeData(source=sug_view, properties={
                "runId": run_id,
                "decision": "superseded",
                "decidedBy": "pipeline",
                "decidedTime": _ts(now),
                "evidenceText": f"run {run_id} no longer produces this pair",
            })]))

    nodes = [n for n in nodes if n is not None]

    # Counts are read off the decisions actually recorded, never off a parallel
    # tally kept by hand -- a hand-kept tally is a second source of truth that
    # disagrees with the first the moment anyone edits this function.
    def _count(value):
        return sum(1 for n in nodes
                   if n.sources[0].properties.get("decision") == value)

    nodes.append(NodeApply(
        space=space, external_id=run_id,
        sources=[NodeOrEdgeData(source=run_view, properties={
            "name": f"{technique} {run_id}",
            "runId": run_id,
            "technique": technique,
            "status": "completed",
            # The rule set is identified by a hash of its CONTENT, not by its row
            # count. A count is the obvious choice and it is wrong: editing a rule --
            # the single most common change -- leaves the count identical, so the
            # version says nothing changed while the results say otherwise. Measured
            # exactly that way before this was fixed.
            "rulesVersion": _rules_version(rules),
            "startedTime": _ts(started),
            "completedTime": _ts(now),
            "scannedCount": len(resolved) + len(below) + len(unresolved),
            "appliedCount": _count("auto-applied"),
            "reviewCount": _count("needs-review"),
            "rejectedCount": _count("rejected") + _count("rejected-by-human"),
            "unresolvedCount": _count("unresolved"),
            # Links actually taken off file.assets -- not suggestions marked
            # superseded. The alert is about data that changed, not bookkeeping.
            "staleRemovedCount": retracted,
            "supersededCount": superseded,
            "failedCount": 0,
            "workflowExecutionId": workflow_execution,
        })]))

    client.data_modeling.instances.apply(nodes=nodes, auto_create_direct_relations=False)
    return len(nodes) - 1


def _retractions(prior: dict, resolved: dict) -> list[tuple]:
    """Links that must be **removed** from file.assets, as (source, target) pairs.

    Applying a link is only half a pipeline. Two things have to un-apply it, and a
    system that does neither quietly accumulates links nobody can justify:

    * **A person rejected the pair.** Their decision is the whole point of a review
      queue. Recording the rejection and leaving the link in place means the reviewer
      does the work, the record says "rejected", and Fusion still shows the bad link.
    * **We applied it and no longer produce it.** Somebody edited a rule or a source
      system renamed something. Silence is not agreement -- see Chapter 17 section 17.1c.

    Note the asymmetry in what each case is allowed to touch. A *person's* rejection
    retracts the link whoever created it: they looked at this exact pair and said no.
    A *pipeline* retraction only removes what the pipeline itself applied -- which is
    knowable only because the suggestion recorded `decidedBy`. Without that record the
    safe implementation is to remove nothing, and the links accumulate forever.
    """
    produced = {f"{src}|{info['target']}" for src, info in resolved.items()}
    out = []
    for props in prior.values():
        source = props.get("sourceExternalId")
        target = props.get("targetExternalId")
        if not source or not target:
            continue
        decided_by = props.get("decidedBy")
        decision = props.get("decision")
        by_human = decided_by not in (None, "", "pipeline")
        if by_human and decision == "rejected":
            out.append((source, target))
        elif (not by_human and decision == "auto-applied"
              and f"{source}|{target}" not in produced):
            out.append((source, target))
    return out


def _write_and_report(client, space, v_file, files, resolved, matches, below, rules,
                      *, model_used: bool, retract=None, unresolved=()) -> dict:
    """One write path for all three rungs, so a rule-matched file is applied exactly
    the same way an entity-matched one is -- and one retraction path, so a link can
    come off again."""
    retract = retract or []
    # Group by file: a single read-modify-write per node, never one per pair, or the
    # second write of the pair silently reinstates what the first removed.
    drop: dict[str, set] = {}
    for src_id, tgt_id in retract:
        drop.setdefault(src_id, set()).add(tgt_id)

    retracted = 0
    applies: list[NodeApply] = []
    for src_id, info in resolved.items():
        tgt_id = info["target"]
        matches.append({"source": src_id, "target": tgt_id, "resolvedBy": info["how"],
                        **({"score": info["score"]} if "score" in info else {})})

        # read-modify-write: never clobber assets somebody else put on this file
        existing = next((f for f in files if f.external_id == src_id), None)
        existing_assets = []
        if existing is not None:
            props = existing.properties.get(v_file, {})
            for rel in props.get("assets") or []:
                if hasattr(rel, "external_id"):
                    existing_assets.append(DirectRelationReference(rel.space, rel.external_id))
                elif isinstance(rel, dict):
                    existing_assets.append(
                        DirectRelationReference(rel.get("space", space), rel["externalId"])
                    )
        # Anything retracted for this file comes off in the same write that adds it,
        # never in a second write -- two writes to one node and the later one wins.
        kept = [a for a in existing_assets
                if getattr(a, "external_id", None) not in drop.get(src_id, ())]
        retracted += len(existing_assets) - len(kept)
        existing_assets = kept
        if not any(getattr(a, "external_id", None) == tgt_id for a in existing_assets):
            existing_assets.append(DirectRelationReference(space, tgt_id))
        applies.append(
            NodeApply(
                space=space,
                external_id=src_id,
                sources=[NodeOrEdgeData(source=v_file, properties={"assets": existing_assets})],
            )
        )

    # Files with nothing to add this run but something to take away still need writing.
    for src_id, targets in drop.items():
        if src_id in resolved:
            continue                      # already handled in the loop above
        existing = next((f for f in files if f.external_id == src_id), None)
        if existing is None:
            continue
        keep = []
        for rel in existing.properties.get(v_file, {}).get("assets") or []:
            xid = rel.external_id if hasattr(rel, "external_id") else rel.get("externalId")
            rel_space = rel.space if hasattr(rel, "space") else rel.get("space", space)
            if xid in targets:
                retracted += 1
                continue
            keep.append(DirectRelationReference(rel_space, xid))
        applies.append(
            NodeApply(
                space=space,
                external_id=src_id,
                sources=[NodeOrEdgeData(source=v_file, properties={"assets": keep})],
            )
        )

    if applies:
        client.data_modeling.instances.apply(nodes=applies)

    by_rung: dict[str, int] = {}
    for info in resolved.values():
        by_rung[info["how"]] = by_rung.get(info["how"], 0) + 1

    return {
        "matches": matches,
        "below_threshold": below,
        "resolved_by": by_rung,          # how much each rung actually did
        "rules_loaded": len(rules),
        "entity_matching_used": model_used,
        "links_retracted": retracted,
        # An honest result says what it did *not* do. A caller that only ever sees
        # `matches` has no way to tell "nothing was left over" from "nothing ran".
        "unresolved_count": len(unresolved),
    }
```

### Line-by-line walkthrough

| Code | What it does | Why it is written this way |
|---|---|---|
| `AUTO_APPLY_AT = 0.80` / `REVIEW_AT = 0.45` | Three bands, not one threshold | A single cut-off forces every uncertain match into one of two wrong answers — apply it silently, or throw it away with no trace. The middle band is where contextualization actually lives |
| `TAG_IN_FILENAME = re.compile(r"\b(\d{2}-[A-Z]{2}-\d{4}[A-Z]?)\b")` | Rung 2: finds a tag like `21-PA-2001A` anywhere in a file name | Mirrors the site tag convention *area–type–number–suffix*. The trailing `[A-Z]?` catches the `A`/`B` that distinguishes duty and standby pumps; the `\b` anchors stop it matching inside a longer number |
| `_load_mapping_rules(client, raw_db, table)` | Rung 1: reads the rules out of a RAW table | **Rules are data, not code.** An engineer corrects a bad match by editing a row — no code change, no deploy, no Python. That is the whole argument for section 7.2 |
| `except Exception: return []` in `_load_mapping_rules` | An absent rule table yields no rules | A missing table is a *valid state*, not an error — somebody who has not created it yet must still get a working cascade |
| `sorted(rules, key=lambda r: r["matchType"] != "exact")` | Exact rules are tried before regex rules | Order in the table is policy. An exact rule is a person naming one specific pair; a regex is a generalisation. The specific statement wins |
| `except re.error: continue` | A malformed regex in a data row is skipped, not fatal | The moment you let humans edit rules, one of those rules will be `(unclosed`. One bad row must not take the pipeline down |
| `def handle(client, ...)` | Entry point — must be named `handle` | `client` arrives **already authenticated** as the Function's own identity. Never construct a `CogniteClient` inside a Function. [Functions](https://docs.cognite.com/cdf/functions/) |
| `os.environ["PARTICIPANT"]` / `["INSTANCE_SPACE"]` | Reads your name and space | Injected via `envVars` in the `.Function.yaml` below. This is precisely why the Python is byte-identical for 15 people |
| `run_id = data.get("runId") or f"ctxrun-..."` | One correlation ID for everything this run writes | A caller — a Workflow — can pass its own, so every record from one execution carries the same ID. Generate one when nobody does, so a hand-call is still traceable |
| `prior = _existing_decisions(...)` | Loads every existing suggestion **before** doing any work | It drives both re-run rules: a person's decision outranks the machine's, and a pair a previous run made and this one does not is stale, not absent ([Chapter 17](17-cross-cutting-mastery.md) section 17.1c) |
| `model_xid = f"emp_{participant}_..."` | Names the EM model with **your** name | EM models are project-global, so unlike a view or container this one **must** be name-scoped or it collides with the rest of the cohort |
| `retrieve_nodes(nodes=[...], sources=[v_file])` | Fetches your two PDF nodes | `sources=` asks for properties *as seen through* the `CogniteFile` view. Without it you get the node but not its typed properties. [Data modeling](https://docs.cognite.com/cdf/dm/) |
| `instances.list(..., space=space, limit=-1)` | Fetches all your assets as match candidates | `space=space` is the isolation boundary — you can only ever match against your own 8 assets. `limit=-1` means "all" |
| `if target is not None and target not in asset_ids` | A rule naming an asset that does not exist resolves to nothing | Never trust a data row blindly. A typo in a rule would otherwise write a dangling relation that looks exactly like a real one |
| `human_decisions.get(f"{f.external_id}\|{target}") == "rejected"` | A vetoed pair is dropped on the **rule** rung too | A rule is not more authoritative than a person who looked at the link and said no; it is only cheaper. Applying this to the model's output alone is the bug that re-applies every rejection nightly |
| `vetoed.add(f.external_id)` | A vetoed file never reaches Entity Matching | Escalating to a paid rung to re-propose something a person already rejected is the worst of both outcomes |
| `if not sources:` → early return | When rules and regex resolve everything, EM never runs | Fitting a model on an empty source list is exactly the waste the cascade exists to avoid. On this lab's two PDFs this is the path you take |
| `client.entity_matching.fit(...)` | Trains a model on name→name similarity | `feature_type="bigram"` compares two-character sequences, so it tolerates punctuation and spacing differences that exact matching would fail on |
| `model.wait_for_completion(timeout=600)` | Blocks until the job finishes, with a bound | The SDK's own wait. A hand-rolled polling loop is what produced the bug in the ⚠️ below — "completed with zero matches, no error" |
| `predict.get_result()` | A **method**, not a `.result` property | `getattr(predict, "result", None)` returns `None` and you get zero matches with no error at all. This one cost an afternoon |
| `band = _band(score)` then `if band != "auto-applied"` | Low-confidence matches are **recorded but never written** | Auto-applying a bad match is worse than applying nothing — a wrong link is silently believed by every downstream consumer. Recording it is what makes a review queue possible |
| `_retractions(prior, resolved)` | Works out which links must come **off** | Applying is only half a pipeline. A rejected pair and a pair we no longer produce both have to un-apply, or the graph accumulates links nobody can justify |
| `_write_and_report(..., retract=...)` | One write path for all three rungs, and one retraction path | A rule-matched file is applied exactly the same way an entity-matched one is. Additions and removals for a file go in **one** write. Two `NodeApply` entries for the same node in one call are rejected outright (`Duplicate node externalIds ... | code: 400`), and across two calls the second write **replaces** the list rather than merging into it — so a split write would silently reinstate what the first removed |
| `_write_spine(...)` | Persists the run and every suggestion | `file.assets` says a link exists. These records say which rung made it, on what evidence, how confident it was, and who signed it off |
| `client.entity_matching.delete(...)` in `try/except` × 3 | Deletes the model on **every** exit path | Success, fit failure, predict failure. `except: pass` on the pre-emptive delete because "it was not there" is the expected case, not an error |
| `result["model_delete_warning"]` | Surfaces a failed cleanup instead of hiding it | If deletion fails you **must** know — you now own a global object that collides with the rest of the cohort |
| `return {...}` | Counts and lists, JSON-serializable | This dict is what appears in the Function's call-result log. Note it reports `below_threshold`, `unresolved_count` and `links_retracted` too — an honest result says what it did *not* do, and what it undid |

📚 `[DOCS]` [Cognite Functions](https://docs.cognite.com/cdf/functions/) ·
[Entity matching](https://docs.cognite.com/cdf/integration/guides/contextualization/match_entities) ·
[Data modeling](https://docs.cognite.com/cdf/dm/)

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/04_compute/functions/fnc_<YOURNAME>_Training_MatchDocuments/requirements.txt`

```
cognite-sdk==8.10.0
```

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/04_compute/functions/MatchDocuments.Function.yaml`

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
  # Rung 1 of the cascade reads its mapping rules from RAW.
  RAW_DB: "rwd_<YOURNAME>_Training_TRN"
```

🔧 `[CHANGE]` `handler.py` is **byte-identical** for every participant — same
argument as containers/views in section 1.2. Only `Function.yaml`'s `externalId`, `name`,
and `envVars` values carry `YOURNAME`.

💡 `[GOOD TO KNOW]` — **notebook vs. Function, concretely.** The notebook runs the three
techniques *side by side* so you can compare them; the Function composes them into one
production **cascade** (manual override → regex → EM-on-miss → threshold gate). Other
differences: no interactive login (the Function runs under its own managed identity), no
hardcoded space string (it reads `INSTANCE_SPACE` from `envVars`), a hard 300-second
poll deadline on the EM path instead of "just wait and see," and it returns a
JSON-serializable dict instead of printing — that dict (`matches`, `below_threshold`,
`resolved_by`, `rules_loaded`, `entity_matching_used`, `links_retracted`, `run_id`,
`suggestions_recorded`) is what shows up in the Function's call-result log
([Chapter 17](17-cross-cutting-mastery.md)).

💡 `[GOOD TO KNOW]` Those key names are checked against the handler by
`tools/check_docs.py`. A chapter that documents a field the code stopped returning is
worse than one that documents nothing — the learner trusts it, gets `None`, and blames
their own code.

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

✅ `[VERIFY]` On this lab's two PDFs **rung 1 resolves both** — the mapping rules in RAW
name them explicitly (section 7.2) — so the response should show:

```json
{
  "matches": [
    {"source": "file_<YOURNAME>_TRN_PID_21_SEP",     "target": "TRN-21-SEP",  "resolvedBy": "rule", "score": 1.0},
    {"source": "file_<YOURNAME>_TRN_DS_21_PA_2001A", "target": "21-PA-2001A", "resolvedBy": "rule", "score": 1.0}
  ],
  "below_threshold": [],
  "resolved_by": {"rule": 2},
  "rules_loaded": 2,
  "entity_matching_used": false,
  "links_retracted": 0,
  "run_id": "ctxrun-...-matchdocuments",
  "suggestions_recorded": 2
}
```

`resolvedBy` is `"rule"`, not `"regex"` — the regex rung exists for files the rules do
*not* name, and on this lab's two files it never fires. **`entity_matching_used: false`**:
no entity-matching model is created or deleted on this call. Then open both files in Fusion and confirm the `assets` relation
(`TRN-21-SEP`, `21-PA-2001A`). *Files linked correctly* is the success criterion —
**not** "EM scored them." You saw `fit`/`predict` run for real in the notebook (section 7.6);
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

🚧 `[LIMITS]` **The rung you exercise least is the rung that breaks.**

A cascade is *designed* so the expensive rung is rare. On this lab's two documents the
mapping rules resolve everything, so rung 3 never runs — which means it is also the
least-exercised code in the pipeline, by construction rather than by neglect.

That is not hypothetical here. This handler shipped with a crash on the entity-matching
path: a loop variable shadowed the dict of existing suggestions, so the first model result
turned it into a string and the retraction step died on it.

```
AttributeError: 'NoneType' object has no attribute 'values'
```

Every test passed. Every live run was green. The bug was found only by deliberately
breaking a mapping rule for the [Chapter 17](17-cross-cutting-mastery.md) section 17.8
capstone, which is the first thing in the whole course that forces the cascade down to
rung 3.

⚠️ `[COMMON MISTAKE]` Reading "the fallback rarely runs" as reassurance. It is the
opposite. Rarely-run code is code whose failures are discovered by your users, on the day
the common path stops working — which is precisely the day you most need the fallback.
Write a test that forces each rung, and if you cannot force a rung from a test, that is
itself the finding.

---

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
  **rule** path (the call returned `resolved_by: {"rule": 2}` and
  `entity_matching_used: false`)
- The entity-matching model is confirmed deleted after the **notebook** run; and you've
  confirmed the **Function** call created **no** model (regex resolved both files, so
  there was nothing to clean up)
- You can explain when you'd reach for each of the three techniques — and why a normal
  Function call returns `entity_matching_used: false` while the notebook's EM cell
  runs a real `fit`/`predict`
- The acceptance contract passes for this capability: `uv run python tools/acceptance.py <YOURNAME> contextualization` ([Chapter 17](17-cross-cutting-mastery.md) section 17.2c)
- 📓 You have added your two or three lines for this chapter to `participants/<YOURNAME>/NOTES.md` — **now**, not tonight

→ [Chapter 08 — Diagram Annotation](08-diagram-annotation.md)
