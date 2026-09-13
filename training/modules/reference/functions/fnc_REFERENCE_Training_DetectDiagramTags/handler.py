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
