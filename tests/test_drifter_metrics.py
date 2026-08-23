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


DECLARED = [
    {"clip": "pulse_swim", "frame": 0, "rim_diameter": 1.200,
     "apex_to_tip": 3.900},
    {"clip": "pulse_swim", "frame": 15, "rim_diameter": 0.900,
     "apex_to_tip": 3.700},
]


def test_compare_samples_clean_when_inside_tolerance():
    measured = [dict(s) for s in DECLARED]
    measured[1]["rim_diameter"] += 5e-4
    assert dm.compare_samples(DECLARED, measured, 1e-3) == []


def test_compare_samples_reports_the_metric_that_moved():
    measured = [dict(s) for s in DECLARED]
    measured[1]["apex_to_tip"] = 3.500
    bad = dm.compare_samples(DECLARED, measured, 1e-3)
    assert len(bad) == 1
    assert bad[0]["clip"] == "pulse_swim"
    assert bad[0]["frame"] == 15
    assert bad[0]["metric"] == "apex_to_tip"
    assert abs(bad[0]["delta"] - 0.2) < 1e-9


def test_compare_samples_refuses_a_missing_measurement():
    try:
        dm.compare_samples(DECLARED, DECLARED[:1], 1e-3)
    except ValueError as exc:
        assert "pulse_swim" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_seam_violations_ignores_a_one_shot_clip():
    samples = [
        {"clip": "tendril_reach", "frame": 0, "rim_diameter": 1.2,
         "apex_to_tip": 3.9},
        {"clip": "tendril_reach", "frame": 30, "rim_diameter": 1.2,
         "apex_to_tip": 2.4},
    ]
    assert dm.seam_violations(samples, ["pulse_swim"], 1e-4) == []


def test_seam_violations_catches_a_loop_that_does_not_close():
    samples = [
        {"clip": "pulse_swim", "frame": 0, "rim_diameter": 1.2,
         "apex_to_tip": 3.9},
        {"clip": "pulse_swim", "frame": 15, "rim_diameter": 0.9,
         "apex_to_tip": 3.7},
        {"clip": "pulse_swim", "frame": 30, "rim_diameter": 1.2,
         "apex_to_tip": 3.8},
    ]
    bad = dm.seam_violations(samples, ["pulse_swim"], 1e-4)
    assert len(bad) == 1
    assert bad[0]["metric"] == "apex_to_tip"
    assert abs(bad[0]["delta"] - 0.1) < 1e-9


def test_histogram_facts_counts_vertices_over_four():
    buckets = [{"influences": 2, "vertices": 100},
               {"influences": 4, "vertices": 50},
               {"influences": 6, "vertices": 7}]
    facts = dm.histogram_facts(buckets)
    assert facts == {"max_influences": 6, "vertices": 157, "over_four": 7}


def test_histogram_facts_on_a_bind_that_never_exceeds_four():
    buckets = [{"influences": 3, "vertices": 10},
               {"influences": 4, "vertices": 20}]
    assert dm.histogram_facts(buckets)["over_four"] == 0
