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

SCORE_THRESHOLD = 0.5


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


def handle(client, data=None, secrets=None, function_call_info=None) -> dict:
    participant = os.environ["PARTICIPANT"]
    space = os.environ["INSTANCE_SPACE"]
    raw_db = os.environ.get("RAW_DB", f"rwd_{participant}_Training_TRN")
    model_xid = f"emp_{participant}_Datasheet_TRN"

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

        if target is None:
            unresolved.append(f)
        else:
            resolved[f.external_id] = {"target": target, "how": how}

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
    below: list[dict] = []
    model = None

    # If rules and regex resolved everything, there is nothing to fit a model on -- and
    # fitting one anyway is exactly the waste this cascade exists to avoid.
    if not sources:
        return _write_and_report(
            client, space, v_file, files, resolved, matches, below, rules, model_used=False
        )

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
        if score < SCORE_THRESHOLD:
            below.append(row)          # never written; surfaced for a human to review
            continue
        resolved[src_id] = {"target": tgt_id, "how": "entity-matching", "score": score}

    result = _write_and_report(
        client, space, v_file, files, resolved, matches, below, rules, model_used=True
    )

    try:
        client.entity_matching.delete(id=model.id)
    except Exception as exc:  # noqa: BLE001 - cleanup is best-effort
        result["model_delete_warning"] = str(exc)
    return result


def _write_and_report(client, space, v_file, files, resolved, matches, below, rules,
                      *, model_used: bool) -> dict:
    """One write path for all three rungs, so a rule-matched file is applied exactly
    the same way an entity-matched one is."""
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
        if not any(getattr(a, "external_id", None) == tgt_id for a in existing_assets):
            existing_assets.append(DirectRelationReference(space, tgt_id))
        applies.append(
            NodeApply(
                space=space,
                external_id=src_id,
                sources=[NodeOrEdgeData(source=v_file, properties={"assets": existing_assets})],
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
    }
