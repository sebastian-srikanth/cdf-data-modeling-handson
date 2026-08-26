"""Parse the pump datasheet PDF into viw_EquipmentHealthProfile_sdm."""

from __future__ import annotations

import io
import os
import re
from datetime import datetime, timezone

from cognite.client.data_classes.data_modeling import (
    DirectRelationReference,
    NodeApply,
    NodeId,
    NodeOrEdgeData,
    ViewId,
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


def handle(client, data=None, secrets=None, function_call_info=None) -> dict:
    participant = os.environ["PARTICIPANT"]
    space = os.environ["INSTANCE_SPACE"]
    schema_edm = os.environ["SCHEMA_SPACE_EDM"]
    schema_sdm = os.environ["SCHEMA_SPACE_SDM"]
    model_version = os.environ.get("MODEL_VERSION", "v1.0.0")
    file_xid = f"file_{participant}_TRN_DS_21_PA_2001A"

    try:
        content = client.files.download_bytes(instance_id=NodeId(space, file_xid))
    except Exception:
        content = client.files.download_bytes(external_id=file_xid)

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
        if key in {
            "ratedFlowM3h",
            "ratedHeadM",
            "ratedPowerKw",
            "designPressureBarg",
            "designTemperatureC",
            "dryWeightKg",
        }:
            parsed[key] = float(raw)
        else:
            parsed[key] = raw

    v_wo = ViewId(schema_edm, "viw_WorkOrder_edm", model_version)
    work_orders = client.data_modeling.instances.list(
        instance_type="node",
        sources=[v_wo],
        space=space,
        limit=-1,
    )
    open_count = 0
    for wo in work_orders:
        props = wo.properties.get(v_wo, {})
        status = (props.get("status") or "").upper()
        assets = props.get("assets") or []
        asset_ids = []
        for rel in assets:
            if hasattr(rel, "external_id"):
                asset_ids.append(rel.external_id)
            elif isinstance(rel, dict):
                asset_ids.append(rel.get("externalId"))
        if "21-PA-2001A" in asset_ids and status != "CLOSED":
            open_count += 1

    v_ehp = ViewId(schema_sdm, "viw_EquipmentHealthProfile_sdm", model_version)
    v_eq = ViewId("cdf_cdm", "CogniteEquipment", "v1")
    ehp_props = {
        "asset": DirectRelationReference(space, "21-PA-2001A"),
        "equipment": DirectRelationReference(space, "EQ-1002"),
        "datasheetFile": DirectRelationReference(space, file_xid),
        "openWorkOrderCount": open_count,
        # CDF timestamp props allow 1–3 fractional digits only (not full microseconds).
        "lastParsedTime": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    }
    for key in (
        "ratedFlowM3h",
        "ratedHeadM",
        "ratedPowerKw",
        "designPressureBarg",
        "designTemperatureC",
        "dryWeightKg",
        "casingMaterial",
        "sealType",
    ):
        if key in parsed:
            ehp_props[key] = parsed[key]

    applies = [
        NodeApply(
            space=space,
            external_id="ehp_21-PA-2001A",
            sources=[NodeOrEdgeData(source=v_ehp, properties=ehp_props)],
        )
    ]
    eq_props = {}
    if "manufacturer" in parsed:
        eq_props["manufacturer"] = parsed["manufacturer"]
    if "serialNumber" in parsed:
        eq_props["serialNumber"] = parsed["serialNumber"]
    if eq_props:
        applies.append(
            NodeApply(
                space=space,
                external_id="EQ-1002",
                sources=[NodeOrEdgeData(source=v_eq, properties=eq_props)],
            )
        )

    client.data_modeling.instances.apply(nodes=applies)

    return {
        "parsed": {k: v for k, v in parsed.items() if k not in ("manufacturer", "serialNumber")},
        "missing_fields": [m for m in missing if m not in ("manufacturer", "serialNumber")],
        "openWorkOrderCount": open_count,
    }
