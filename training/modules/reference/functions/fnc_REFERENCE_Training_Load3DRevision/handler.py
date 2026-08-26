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

TAG_MAP = {
    "21-VG-2001": "21-VG-2001",
    "21-PA-2001A": "21-PA-2001A",
    "21-PA-2001B": "21-PA-2001B",
    "21-HA-2001": "21-HA-2001",
    "21-XV-2001": "21-XV-2001",
    "DECK": "TRN-21-SEP",
}


def _project(client) -> str:
    return client.config.project


def _ensure_dms_cad_model(client, model_name: str, space: str) -> SimpleNamespace:
    """Create/find the CAD model shell via DMS 3D API (space + type)."""
    base = f"/api/v1/projects/{_project(client)}/3d/models"
    cursor = None
    while True:
        params: dict = {"limit": 1000}
        if cursor:
            params["cursor"] = cursor
        payload = client.get(base, params=params).json()
        for item in payload.get("items") or []:
            if item.get("name") == model_name:
                return SimpleNamespace(id=item["id"], name=item.get("name"), raw=item)
        cursor = payload.get("nextCursor")
        if not cursor:
            break

    response = client.post(
        base,
        json={"items": [{"name": model_name, "space": space, "type": "CAD"}]},
    )
    model_id = response.json()["items"][0]["id"]
    return SimpleNamespace(id=model_id, name=model_name, raw=response.json()["items"][0])


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


def _publish_revision(client, model_id: int, revision_id: int, space: str) -> dict:
    """Mark revision published so Fusion 3D UI shows it to end users.

    On DMS/space-scoped models the update body requires ``instanceId`` of the
    auto node ``cog_3d_revision_{revisionId}`` (classic ``id``-only update 400s).
    """
    body = {
        "items": [
            {
                "id": revision_id,
                "instanceId": {
                    "space": space,
                    "externalId": f"cog_3d_revision_{revision_id}",
                },
                "update": {"published": {"set": True}},
            }
        ]
    }
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


def _bbox_props(node: dict) -> dict[str, float]:
    bbox = node.get("boundingBox") or {}
    mins = bbox.get("min") or [0.0, 0.0, 0.0]
    maxs = bbox.get("max") or [1.0, 1.0, 1.0]
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
    model_name = f"trd_{participant}_TRN_CAD"
    file_xid = f"file_{participant}_TRN_3D_21_SEP"

    model = _ensure_dms_cad_model(client, model_name, space)

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
            revision = _publish_revision(client, model.id, revision_id, space)
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

    mapped: dict[str, str] = {}
    unmapped: list[str] = []
    for cad_name, asset_xid in TAG_MAP.items():
        node = by_name.get(cad_name)
        if node is None:
            unmapped.append(cad_name)
            continue
        obj_xid = f"obj3d_{cad_name}"
        cad_xid = f"cadnode_{cad_name}"
        bbox = _bbox_props(node)

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
        "cad_model": cad_model_xid,
        "cad_revision": cad_rev_xid,
    }
