#!/usr/bin/env python3
"""Am I actually done with this chapter? Ask CDF, not yourself.

    uv run python tools/selfcheck.py 03      # one chapter
    uv run python tools/selfcheck.py all     # every chapter you have reached

Each check corresponds to a [VERIFY] line or a Gate bullet in the chapter. Nothing here
writes to CDF — it only reads. PARTICIPANT must be set (in .env or the environment).
"""
from __future__ import annotations

import sys
import pathlib

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _client import Report, cdf_client, participant  # noqa: E402

from cognite.client.data_classes import filters as flt  # noqa: E402
from cognite.client.data_classes.data_modeling import ViewId  # noqa: E402

MODEL_VERSION = "v1.0.0"


def spaces_for(name: str) -> tuple[str, str, str]:
    return (
        f"isp_{name}_TRN",
        f"ssp_{name}_TrainingCore_edm",
        f"ssp_{name}_MaintenanceInsight_sdm",
    )


# --------------------------------------------------------------------- ch 03 ----
def check_03(client, name, r: Report) -> None:
    isp, edm, sdm = spaces_for(name)
    deployed = {s.space for s in client.data_modeling.spaces.list(limit=-1)}
    for space in (isp, edm, sdm):
        r.check(f"space {space}", space in deployed, True)

    # containers.list / views.list / data_models.list take `space: str`, NOT a list.
    # Passing a list silently returns only the first space -- no error, wrong answer.
    # List once and filter in Python instead.
    mine = {edm, sdm}
    containers = {
        c.external_id
        for c in client.data_modeling.containers.list(limit=-1, include_global=False)
        if c.space in mine
    }
    r.check("containers deployed", sorted(containers), ["EquipmentHealthProfile", "WorkOrder"])

    views = {
        v.external_id
        for v in client.data_modeling.views.list(limit=-1, include_global=False)
        if v.space in mine
    }
    r.check("views deployed", sorted(views), ["Asset", "EquipmentHealthProfile", "WorkOrder"])

    models = {
        m.external_id
        for m in client.data_modeling.data_models.list(limit=-1)
        if m.space in mine
    }
    r.check("data models deployed", sorted(models), ["MaintenanceInsight", "TrainingCore"])

    # the two connection properties are the point of Asset (§3.9, §3.12)
    try:
        asset = client.data_modeling.views.retrieve((sdm, "Asset", MODEL_VERSION))[0]
        props = asset.properties
        r.check(
            "Asset.healthProfile is a reverse direct relation",
            type(props.get("healthProfile")).__name__,
            "SingleReverseDirectRelation",
        )
        r.check(
            "Asset.diagramAnnotations is an edge connection",
            type(props.get("diagramAnnotations")).__name__,
            "MultiEdgeConnection",
        )
    except IndexError:
        r.check("Asset view retrievable", False, True)

    # constraints and indexes a learner is told to add (§3.7)
    wo = client.data_modeling.containers.retrieve((edm, "WorkOrder"))
    if wo:
        r.check("WorkOrder has a uniqueness constraint",
                any(type(c).__name__.startswith("Uniqueness") for c in (wo.constraints or {}).values()), True)
        r.check("WorkOrder has a btree index", len(wo.indexes or {}) >= 1, True)
        src = (wo.properties or {}).get("sourceSystem")
        r.check("sourceSystem is immutable", bool(src and src.immutable), True)

    ehp = client.data_modeling.containers.retrieve((sdm, "EquipmentHealthProfile"))
    if ehp:
        r.check("EquipmentHealthProfile has a requires constraint",
                any(type(c).__name__.startswith("Requires") for c in (ehp.constraints or {}).values()), True)
        united = sorted(
            k for k, p in (ehp.properties or {}).items()
            if getattr(getattr(p, "type", None), "unit", None) is not None
        )
        r.check("properties carrying a unit", len(united), 6)
        r.note("united properties", united)


# --------------------------------------------------------------------- ch 04 ----
def check_04(client, name, r: Report) -> None:
    isp, _, _ = spaces_for(name)
    raw_db = f"rwd_{name}_Training_TRN"

    r.check("data set exists",
            client.data_sets.retrieve(external_id=f"dts_{name}_Training_TRN") is not None, True)

    want_rows = {
        "rwt_Training_TRN_Assets": 8,
        "rwt_Training_TRN_Equipment": 5,
        "rwt_Training_TRN_TimeSeries": 6,
        "rwt_Training_TRN_WorkOrders": 3,
        "rwt_Training_TRN_WorkOrderOperations": 8,
    }
    try:
        tables = {t.name for t in client.raw.tables.list(raw_db, limit=-1)}
    except Exception:
        tables = set()
    r.check("RAW tables", sorted(tables), sorted(want_rows))
    for table, expected in want_rows.items():
        if table in tables:
            got = len(client.raw.rows.list(raw_db, table, limit=-1))
            r.check(f"RAW rows {table}", got, expected)

    files = client.data_modeling.instances.list(
        sources=ViewId("cdf_cdm", "CogniteFile", "v1"), space=isp, limit=-1)
    r.check("CogniteFile nodes (P&ID + datasheet)", len(files), 2)
    obj = client.files.retrieve(external_id=f"file_{name}_TRN_3D_21_SEP")
    r.check("classic OBJ uploaded", bool(obj and obj.uploaded), True)


# --------------------------------------------------------------------- ch 05 ----
def check_05(client, name, r: Report) -> None:
    isp, edm, _ = spaces_for(name)
    counts = {
        "assets": (ViewId("cdf_cdm", "CogniteAsset", "v1"), 8),
        "equipment": (ViewId("cdf_cdm", "CogniteEquipment", "v1"), 5),
        "time series": (ViewId("cdf_cdm", "CogniteTimeSeries", "v1"), 6),
    }
    for label, (view, expected) in counts.items():
        got = len(client.data_modeling.instances.list(sources=view, space=isp, limit=-1))
        r.check(f"{label} loaded", got, expected)

    wo_view = ViewId(edm, "WorkOrder", MODEL_VERSION)
    work_orders = client.data_modeling.instances.list(sources=wo_view, space=isp, limit=-1)
    r.check("work orders loaded", len(work_orders), 3)

    activities = client.data_modeling.instances.list(
        sources=ViewId("cdf_cdm", "CogniteActivity", "v1"), space=isp, limit=-1)
    wo_ids = {n.external_id for n in work_orders}
    operations = [a for a in activities if a.external_id not in wo_ids]
    r.check("activities total (operations + work orders)", len(activities), 9)
    r.check("operations loaded (8 source rows -> 6)", len(operations), 6)


# --------------------------------------------------------------------- ch 07 ----
def check_07(client, name, r: Report) -> None:
    isp, _, _ = spaces_for(name)
    file_view = ViewId("cdf_cdm", "CogniteFile", "v1")
    datasheet = client.data_modeling.instances.retrieve(
        nodes=(isp, f"file_{name}_TRN_DS_21_PA_2001A"), sources=file_view).nodes
    if not datasheet:
        r.check("datasheet file node exists", False, True)
        return
    assets = datasheet[0].properties[file_view].get("assets") or []
    linked = [a.get("externalId") if isinstance(a, dict) else a.external_id for a in assets]
    r.check("datasheet linked to the pump by entity matching", linked, ["21-PA-2001A"])


# --------------------------------------------------------------------- ch 08 ----
def check_08(client, name, r: Report) -> None:
    isp, _, sdm = spaces_for(name)
    anno = ViewId("cdf_cdm", "CogniteDiagramAnnotation", "v1")
    edges = client.data_modeling.instances.list(
        instance_type="edge", sources=anno, space=isp, limit=-1)
    r.check("diagram annotation edges exist", len(edges) >= 1, True)
    r.note("annotations created", len(edges))
    if edges:
        starts = {e.start_node.external_id for e in edges}
        r.check("edges start at the P&ID file",
                all(s.startswith(f"file_{name}_TRN_PID") for s in starts), True)


# --------------------------------------------------------------------- ch 09 ----
def check_09(client, name, r: Report) -> None:
    isp, _, _ = spaces_for(name)
    models = [m for m in client.three_d.models.list(limit=-1) if m.name == f"trd_{name}_TRN_CAD"]
    r.check("3D model exists", len(models), 1)
    if not models:
        return

    # `three_d.revisions.list()` returns an EMPTY list for a revision created through the
    # data-modeling 3D path, even though `retrieve()` returns it published and Done.
    # Check the CADModel node and the mapped geometry instead -- that is what the
    # chapter's Gate actually asks for, and it is the reliable signal.
    cad_models = client.data_modeling.instances.list(
        sources=ViewId("cdf_cdm", "CogniteCADModel", "v1"), space=isp, limit=-1)
    r.check("CogniteCADModel node exists", len(cad_models) >= 1, True)

    objects = client.data_modeling.instances.list(
        sources=ViewId("cdf_cdm", "Cognite3DObject", "v1"), space=isp, limit=-1)
    r.check("3D objects mapped to assets", len(objects), 6)

    nodes = client.data_modeling.instances.list(
        sources=ViewId("cdf_cdm", "CogniteCADNode", "v1"), space=isp, limit=-1)
    mapped = {n.external_id for n in nodes}
    r.check("the hero pump has CAD geometry", "cadnode_21-PA-2001A" in mapped, True)


# --------------------------------------------------------------------- ch 10 ----
def check_10(client, name, r: Report) -> None:
    isp, _, sdm = spaces_for(name)
    ehp_view = ViewId(sdm, "EquipmentHealthProfile", MODEL_VERSION)
    nodes = client.data_modeling.instances.list(sources=ehp_view, space=isp, limit=-1)
    r.check("health profile visible through the view", len(nodes), 1)
    if not nodes:
        r.note("hint", "0 usually means name/description were not written — see §3.8b")
        return
    props = nodes[0].properties[ehp_view]
    for key in ("asset", "equipment", "datasheetFile"):
        r.check(f"{key} direct relation populated", bool(props.get(key)), True)
    r.check("specs parsed from the datasheet",
            all(props.get(k) is not None for k in ("ratedFlowM3h", "ratedPowerKw", "sealType")), True)
    r.check("openWorkOrderCount computed", props.get("openWorkOrderCount") is not None, True)


# --------------------------------------------------------------------- ch 11 ----
def check_11(client, name, r: Report) -> None:
    isp, _, _ = spaces_for(name)
    ts_view = ViewId("cdf_cdm", "CogniteTimeSeries", "v1")
    series = client.data_modeling.instances.list(sources=ts_view, space=isp, limit=-1)
    r.check("time series present", len(series), 6)
    with_data = 0
    for node in series:
        # retrieve_latest returns ONE LatestDatapoint, not a list -- len() raises TypeError.
        latest = client.time_series.data.retrieve_latest(instance_id=(isp, node.external_id))
        if latest is not None and getattr(latest, "value", None) is not None:
            with_data += 1
    r.check("series carrying datapoints", with_data, 6)


# --------------------------------------------------------------------- ch 12 ----
def check_12(client, name, r: Report) -> None:
    xid = f"wkf_{name}_Training_TRN"
    workflows = {w.external_id for w in client.workflows.list(limit=-1)}
    r.check("workflow deployed", xid in workflows, True)
    if xid not in workflows:
        return
    versions = client.workflows.versions.list(workflow_version_ids=xid, limit=-1)
    tasks = versions[0].workflow_definition.tasks if versions else []
    r.check("workflow has ten tasks", len(tasks), 10)
    runs = client.workflows.executions.list(workflow_version_ids=xid, limit=5)
    r.check("workflow has been executed at least once", len(runs) >= 1, True)
    if runs:
        r.note("most recent execution", runs[0].status)
        r.check("most recent execution completed", str(runs[0].status), "completed")
    else:
        r.note("hint", "deploy is not enough -- trigger the workflow (Chapter 12 §12.4)")


# --------------------------------------------------------------------- ch 13 ----
def check_13(client, name, r: Report) -> None:
    isp, edm, sdm = spaces_for(name)
    from cognite.client.data_classes.data_modeling.query import (
        NodeResultSetExpression, Query, Select, SourceSelector)

    ehp_view = ViewId(sdm, "EquipmentHealthProfile", MODEL_VERSION)
    q = Query(
        with_={
            "pump": NodeResultSetExpression(
                filter=flt.Equals(["node", "externalId"], "21-PA-2001A"), limit=1),
            "profile": NodeResultSetExpression(
                from_="pump", through=ehp_view.as_property_ref("asset"),
                direction="inwards", limit=10),
        },
        select={"profile": Select([SourceSelector(ehp_view, ["ratedPowerKw"])])},
    )
    res = client.data_modeling.instances.query(q)
    r.check("reverse direct relation traversal returns the profile", len(res["profile"]), 1)

    wo_view = ViewId(edm, "WorkOrder", MODEL_VERSION)
    pump = {"space": isp, "externalId": "21-PA-2001A"}
    orders = client.data_modeling.instances.list(
        sources=wo_view, space=isp, limit=-1,
        filter=flt.ContainsAny(wo_view.as_property_ref("assets"), [pump]))
    r.check("work orders on the pump", sorted(n.external_id for n in orders), ["WO-1001"])


CHECKS = {
    "03": check_03, "04": check_04, "05": check_05, "06": check_06,
    "07": check_07, "08": check_08, "09": check_09, "10": check_10,
    "11": check_11, "12": check_12, "13": check_13, "15": check_15,
    "18": check_18,
}

# Chapter 18 asserts the OPPOSITE of every other chapter: it passes when your resources are
# gone. Running it inside `all` would fail for anyone mid-course, so ask for it by name.
EXCLUDE_FROM_ALL = {"18"}


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    which = sys.argv[1]
    if which == "all":
        chapters = sorted(set(CHECKS) - EXCLUDE_FROM_ALL)
    else:
        chapters = [which.zfill(2)]

    unknown = [c for c in chapters if c not in CHECKS]
    if unknown:
        print(f"  no self-check for chapter {unknown[0]}. Available: {', '.join(sorted(CHECKS))}")
        return 2

    client = cdf_client()
    name = participant()
    print(f"\n  project {client.config.project} · participant {name}\n")

    worst = 0
    for chapter in chapters:
        print(f"  ---- Chapter {chapter} " + "-" * 46)
        report = Report(chapter)
        try:
            CHECKS[chapter](client, name, report)
        except Exception as exc:  # noqa: BLE001 - a learner needs the message, not a traceback
            report.check(f"self-check ran without error ({type(exc).__name__})", str(exc)[:120], ok=False)
        worst = max(worst, report.finish())
        print()
    return worst


if __name__ == "__main__":
    sys.exit(main())
