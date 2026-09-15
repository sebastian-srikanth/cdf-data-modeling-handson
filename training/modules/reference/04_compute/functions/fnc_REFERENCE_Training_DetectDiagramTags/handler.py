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
