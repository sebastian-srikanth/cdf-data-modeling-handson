"""Neither handler may invent geometry it was not given.

Both used to. The P&ID detector returned a small box at the origin when the API omitted
vertices; the 3D loader returned a one-metre cube at the model origin when a CAD node
carried no boundingBox. Both wrote to CDF as though measured. Nothing errored, Fusion
rendered both, and anyone reading a clearance off that model was reading a number a
function made up to keep a write path happy.
"""
from conftest import load_handler
import pytest


@pytest.fixture(scope="module")
def detect():
    return load_handler("fnc_REFERENCE_Training_DetectDiagramTags")


@pytest.fixture(scope="module")
def three_d():
    return load_handler("fnc_REFERENCE_Training_Load3DRevision")


# ---------------------------------------------------------------- P&ID geometry ----
def test_real_vertices_give_a_real_box(detect):
    region = {"vertices": [{"x": 0.1, "y": 0.2}, {"x": 0.4, "y": 0.6}]}
    assert detect._bbox(region) == (0.1, 0.4, 0.2, 0.6)


def test_missing_vertices_return_none_not_a_default_box(detect):
    assert detect._bbox({}) is None
    assert detect._bbox({"vertices": []}) is None


def test_vertices_without_coordinates_return_none(detect):
    assert detect._bbox({"vertices": [{"page": 1}, {"foo": "bar"}]}) is None


def test_the_old_fallback_value_is_gone(detect):
    """0.0, 0.1, 0.0, 0.1 was the invented box. It must never be returned again."""
    for region in ({}, {"vertices": []}, {"vertices": [{}]}):
        assert detect._bbox(region) != (0.0, 0.1, 0.0, 0.1)


# ------------------------------------------------------------------ 3D geometry ----
def test_a_real_bounding_box_is_flattened(three_d):
    node = {"boundingBox": {"min": [1.0, 2.0, 3.0], "max": [4.0, 5.0, 6.0]}}
    assert three_d._bbox_props(node) == {
        "xMin": 1.0, "yMin": 2.0, "zMin": 3.0,
        "xMax": 4.0, "yMax": 5.0, "zMax": 6.0}


def test_a_node_with_no_bounding_box_returns_none(three_d):
    assert three_d._bbox_props({}) is None
    assert three_d._bbox_props({"boundingBox": {}}) is None


def test_a_truncated_bounding_box_returns_none(three_d):
    """Two coordinates is not a 3D box. Better to report it than to pad it."""
    assert three_d._bbox_props({"boundingBox": {"min": [0, 0], "max": [1, 1]}}) is None


def test_the_old_unit_cube_is_gone(three_d):
    """0,0,0 - 1,1,1 was the invented cube."""
    unit = {"xMin": 0.0, "yMin": 0.0, "zMin": 0.0,
            "xMax": 1.0, "yMax": 1.0, "zMax": 1.0}
    assert three_d._bbox_props({}) != unit
    assert three_d._bbox_props({"boundingBox": {"min": None, "max": None}}) != unit


# ------------------------------------------------- the quarantine path itself ----
# On this lab's P&ID every detection carries vertices, so a green live run proves the
# field is returned and nothing more. These prove the path a real drawing would take.
class _CapturingInstances:
    def __init__(self):
        self.applied = []

    def apply(self, nodes=None, edges=None, **kw):
        self.applied.extend(nodes or [])


class _CapturingClient:
    def __init__(self):
        import types
        self.data_modeling = types.SimpleNamespace(instances=_CapturingInstances())


def _placeless(target="21-PA-2001A"):
    return [{"source": "file_X_TRN_PID_21_SEP", "target": target,
             "page": 3, "text": "21-PA-2001A", "confidence": 0.77}]


def test_a_placeless_detection_becomes_a_review_row(detect):
    client = _CapturingClient()
    written = detect._record_for_review(
        client, "isp_X_TRN", "ssp_X_MaintenanceInsight_sdm", "v1.0.0",
        "file_X_TRN_PID_21_SEP", _placeless(), "ctxrun-test")
    assert written == 1
    node = client.data_modeling.instances.applied[0]
    props = node.sources[0].properties
    assert props["decision"] == "needs-review"
    assert props["method"] == "diagram-detect"
    assert props["evidencePage"] == 3
    assert props["confidence"] == 0.77


def test_the_review_row_says_why_it_could_not_be_placed(detect):
    """A reviewer who cannot see the reason has to redo the investigation."""
    client = _CapturingClient()
    detect._record_for_review(client, "isp_X_TRN", "ssp_X_MaintenanceInsight_sdm",
                              "v1.0.0", "file_X_TRN_PID_21_SEP", _placeless(), "r1")
    evidence = client.data_modeling.instances.applied[0].sources[0].properties["evidenceText"]
    assert "no vertices" in evidence and "page 3" in evidence


def test_nothing_is_written_when_every_detection_has_geometry(detect):
    client = _CapturingClient()
    assert detect._record_for_review(client, "isp_X_TRN", "sdm", "v1.0.0", "f", [], "r") == 0
    assert client.data_modeling.instances.applied == []


def test_review_row_identity_is_stable_across_runs(detect):
    """Two runs that both fail to place the same pair must update one row, not pile up."""
    ids = []
    for run in ("run-1", "run-2"):
        client = _CapturingClient()
        detect._record_for_review(client, "isp_X_TRN", "sdm", "v1.0.0", "f",
                                  _placeless(), run)
        ids.append(client.data_modeling.instances.applied[0].external_id)
    assert ids[0] == ids[1]
