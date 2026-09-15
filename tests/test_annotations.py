"""Annotation identity. The bug these exist to prevent was found live, not here:
one re-run of DetectDiagramTags took a P&ID from 9 annotation edges to 17."""
from conftest import load_handler
import pytest


@pytest.fixture(scope="module")
def detect():
    return load_handler("fnc_REFERENCE_Training_DetectDiagramTags")


BOX = (0.10, 0.20, 0.30, 0.40)


def test_the_same_detection_gets_the_same_id(detect):
    a = detect._annotation_id("file_1", "21-PA-2001A", 1, BOX)
    b = detect._annotation_id("file_1", "21-PA-2001A", 1, BOX)
    assert a == b


def test_a_different_place_is_a_different_annotation(detect):
    """The same tag can legitimately appear twice on one drawing."""
    a = detect._annotation_id("file_1", "21-PA-2001A", 1, BOX)
    b = detect._annotation_id("file_1", "21-PA-2001A", 1, (0.5, 0.6, 0.7, 0.8))
    assert a != b


def test_a_different_page_is_a_different_annotation(detect):
    a = detect._annotation_id("file_1", "21-PA-2001A", 1, BOX)
    b = detect._annotation_id("file_1", "21-PA-2001A", 2, BOX)
    assert a != b


def test_a_different_drawing_is_a_different_annotation(detect):
    a = detect._annotation_id("file_1", "21-PA-2001A", 1, BOX)
    b = detect._annotation_id("file_2", "21-PA-2001A", 1, BOX)
    assert a != b


def test_a_floating_point_wobble_does_not_change_identity(detect):
    """The service is free to return 0.1000000001 where it returned 0.1 last night.
    An identity that changes on that is not an identity."""
    a = detect._annotation_id("file_1", "21-PA-2001A", 1, (0.1, 0.2, 0.3, 0.4))
    b = detect._annotation_id("file_1", "21-PA-2001A", 1,
                              (0.10000001, 0.19999999, 0.3, 0.4))
    assert a == b


def test_a_real_move_does_change_identity(detect):
    """Rounding must not be so coarse that a genuinely different box collides."""
    a = detect._annotation_id("file_1", "21-PA-2001A", 1, (0.1000, 0.2, 0.3, 0.4))
    b = detect._annotation_id("file_1", "21-PA-2001A", 1, (0.1002, 0.2, 0.3, 0.4))
    assert a != b


def test_the_id_is_within_the_external_id_length_limit(detect):
    long_file = "file_" + "X" * 300
    assert len(detect._annotation_id(long_file, "21-PA-2001A", 1, BOX)) <= 255


def test_the_id_carries_the_tag_so_a_human_can_read_it(detect):
    """A hash-only ID is correct and useless when you are staring at a list of them."""
    assert "21-PA-2001A" in detect._annotation_id("file_1", "21-PA-2001A", 1, BOX)
