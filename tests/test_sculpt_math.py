import math

from maya_plugin.handlers import sculpt_math


def test_vnoise_deterministic_and_bounded():
    samples = [
        sculpt_math.vnoise(x * 0.7, x * 0.3, x * 1.1) for x in range(50)
    ]
    assert samples == [
        sculpt_math.vnoise(x * 0.7, x * 0.3, x * 1.1) for x in range(50)
    ]
    assert all(0.0 <= s <= 1.0 for s in samples)
    assert max(samples) - min(samples) > 0.3  # actually varies


def test_fbm_signed_and_octaves_add_detail():
    one = [sculpt_math.fbm(x * 0.5, 0.0, 0.0, octaves=1) for x in range(40)]
    two = [sculpt_math.fbm(x * 0.5, 0.0, 0.0, octaves=2) for x in range(40)]
    assert any(v < 0 for v in two) and any(v > 0 for v in two)
    assert one != two


def test_falloff_weight_edges():
    assert sculpt_math.falloff_weight(0.0, 2.0, "smooth") == 1.0
    assert sculpt_math.falloff_weight(2.0, 2.0, "smooth") == 0.0
    assert sculpt_math.falloff_weight(3.0, 2.0, "linear") == 0.0
    assert math.isclose(sculpt_math.falloff_weight(1.0, 2.0, "linear"), 0.5)
    mid_smooth = sculpt_math.falloff_weight(1.0, 2.0, "smooth")
    assert math.isclose(mid_smooth, 0.5)  # smoothstep(0.5) = 0.5


class TestBboxIntersection:
    """#822: the overlap of two world bboxes, [xmin, ymin, zmin, xmax, ymax,
    zmax] as exactWorldBoundingBox reports them. Touching is NOT overlapping -
    two cubes sharing a face gave polyCBoolOp an empty intersection."""

    def test_overlapping_cubes_give_the_overlap_box(self):
        a = [0, 0, 0, 1, 1, 1]
        b = [0.5, 0.5, 0.5, 1.5, 1.5, 1.5]
        assert sculpt_math.bbox_intersection(a, b) == [0.5, 0.5, 0.5, 1, 1, 1]

    def test_disjoint_boxes_have_none(self):
        assert sculpt_math.bbox_intersection([0, 0, 0, 1, 1, 1], [3, 0, 0, 4, 1, 1]) is None

    def test_boxes_sharing_a_face_have_none(self):
        assert sculpt_math.bbox_intersection([0, 0, 0, 1, 1, 1], [1, 0, 0, 2, 1, 1]) is None

    def test_a_box_inside_another_is_the_inner_box(self):
        assert sculpt_math.bbox_intersection([-0.5, -0.5, -0.5, 0.5, 0.5, 0.5],
                                             [-1.5, -1.5, -1.5, 1.5, 1.5, 1.5]) == [-0.5, -0.5, -0.5, 0.5, 0.5, 0.5]
