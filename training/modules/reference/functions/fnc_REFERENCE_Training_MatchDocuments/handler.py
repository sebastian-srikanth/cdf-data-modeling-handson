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
        prior = human_decisions.get(f"{src_id}|{tgt_id}")
        if prior == "rejected":
            below.append({**row, "decision": "rejected-by-human"})
            continue
        if prior == "approved":
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
            # The rule set is identified by its row count, so a results change can be
            # attributed to a rules change rather than argued about.
            "rulesVersion": f"rules:{len(rules)}",
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
