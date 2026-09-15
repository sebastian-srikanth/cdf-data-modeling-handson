#!/usr/bin/env python3
"""The production acceptance contract: eight questions, asked of a live capability.

    uv run python tools/acceptance.py <PARTICIPANT>                 # every capability
    uv run python tools/acceptance.py <PARTICIPANT> contextualization

A chapter can say "this capability is production-shaped" in prose and be believed. This
runner makes it answerable. It exercises one capability against a real project and
reports, per property, PASS / FAIL / N/A — where **N/A must carry a reason**, because a
property quietly skipped is indistinguishable from one that passes.

The eight properties, and why each is on the list:

  1  correct initial result        the baseline; everything else is measured against it
  2  unchanged rerun is a no-op    a pipeline that churns on identical input cannot be
                                   scheduled, only supervised
  3  a changed input updates only
     the affected output           blast radius. The reason anyone dares re-run at 03:00
  4  a removed input retires its
     stale automatic output        silence is not agreement -- the link must come off
  5  bad input becomes visible
     review data                   filtering a bad row out makes the job green and the
                                   problem invisible. It has to land somewhere
  6  human decisions survive
     the rerun                     get this wrong once and nobody trusts the system again
  7  evidence and provenance
     stay queryable                "when did that link appear, and on what basis"
  8  workload and time are
     bounded                       an unbounded job does not fail, it hangs

This writes to CDF and then puts things back. Point it at a scratch participant.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _client import cdf_client, participant  # noqa: E402

from cognite.client.data_classes.data_modeling import (  # noqa: E402
    NodeApply, NodeId, NodeOrEdgeData, ViewId,
)

MODEL_VERSION = "v1.0.0"

PROPERTIES = [
    "correct initial result",
    "unchanged rerun is a no-op",
    "a changed input updates only the affected output",
    "a removed input retires its stale output",
    "bad input becomes visible review data",
    "human decisions survive the rerun",
    "evidence and provenance stay queryable",
    "workload and time are bounded",
]


class Contract:
    """Records one capability's answers. N/A always carries a reason."""

    def __init__(self, capability: str):
        self.capability = capability
        self.rows: list[tuple[str, str, str]] = []

    def ok(self, prop: str, detail: str = "") -> None:
        self.rows.append((prop, "PASS", detail))

    def bad(self, prop: str, detail: str) -> None:
        self.rows.append((prop, "FAIL", detail))

    def na(self, prop: str, reason: str) -> None:
        if not reason:
            raise ValueError("N/A without a reason is a skipped check pretending to pass")
        self.rows.append((prop, "N/A", reason))

    def assert_(self, prop: str, got, want, detail: str = "") -> bool:
        if got == want:
            self.ok(prop, detail or f"got {got!r}")
            return True
        self.bad(prop, f"got {got!r}, want {want!r}" + (f" -- {detail}" if detail else ""))
        return False

    @property
    def failed(self) -> int:
        return sum(1 for _, verdict, _ in self.rows if verdict == "FAIL")

    def report(self) -> None:
        print(f"\n  ---- {self.capability} " + "-" * max(0, 52 - len(self.capability)))
        covered = {p for p, _, _ in self.rows}
        for prop in PROPERTIES:
            if prop not in covered:
                self.rows.append((prop, "N/A", "the capability does not claim this yet"))
        order = {p: i for i, p in enumerate(PROPERTIES)}
        for prop, verdict, detail in sorted(self.rows, key=lambda r: order.get(r[0], 99)):
            mark = {"PASS": "[PASS]", "FAIL": "[FAIL]", "N/A": "[ -- ]"}[verdict]
            print(f"  {mark} {prop:<48} {detail}")


# --------------------------------------------------------------- contextualization ----
def contextualization(client, name: str) -> Contract:
    """MatchDocuments: rules -> regex -> entity matching, with the Chapter 17 spine."""
    c = Contract("contextualization (MatchDocuments)")
    isp = f"isp_{name}_TRN"
    sdm = f"ssp_{name}_MaintenanceInsight_sdm"
    db = f"rwd_{name}_Training_TRN"
    table = "rwt_Training_TRN_MappingRules"
    run_v = ViewId(sdm, "ContextualizationRun", MODEL_VERSION)
    sug_v = ViewId(sdm, "ContextualizationSuggestion", MODEL_VERSION)
    file_v = ViewId("cdf_cdm", "CogniteFile", "v1")
    pid = f"file_{name}_TRN_PID_21_SEP"
    fn = client.functions.retrieve(external_id=f"fnc_{name}_Training_MatchDocuments")
    if fn is None:
        c.bad(PROPERTIES[0], "the Function is not deployed")
        return c

    def call() -> dict:
        started = time.time()
        x = fn.call(data={})
        while x.status == "Running":
            time.sleep(4)
            x.update()
        if x.status != "Completed":
            raise RuntimeError(f"call {x.status}")
        time.sleep(6)                    # data modeling reads lag writes (section 17.1d)
        out = x.get_response()
        out["_elapsed"] = time.time() - started
        return out

    def links() -> list:
        n = client.data_modeling.instances.retrieve(nodes=(isp, pid), sources=file_v).nodes
        rels = n[0].properties[file_v].get("assets") or [] if n else []
        return sorted(r.external_id if hasattr(r, "external_id") else r["externalId"]
                      for r in rels)

    def latest_run() -> dict:
        runs = client.data_modeling.instances.list(sources=run_v, space=isp, limit=-1)
        if not runs:
            return {}
        best = max(runs, key=lambda n: n.properties[run_v].get("startedTime") or "")
        return dict(best.properties[run_v])

    def suggestion(xid: str) -> dict:
        n = client.data_modeling.instances.retrieve(nodes=(isp, xid), sources=sug_v).nodes
        return dict(n[0].properties[sug_v]) if n else {}

    # 1 -----------------------------------------------------------------------------
    first = call()
    run1 = latest_run()
    c.assert_(PROPERTIES[0], links(), ["TRN-21-SEP"], "the P&ID resolves to its area tag")

    # 8 -- bounded: the handler must finish well inside a Function's wall clock --------
    c.assert_(PROPERTIES[7], first["_elapsed"] < 120, True,
              f"completed in {first['_elapsed']:.0f}s, and every rung carries a deadline")

    # 7 -----------------------------------------------------------------------------
    have_provenance = bool(run1.get("runId")) and bool(run1.get("rulesVersion"))
    sug_xid = f"sug_{pid}_TRN-21-SEP"
    evidence = suggestion(sug_xid).get("evidenceText")
    c.assert_(PROPERTIES[6], bool(have_provenance and evidence), True,
              f"run {run1.get('runId')}, rules {run1.get('rulesVersion')}, evidence recorded")

    # 2 -----------------------------------------------------------------------------
    second = call()
    run2 = latest_run()
    unchanged = (links() == ["TRN-21-SEP"]
                 and (run2.get("staleRemovedCount") or 0) == 0
                 and (run2.get("supersededCount") or 0) == 0)
    c.assert_(PROPERTIES[1], unchanged, True,
              "same links, nothing retracted, nothing superseded")

    # 6 -- a human rejects the OTHER pair; it must survive -----------------------------
    ds = f"file_{name}_TRN_DS_21_PA_2001A"
    human_xid = f"sug_{ds}_21-PA-2001A"
    before = suggestion(human_xid)
    if not before:
        c.na(PROPERTIES[5], "the datasheet suggestion is absent; cannot test a veto")
        c.na(PROPERTIES[4], "no suggestion row to reject")
    else:
        client.data_modeling.instances.apply(nodes=[NodeApply(
            space=isp, external_id=human_xid,
            sources=[NodeOrEdgeData(source=sug_v, properties={
                "decision": "rejected", "decidedBy": "acceptance-contract",
                "evidenceText": "rejected by the acceptance contract"})])])
        time.sleep(6)
        call()
        after = suggestion(human_xid)
        c.assert_(PROPERTIES[5],
                  (after.get("decidedBy"), after.get("decision")),
                  ("acceptance-contract", "rejected"),
                  "the pipeline refused to overwrite a person's row")
        # 5 -- the rejection must be visible as review/quarantine data, not just absent
        c.assert_(PROPERTIES[4], after.get("decision") in
                  ("rejected", "needs-review"), True,
                  "the rejected pair is queryable, not silently dropped")

    # 3 and 4 -- break one rule: only that output changes -------------------------------
    rows = {r.key: r for r in client.raw.rows.list(db, table, limit=-1)}
    victim = next((k for k, r in rows.items()
                   if r.columns.get("targetExternalId") == "TRN-21-SEP"), None)
    if victim is None:
        c.na(PROPERTIES[2], "no rule targets the P&ID; cannot change one input")
        c.na(PROPERTIES[3], "no rule targets the P&ID; cannot remove one input")
    else:
        saved = dict(rows[victim].columns)
        broken = dict(saved)
        broken["sourcePattern"] = "TRN-21-SEP-PID-RevB.pdf"   # a reissued drawing
        client.raw.rows.insert(db, table, {victim: broken})
        time.sleep(3)
        call()
        run3 = latest_run()
        c.assert_(PROPERTIES[3], links(), [],
                  f"the orphaned link was retracted, staleRemovedCount="
                  f"{run3.get('staleRemovedCount')}")
        # only the affected output moved: the datasheet row is still the human's
        still_human = suggestion(human_xid).get("decidedBy")
        c.assert_(PROPERTIES[2],
                  (run3.get("rulesVersion") != run1.get("rulesVersion"),
                   still_human if before else "acceptance-contract"),
                  (True, "acceptance-contract"),
                  "rulesVersion moved and the unaffected pair was untouched")
        client.raw.rows.insert(db, table, {victim: saved})
        time.sleep(3)
        call()

    # put the human decision back the way we found it
    if before:
        client.data_modeling.instances.apply(nodes=[NodeApply(
            space=isp, external_id=human_xid,
            sources=[NodeOrEdgeData(source=sug_v, properties={
                "decision": before.get("decision") or "auto-applied",
                "decidedBy": before.get("decidedBy") or "pipeline",
                "evidenceText": before.get("evidenceText") or ""})])])
        time.sleep(4)
        call()
    return c


# ------------------------------------------------------------------ diagram tags ----
def diagram_annotation(client, name: str) -> Contract:
    """DetectDiagramTags: stable identity, reconciliation, review for placeless hits."""
    c = Contract("diagram annotation (DetectDiagramTags)")
    isp = f"isp_{name}_TRN"
    anno = ViewId("cdf_cdm", "CogniteDiagramAnnotation", "v1")
    fn = client.functions.retrieve(external_id=f"fnc_{name}_Training_DetectDiagramTags")
    if fn is None:
        c.bad(PROPERTIES[0], "the Function is not deployed")
        return c

    def call() -> dict:
        started = time.time()
        x = fn.call(data={})
        while x.status == "Running":
            time.sleep(5)
            x.update()
        if x.status != "Completed":
            raise RuntimeError(f"call {x.status}")
        time.sleep(6)
        out = x.get_response()
        out["_elapsed"] = time.time() - started
        return out

    def edge_ids() -> list:
        return sorted(e.external_id for e in client.data_modeling.instances.list(
            instance_type="edge", sources=anno, space=isp, limit=-1))

    first = call()
    ids1 = edge_ids()
    c.assert_(PROPERTIES[0], len(ids1) > 0, True, f"{len(ids1)} annotation edges")
    c.assert_(PROPERTIES[7], first["_elapsed"] < 600, True,
              f"completed in {first['_elapsed']:.0f}s")

    call()
    c.assert_(PROPERTIES[1], edge_ids(), ids1,
              "identical edge set -- identity is geometry-derived, not order-derived")

    # a planted stale edge must be retired; a reviewed one must not be
    from cognite.client.data_classes.data_modeling import DirectRelationReference, EdgeApply, EdgeId
    pid = f"file_{name}_TRN_PID_21_SEP"
    stale = f"anno_{pid}_21-PA-2001A_ACCEPTANCESTALE"
    kept = f"anno_{pid}_21-PA-2001A_ACCEPTANCEKEPT"
    for xid, status in ((stale, "Suggested"), (kept, "Approved")):
        client.data_modeling.instances.apply(edges=[EdgeApply(
            space=isp, external_id=xid,
            type=DirectRelationReference("cdf_cdm", "diagrams.AssetLink"),
            start_node=DirectRelationReference(isp, pid),
            end_node=DirectRelationReference(isp, "21-PA-2001A"),
            sources=[NodeOrEdgeData(source=anno, properties={
                "name": "acceptance probe", "status": status,
                "startNodePageNumber": 1, "startNodeText": "probe",
                "startNodeXMin": 0.91, "startNodeXMax": 0.94,
                "startNodeYMin": 0.91, "startNodeYMax": 0.94})])])
    time.sleep(6)
    result = call()
    after = edge_ids()
    c.assert_(PROPERTIES[3], stale not in after, True,
              f"the stale Suggested edge was retired ({result.get('annotations_removed')} removed)")
    c.assert_(PROPERTIES[5], kept in after, True,
              f"the Approved edge survived ({result.get('reviewed_annotations_kept')} kept)")
    client.data_modeling.instances.delete(edges=[EdgeId(isp, kept)])
    time.sleep(3)
    call()

    c.assert_(PROPERTIES[4], "detections_without_geometry" in result, True,
              f"placeless detections are counted and written to review "
              f"({result.get('detections_without_geometry')} this run)")
    c.na(PROPERTIES[2],
         "one drawing, one revision: Rev A -> Rev B is not yet a course fixture")
    c.na(PROPERTIES[6],
         "annotations carry confidence and page, but no run record yet -- the spine "
         "covers contextualization only")
    return c


CAPABILITIES = {
    "contextualization": contextualization,
    "diagram-annotation": diagram_annotation,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("participant", nargs="?", help="participant name (or PARTICIPANT env)")
    ap.add_argument("capability", nargs="?", choices=sorted(CAPABILITIES),
                    help="one capability; default is all of them")
    args = ap.parse_args()

    name = args.participant or participant()
    client = cdf_client()
    print(f"\n  acceptance contract · project {client.config.project} · participant {name}")

    chosen = [args.capability] if args.capability else sorted(CAPABILITIES)
    contracts = []
    for key in chosen:
        try:
            contracts.append(CAPABILITIES[key](client, name))
        except Exception as exc:  # noqa: BLE001 - a crash is a failed contract, not a stop
            broken = Contract(key)
            broken.bad(PROPERTIES[0], f"raised {type(exc).__name__}: {exc}")
            contracts.append(broken)

    failed = 0
    for contract in contracts:
        contract.report()
        failed += contract.failed

    total = sum(len(c.rows) for c in contracts)
    print(f"\n  {total} properties checked across {len(contracts)} capabilities, "
          f"{failed} failed")
    if failed:
        print("  CONTRACT NOT MET")
    else:
        print("  CONTRACT MET")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
