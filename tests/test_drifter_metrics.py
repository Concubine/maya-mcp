"""#743: the drifter fixture's pure metrics.

These are frame-invariant on purpose. #737 turned on comparing a quantity
that survives any rigid or mirrored transform, because height agreed to
2 micrometres on three poses whose arms were metres out. Every metric here
must be a distance between two points on the same mesh - never a coordinate,
never a bounding box.
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "evals"))

import drifter_metrics as dm  # noqa: E402


def test_distance_is_euclidean():
    assert dm.distance([0.0, 0.0, 0.0], [3.0, 4.0, 0.0]) == 5.0


def test_farthest_pair_finds_the_extremes():
    pts = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [5.0, 0.0, 0.0], [2.0, 0.0, 0.0]]
    i, j, d = dm.farthest_pair(pts)
    assert {i, j} == {0, 2}
    assert d == 5.0


def test_rim_diameter_of_a_unit_circle_ring():
    pts = [[math.cos(t * math.pi / 8), 0.0, math.sin(t * math.pi / 8)]
           for t in range(16)]
    assert abs(dm.rim_diameter(pts) - 2.0) < 1e-9


def test_rim_diameter_is_invariant_under_rigid_motion():
    pts = [[math.cos(t * math.pi / 8), 0.0, math.sin(t * math.pi / 8)]
           for t in range(16)]
    # Rotate 37 degrees about Y and translate: the diameter must not move.
    a = math.radians(37.0)
    moved = [[p[0] * math.cos(a) - p[2] * math.sin(a) + 11.0,
              p[1] - 4.0,
              p[0] * math.sin(a) + p[2] * math.cos(a) + 6.0] for p in pts]
    assert abs(dm.rim_diameter(pts) - dm.rim_diameter(moved)) < 1e-9


def test_rim_diameter_is_invariant_under_mirroring():
    pts = [[math.cos(t * math.pi / 8), 0.0, math.sin(t * math.pi / 8)]
           for t in range(16)]
    mirrored = [[-p[0], p[1], p[2]] for p in pts]
    assert abs(dm.rim_diameter(pts) - dm.rim_diameter(mirrored)) < 1e-9


def test_apex_to_tip_is_a_plain_distance():
    assert abs(dm.apex_to_tip([0.0, 4.0, 0.0], [0.0, 0.1, 0.0]) - 3.9) < 1e-12


def test_rim_diameter_refuses_fewer_than_two_points():
    try:
        dm.rim_diameter([[0.0, 0.0, 0.0]])
    except ValueError as exc:
        assert "at least 2" in str(exc)
    else:
        raise AssertionError("expected ValueError")
