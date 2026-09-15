"""Upload a 3D revision and map CAD node names to CogniteAsset.object3D.

Uses raw HTTP for DMS 3D model/revision/node APIs. The classic SDK loaders
expect fields like ``assetMappingCount`` that Data-Modeling-only projects omit.
"""

from __future__ import annotations

import os
import time
from types import SimpleNamespace

from cognite.client.data_classes.data_modeling import (
    DirectRelationReference,
    NodeApply,
    NodeOrEdgeData,
    ViewId,
)

# Fallback only. The real mapping lives in RAW -- see _load_3d_mappings below and
# Chapter 09 section 9.2b. This dict is what the Function uses if the table is absent,
# so a participant who has not created it yet still gets a working revision.
TAG_MAP = {
    "21-VG-2001": "21-VG-2001",
    "21-PA-2001A": "21-PA-2001A",
    "21-PA-2001B": "21-PA-2001B",
    "21-HA-2001": "21-HA-2001",
    "21-XV-2001": "21-XV-2001",
    "DECK": "TRN-21-SEP",
}


def _load_3d_mappings(client, raw_db: str) -> dict[str, str]:
    """CAD node name -> asset externalId, from RAW.

    A 3D model is delivered by whoever built it, and their naming is not your naming.
    Most nodes match their tag exactly; a few never will, because a modeller called the
    structure DECK. Those exceptions are data, not code -- the person who knows that DECK
    is the separation train is rarely the person who can deploy a Function.
    """
    try:
        rows = client.raw.rows.list(
            db_name=raw_db, table_name="rwt_Training_TRN_Model3DMappings", limit=-1)
    except Exception:  # noqa: BLE001 - absent table means "use the built-in fallback"
        return {}
    mappings = {}
    for row in rows:
        c = row.columns or {}
        node = (c.get("cadNodeName") or "").strip()
        asset = (c.get("assetExternalId") or "").strip()
        if node and asset:
            mappings[node] = asset
    return mappings


def _project(client) -> str:
    return client.config.project


def _ensure_cad_model(client, model_name: str, space: str) -> SimpleNamespace:
    """Create or find the CAD model shell.

    The /3d/models create payload is PROJECT-DEPENDENT and there is no capability
    flag to ask about it in advance:

      * a DMS-enabled 3D project REQUIRES {"name", "space", "type"}
      * a classic 3D project REJECTS space outright, with
        `CogniteAPIError: space is not supported | code: 400`

    So we try the DMS shape first and fall back to classic. `flavour` is carried
    forward because publishing a revision differs the same way (see
    _publish_revision).
    """
    base = f"/api/v1/projects/{_project(client)}/3d/models"
    cursor = None
    while True:
        params: dict = {"limit": 1000}
        if cursor:
            params["cursor"] = cursor
        payload = client.get(base, params=params).json()
        for item in payload.get("items") or []:
            if item.get("name") == model_name:
                flavour = "dms" if item.get("space") else "classic"
                return SimpleNamespace(id=item["id"], name=item.get("name"),
                                       raw=item, flavour=flavour)
        cursor = payload.get("nextCursor")
        if not cursor:
            break

    attempts = (
        ("dms", {"name": model_name, "space": space, "type": "CAD"}),
        ("classic", {"name": model_name}),
    )
    last_error: Exception | None = None
    for flavour, item in attempts:
        try:
            response = client.post(base, json={"items": [item]})
        except Exception as exc:              # CogniteAPIError, but keep the handler import-light
            last_error = exc
            if "space is not supported" in str(exc):
                continue                      # classic project: try the next shape
            raise
        created = response.json()["items"][0]
        return SimpleNamespace(id=created["id"], name=model_name,
                               raw=created, flavour=flavour)
    raise RuntimeError(f"could not create 3D model {model_name!r}: {last_error}")


def _list_revisions(client, model_id: int) -> list[dict]:
    base = f"/api/v1/projects/{_project(client)}/3d/models/{model_id}/revisions"
    items: list[dict] = []
    cursor = None
    while True:
        params: dict = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        payload = client.get(base, params=params).json()
        items.extend(payload.get("items") or [])
        cursor = payload.get("nextCursor")
        if not cursor:
            break
    return items


def _get_revision(client, model_id: int, revision_id: int) -> dict:
    base = f"/api/v1/projects/{_project(client)}/3d/models/{model_id}/revisions/{revision_id}"
    return client.get(base).json()


def _publish_revision(client, model_id: int, revision_id: int, space: str,
                     flavour: str = "dms") -> dict:
    """Mark the revision published so the Fusion 3D UI shows it.

    Same project split as _ensure_cad_model: a DMS model needs the ``instanceId``
    of the auto-created node ``cog_3d_revision_{revisionId}``; a classic model
    takes ``id`` alone and 400s if you send instanceId.
    """
    item: dict = {"id": revision_id, "update": {"published": {"set": True}}}
    if flavour == "dms":
        item["instanceId"] = {
            "space": space,
            "externalId": f"cog_3d_revision_{revision_id}",
        }
    body = {"items": [item]}
    response = client.post(
        f"/api/v1/projects/{_project(client)}/3d/models/{model_id}/revisions/update",
        json=body,
    )
    return response.json()["items"][0]


def _create_revision(client, model_id: int, file_id: int) -> dict:
    session = client.iam.sessions.create()
    response = client.post(
        f"/api/v1/projects/{_project(client)}/3d/models/{model_id}/revisions",
        json={
            "items": [
                {
                    "fileId": file_id,
                    "published": True,
                    "nonce": session.nonce,
                }
            ]
        },
    )
    return response.json()["items"][0]


def _list_nodes(client, model_id: int, revision_id: int) -> list[dict]:
    base = (
        f"/api/v1/projects/{_project(client)}/3d/models/{model_id}"
        f"/revisions/{revision_id}/nodes"
    )
    items: list[dict] = []
    cursor = None
    while True:
        params: dict = {"limit": 1000}
        if cursor:
            params["cursor"] = cursor
        payload = client.get(base, params=params).json()
        items.extend(payload.get("items") or [])
        cursor = payload.get("nextCursor")
        if not cursor:
            break
    return items


def _bbox_props(node: dict):
    """Six flat floats from the API's nested boundingBox -- or None if it has none.

    **None, not a unit cube.** This used to default to 0,0,0-1,1,1 when the node carried
    no geometry, which writes a one-metre box at the model origin and calls it the pump.
    Nothing errors. Fusion renders it. Anyone measuring clearances off that model is
    measuring a number this function invented.

    A CAD node with no geometry is a finding to report, not a gap to fill.
    """
    bbox = node.get("boundingBox") or {}
    mins = bbox.get("min")
    maxs = bbox.get("max")
    if not mins or not maxs or len(mins) < 3 or len(maxs) < 3:
        return None
    return {
        "xMin": float(mins[0]),
        "yMin": float(mins[1]),
        "zMin": float(mins[2]),
        "xMax": float(maxs[0]),
        "yMax": float(maxs[1]),
        "zMax": float(maxs[2]),
    }


def handle(client, data=None, secrets=None, function_call_info=None) -> dict:
    participant = os.environ["PARTICIPANT"]
    space = os.environ["INSTANCE_SPACE"]
    raw_db = os.environ.get("RAW_DB", f"rwd_{os.environ['PARTICIPANT']}_Training_TRN")
    model_name = f"trd_{participant}_TRN_CAD"
    file_xid = f"file_{participant}_TRN_3D_21_SEP"

    model = _ensure_cad_model(client, model_name, space)

    revisions = _list_revisions(client, model.id)
    revision = revisions[0] if revisions else None
    if revision is None:
        src = client.files.retrieve(external_id=file_xid)
        if src is None or not src.uploaded:
            return {"error": "OBJ classic file missing or not uploaded", "file": file_xid}
        revision = _create_revision(client, model.id, src.id)

    revision_id = revision["id"]
    deadline = time.time() + 20 * 60
    status = revision.get("status")
    while status in ("Queued", "Processing") and time.time() < deadline:
        time.sleep(15)
        revision = _get_revision(client, model.id, revision_id)
        status = revision.get("status")

    if status == "Failed":
        return {
            "status": "Failed",
            "model_id": model.id,
            "revision_id": revision_id,
            "resume": False,
        }
    if status != "Done":
        return {
            "status": status,
            "model_id": model.id,
            "revision_id": revision_id,
            "resume": True,
        }

    # Create-with-published:true is ignored on this project type; publish after Done.
    if not revision.get("published"):
        try:
            revision = _publish_revision(client, model.id, revision_id, space, model.flavour)
        except Exception as exc:  # noqa: BLE001 — still map nodes even if publish fails
            return {
                "status": status,
                "model_id": model.id,
                "revision_id": revision_id,
                "published": False,
                "publish_error": str(exc),
                "resume": False,
            }

    nodes = _list_nodes(client, model.id, revision_id)
    # Prefer leaf nodes when the OBJ exports duplicate names (group + leaf).
    by_name: dict[str, dict] = {}
    for n in nodes:
        name = n.get("name")
        if not name:
            continue
        prev = by_name.get(name)
        if prev is None or int(n.get("subtreeSize") or 1) < int(prev.get("subtreeSize") or 1):
            by_name[name] = n

    # Classic/DMS 3D API creates shells as cog_3d_model_{id} / cog_3d_revision_{id}.
    # Fusion asset 3D preview resolves:
    #   Asset.object3D → Cognite3DObject ← CogniteCADNode
    #   CogniteCADNode.revisions → cog_3d_revision_{revisionId} with matching treeIndexes.
    #
    # Do NOT write Cognite3DModel onto the revision node — Fusion's 3D model list
    # treats every Cognite3DModel instance as a separate model (fake duplicates).
    cad_model_xid = f"cog_3d_model_{model.id}"
    cad_rev_xid = f"cog_3d_revision_{revision_id}"
    v_model = ViewId("cdf_cdm", "Cognite3DModel", "v1")
    v_rev3d = ViewId("cdf_cdm", "Cognite3DRevision", "v1")
    v_rev = ViewId("cdf_cdm", "CogniteCADRevision", "v1")
    v_obj = ViewId("cdf_cdm", "Cognite3DObject", "v1")
    v_node = ViewId("cdf_cdm", "CogniteCADNode", "v1")
    v_asset = ViewId("cdf_cdm", "CogniteAsset", "v1")

    applies: list[NodeApply] = [
        NodeApply(
            space=space,
            external_id=cad_model_xid,
            sources=[
                NodeOrEdgeData(
                    source=v_model,
                    properties={"name": model_name, "type": "CAD"},
                )
            ],
        ),
        NodeApply(
            space=space,
            external_id=cad_rev_xid,
            sources=[
                NodeOrEdgeData(
                    source=v_rev3d,
                    properties={
                        "model3D": DirectRelationReference(space, cad_model_xid),
                        "status": status,
                        "published": True,
                        "type": "CAD",
                    },
                ),
                NodeOrEdgeData(
                    source=v_rev,
                    properties={"revisionId": revision_id},
                ),
            ],
        ),
    ]

    # Technique 1: the mapping table in RAW. Technique 2 (name equality) is what most
    # rows in that table record; the built-in TAG_MAP is only a fallback for someone who
    # has not created the table yet. See Chapter 09 section 9.2b.
    tag_map = _load_3d_mappings(client, raw_db) or TAG_MAP
    mapping_source = "raw" if _load_3d_mappings(client, raw_db) else "built-in fallback"

    mapped: dict[str, str] = {}
    unmapped: list[str] = []
    no_geometry: list[str] = []   # named in the mapping, but the revision has no shape
    for cad_name, asset_xid in tag_map.items():
        node = by_name.get(cad_name)
        if node is None:
            unmapped.append(cad_name)
            continue
        obj_xid = f"obj3d_{cad_name}"
        cad_xid = f"cadnode_{cad_name}"
        bbox = _bbox_props(node)
        if bbox is None:
            # Mapped by name, but the revision carries no geometry for it. Report it;
            # do not invent a box and do not link the asset to a shape that is not there.
            no_geometry.append(cad_name)
            continue

        applies.append(
            NodeApply(
                space=space,
                external_id=obj_xid,
                sources=[NodeOrEdgeData(source=v_obj, properties={"name": cad_name, **bbox})],
            )
        )
        applies.append(
            NodeApply(
                space=space,
                external_id=cad_xid,
                sources=[
                    NodeOrEdgeData(
                        source=v_node,
                        properties={
                            "name": cad_name,
                            "object3D": DirectRelationReference(space, obj_xid),
                            "model3D": DirectRelationReference(space, cad_model_xid),
                            "revisions": [DirectRelationReference(space, cad_rev_xid)],
                            "treeIndexes": [int(node.get("treeIndex") or 0)],
                            "subTreeSizes": [int(node.get("subtreeSize") or 1)],
                        },
                    )
                ],
            )
        )
        applies.append(
            NodeApply(
                space=space,
                external_id=asset_xid,
                sources=[
                    NodeOrEdgeData(
                        source=v_asset,
                        properties={"object3D": DirectRelationReference(space, obj_xid)},
                    )
                ],
            )
        )
        mapped[cad_name] = asset_xid

    client.data_modeling.instances.apply(nodes=applies)
    return {
        "model_id": model.id,
        "revision_id": revision_id,
        "status": status,
        "published": bool(revision.get("published")),
        "mapped": mapped,
        "unmapped": unmapped,
        "no_geometry": no_geometry,
        "mapping_source": mapping_source,
        # CAD nodes present in the model that no rule claims. This is the triage list:
        # every one is either a real asset nobody tagged, or scaffolding you can ignore.
        "cad_nodes_unclaimed": sorted(set(by_name) - set(tag_map)),
        "cad_model": cad_model_xid,
        "cad_revision": cad_rev_xid,
    }
