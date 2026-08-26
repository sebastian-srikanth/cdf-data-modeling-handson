"""Entity-match PDF CogniteFile nodes to CogniteAsset nodes; delete the model afterwards."""

from __future__ import annotations

import os
import time

from cognite.client.data_classes.data_modeling import (
    DirectRelationReference,
    NodeApply,
    NodeOrEdgeData,
    ViewId,
)


def handle(client, data=None, secrets=None, function_call_info=None) -> dict:
    participant = os.environ["PARTICIPANT"]
    space = os.environ["INSTANCE_SPACE"]
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

    sources = []
    for f in files:
        props = f.properties.get(v_file, {})
        sources.append({"id": f.external_id, "name": props.get("name") or f.external_id})

    targets = []
    for a in assets:
        props = a.properties.get(v_asset, {})
        targets.append({"id": a.external_id, "name": props.get("name") or a.external_id})

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
    # wait for fit
    deadline = time.time() + 300
    while getattr(model, "status", "Completed") not in ("Completed", "Failed") and time.time() < deadline:
        time.sleep(5)
        model = client.entity_matching.retrieve(id=model.id)

    if getattr(model, "status", None) == "Failed":
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
    while getattr(predict, "status", "Completed") not in ("Completed", "Failed") and time.time() < deadline:
        time.sleep(5)
        predict = client.entity_matching.retrieve_predict_job(id=predict.job_id) if hasattr(client.entity_matching, "retrieve_predict_job") else predict

    matches: list[dict] = []
    below: list[dict] = []
    result_items = getattr(predict, "result", None) or getattr(predict, "matches", None) or []
    if isinstance(result_items, dict):
        result_items = result_items.get("items") or []

    applies: list[NodeApply] = []
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
        if score < 0.5:
            below.append(row)
            continue
        matches.append(row)

        # read-modify-write assets on the file node
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
                sources=[
                    NodeOrEdgeData(
                        source=v_file,
                        properties={"assets": existing_assets},
                    )
                ],
            )
        )

    if applies:
        client.data_modeling.instances.apply(nodes=applies)

    try:
        client.entity_matching.delete(id=model.id)
    except Exception as exc:  # noqa: BLE001 — cleanup best-effort
        return {
            "matches": matches,
            "below_threshold": below,
            "model_delete_warning": str(exc),
        }

    return {"matches": matches, "below_threshold": below}
