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
