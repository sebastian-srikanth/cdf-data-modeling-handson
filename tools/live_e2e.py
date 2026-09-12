#!/usr/bin/env python3
"""Deploy the whole course to a scratch CDF project, run it, verify it, tear it down.

    uv run python tools/live_e2e.py CI
    uv run python tools/live_e2e.py CI --teardown-only

Point this at a THROWAWAY project. Teardown deletes only resources named after the
participant, but a scratch project keeps the blast radius at zero.

It deliberately does NOT call `cdf clean --drop-data` or `cdf data purge space`: the first
destroys everything in the project, and the second requires a human to type the project
name. Both are the wrong tool for an unattended job.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys
import time

# Progress must appear in a CI log while the run is happening, not all at once when it
# ends. Python block-buffers stdout whenever it is not a terminal.
sys.stdout.reconfigure(line_buffering=True)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _client import ROOT, cdf_client, load_env  # noqa: E402

TEMPLATE = {
    "participant": "{name}",
    "site_code": "TRN",
    "instance_space": "isp_{name}_TRN",
    "schema_space_edm": "ssp_{name}_TrainingCore_edm",
    "schema_space_sdm": "ssp_{name}_MaintenanceInsight_sdm",
    "dataset": "dts_{name}_Training_TRN",
    "raw_db": "rwd_{name}_Training_TRN",
    "model_version": "v1.0.0",
    "function_runtime": "py311",
    # Chapter 16 groups. CI has no IdP group to bind to; a placeholder deploys fine and
    # simply matches nobody, which is the correct behaviour to exercise.
    "idp_group_reader": "00000000-0000-0000-0000-000000000000",
    "idp_group_developer": "00000000-0000-0000-0000-000000000000",
}
TRANSFORMATIONS = ["Load_Assets", "Load_Equipment", "Load_TimeSeries",
                   "Load_WorkOrders", "Load_WorkOrderOperations"]
FUNCTIONS = ["MatchDocuments", "DetectDiagramTags", "Load3DRevision",
             "ParseDatasheet", "GenerateDatapoints"]


def run(*args: str) -> str:
    print(f"    $ {' '.join(args)}")
    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout[-3000:])
        print(proc.stderr[-2000:])
        raise SystemExit(f"  command failed: {' '.join(args)}")
    return proc.stdout


def materialise(name: str) -> None:
    """Render the templated reference module into a literal participant module."""
    src = ROOT / "training" / "modules" / "reference"
    dst = ROOT / "training" / "modules" / "participants" / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

    values = {k: v.format(name=name) for k, v in TEMPLATE.items()}
    pattern = re.compile(r"\{\{\s*(\w+)\s*\}\}")
    for path in dst.rglob("*"):
        if path.is_file() and path.suffix in {".yaml", ".yml", ".sql", ".csv", ".py", ".txt", ".toml"}:
            text = path.read_text()
            rendered = pattern.sub(lambda m: values.get(m.group(1), m.group(0)), text)
            if rendered != text:
                path.write_text(rendered)
    # a participant module carries no variable defaults (Chapter 01 section 1.5)
    (dst / "default.config.yaml").unlink(missing_ok=True)
    for folder in dst.glob("functions/fnc_REFERENCE_*"):
        folder.rename(folder.with_name(folder.name.replace("REFERENCE", name)))

    (ROOT / f"training/config.{name}-training.yaml").write_text(
        "environment:\n"
        f"  name: {name}-training\n"
        f"  project: {__import__('os').environ['CDF_PROJECT']}\n"
        "  validation-type: dev\n"
        "  selected:\n"
        f"    - modules/participants/{name}\n"
    )


def wait_for_functions(client, name: str, timeout: int = 900) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        fns = [f for f in client.functions.list(limit=-1)
               if (f.external_id or "").startswith(f"fnc_{name}_Training_")]
        statuses = {f.external_id: f.status for f in fns}
        if len(fns) == len(FUNCTIONS) and all(s in ("Ready", "Failed") for s in statuses.values()):
            failed = [x for x, s in statuses.items() if s == "Failed"]
            if failed:
                raise SystemExit(f"  functions failed to deploy: {failed}")
            print(f"    all {len(fns)} functions Ready")
            return
        time.sleep(20)
    raise SystemExit("  timed out waiting for functions to become Ready")


def delete_location_filter(client, name: str) -> None:
    """Location filters live under the apps API and the SDK has no delete for them.

    The delete body is a bare list of NUMERIC ids -- `{"items": [1588]}`. Passing
    `{"items": [{"id": 1588}]}` or `{"items": [{"externalId": ...}]}` returns HTTP 400
    "Expected numeric literal". Chapter 18 uses `cdf clean --include locations` instead,
    which is the right answer for a human; this is the right answer for a script.
    """
    import json
    import urllib.request

    header, value = client.config.credentials.authorization_header()
    headers = {header: value, "Content-Type": "application/json",
               "cdf-version": "alpha", "accept": "application/json"}
    root = (f"{client.config.base_url.rstrip('/')}/apps/v1/projects/"
            f"{client.config.project}/storage/config/locationfilters")

    def post(path: str, payload: dict) -> dict:
        request = urllib.request.Request(
            f"{root}{path}", data=json.dumps(payload).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
            return json.loads(body) if body.strip() else {}

    try:
        items = post("/list", {"flat": True}).get("items", [])
        mine = [i["id"] for i in items if i.get("externalId") == f"loc_{name}_TRN"]
        if mine:
            post("/delete", {"items": mine})
            print(f"    removed location filter loc_{name}_TRN")
    except Exception as exc:  # noqa: BLE001
        print(f"    skip location filter: {str(exc)[:120]}")


def teardown(client, name: str) -> None:
    isp = f"isp_{name}_TRN"
    spaces = [isp, f"ssp_{name}_TrainingCore_edm", f"ssp_{name}_MaintenanceInsight_sdm"]

    def attempt(label, fn):
        try:
            fn()
            print(f"    removed {label}")
        except Exception as exc:  # noqa: BLE001
            print(f"    skip {label}: {str(exc)[:100]}")

    for fn_name in FUNCTIONS:
        xid = f"fnc_{name}_Training_{fn_name}"
        attempt(f"function {xid}", lambda x=xid: client.functions.delete(external_id=x))
        # deleting a function leaves its uploaded source zip behind (Chapter 17 section 17.2b)
        attempt(f"function zip {xid}", lambda x=xid: client.files.delete(external_id=x))
    attempt("transformations", lambda: client.transformations.delete(
        external_id=[f"tra_{name}_Training_TRN_{t}" for t in TRANSFORMATIONS],
        ignore_unknown_ids=True))
    attempt("workflow", lambda: client.workflows.delete(
        external_id=f"wkf_{name}_Training_TRN", ignore_unknown_ids=True))
    attempt("raw database", lambda: client.raw.databases.delete(
        name=f"rwd_{name}_Training_TRN", recursive=True))
    attempt("classic OBJ file", lambda: client.files.delete(
        external_id=f"file_{name}_TRN_3D_21_SEP"))
    for model in client.three_d.models.list(limit=-1):
        if model.name == f"trd_{name}_TRN_CAD":
            attempt("3D model", lambda m=model: client.three_d.models.delete(id=m.id))

    # edges before nodes: an edge whose node is gone cannot be addressed
    edges = client.data_modeling.instances.list(instance_type="edge", space=isp, limit=-1)
    if edges:
        attempt(f"{len(edges)} edges", lambda: client.data_modeling.instances.delete(
            edges=[(e.space, e.external_id) for e in edges]))
    nodes = client.data_modeling.instances.list(instance_type="node", space=isp, limit=-1)
    if nodes:
        attempt(f"{len(nodes)} nodes", lambda: client.data_modeling.instances.delete(
            nodes=[(n.space, n.external_id) for n in nodes]))

    models = [m for m in client.data_modeling.data_models.list(limit=-1) if m.space in spaces]
    if models:
        attempt("data models", lambda: client.data_modeling.data_models.delete(
            [(m.space, m.external_id, m.version) for m in models]))
    views = [v for v in client.data_modeling.views.list(limit=-1, include_global=False)
             if v.space in spaces]
    if views:
        attempt("views", lambda: client.data_modeling.views.delete(
            [(v.space, v.external_id, v.version) for v in views]))
    containers = [c for c in client.data_modeling.containers.list(limit=-1, include_global=False)
                  if c.space in spaces]
    if containers:
        attempt("containers", lambda: client.data_modeling.containers.delete(
            [(c.space, c.external_id) for c in containers]))
    attempt("spaces", lambda: client.data_modeling.spaces.delete(spaces))

    left = {s.space for s in client.data_modeling.spaces.list(limit=-1)} & set(spaces)
    if left:
        raise SystemExit(f"  teardown incomplete, spaces remain: {sorted(left)}")

    delete_location_filter(client, name)

    # Chapter 15's agent is global too, and Chapter 15 section 15.7 has the learner
    # delete it by hand. An unattended run must not rely on that.
    try:
        attempt(f"agent agt_{name}_maintenance",
                lambda: client.agents.delete(f"agt_{name}_maintenance",
                                             ignore_unknown_ids=True))
    except Exception as exc:  # noqa: BLE001 - Atlas AI is alpha and may be disabled
        print(f"    skip agent: {str(exc)[:90]}")

    # Chapter 16's groups are global resources. Purging spaces does not remove them, and
    # a group bound to a placeholder sourceId matches nobody but still clutters the
    # project's access list.
    mine = [g for g in client.iam.groups.list(all=True)
            if f"_{name}_training_" in (g.name or "")]
    for group in mine:
        attempt(f"group {group.name}", lambda g=group: client.iam.groups.delete(g.id))

    # the generated module and config are build artefacts, not course content
    generated = ROOT / "training" / "modules" / "participants" / name
    if generated.exists():
        shutil.rmtree(generated)
        print(f"    removed generated module participants/{name}")
    config = ROOT / f"training/config.{name}-training.yaml"
    if config.exists():
        config.unlink()
        print(f"    removed generated config.{name}-training.yaml")

    print("    teardown clean (the data set stays: CDF cannot hard-delete data sets)")


def main() -> int:
    load_env()
    name = sys.argv[1] if len(sys.argv) > 1 else "CI"
    teardown_only = "--teardown-only" in sys.argv
    client = cdf_client("course-live-e2e")
    print(f"\n  project {client.config.project} · participant {name}\n")

    if teardown_only:
        print("  TEARDOWN")
        teardown(client, name)
        return 0

    config = f"training/config.{name}-training.yaml"
    print("  1. materialise the participant module")
    materialise(name)

    print("  2. build")
    run("uv", "run", "cdf", "build", "--config-yaml", config)

    print("  3. deploy")
    run("uv", "run", "cdf", "deploy", "--cdf-project", client.config.project,
        "--include", "data_sets", "--include", "raw", "--include", "data_modeling",
        "--include", "transformations", "--include", "files", "--include", "locations",
        "--include", "workflows", "--include", "functions", "--include", "auth")

    print("  4. wait for functions to build")
    wait_for_functions(client, name)

    print("  5. run the transformations in dependency order")
    for t in TRANSFORMATIONS:
        xid = f"tra_{name}_Training_TRN_{t}"
        job = client.transformations.run(transformation_external_id=xid, wait=True)
        # status is a str-subclass enum: `== "Completed"` works, but str() yields
        # "TransformationJobStatus.COMPLETED". Compare the value, never the str().
        if job.status != "Completed":
            raise SystemExit(f"  transformation {xid} finished {job.status}: {job.error}")
        print(f"    {t} Completed")

    print("  6. call the functions")
    for fn_name in FUNCTIONS:
        call = client.functions.call(external_id=f"fnc_{name}_Training_{fn_name}", wait=True)
        if call.status != "Completed":
            raise SystemExit(f"  function {fn_name} finished {call.status}")
        print(f"    {fn_name} Completed")

    print("  7. run the workflow (Chapter 12) -- deploying it is not enough")
    run_id = client.workflows.executions.run(f"wkf_{name}_Training_TRN", "v1")
    deadline = time.time() + 900
    while time.time() < deadline:
        execution = client.workflows.executions.retrieve_detailed(run_id.id)
        if execution.status not in ("running", "in_progress"):
            break
        time.sleep(10)
    print(f"    workflow finished: {execution.status}")
    if execution.status != "completed":
        failed = [t.external_id for t in (execution.executed_tasks or [])
                  if str(t.status) != "completed"]
        raise SystemExit(f"  workflow {execution.status}; failing tasks: {failed}")

    print("  8. self-check every chapter")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "selfcheck.py"), "all"],
        cwd=ROOT, text=True, env={**__import__("os").environ, "PARTICIPANT": name})
    if proc.returncode != 0:
        raise SystemExit("  self-check reported failures — see above")

    print("\n  LIVE END-TO-END PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
