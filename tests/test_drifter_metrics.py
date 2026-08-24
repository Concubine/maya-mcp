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

import pytest

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


def test_compare_samples_flags_a_nan_measured_value_as_a_violation():
    measured = [dict(s) for s in DECLARED]
    measured[1]["apex_to_tip"] = float("nan")
    bad = dm.compare_samples(DECLARED, measured, 1e-3)
    assert len(bad) == 1
    assert bad[0]["clip"] == "pulse_swim"
    assert bad[0]["frame"] == 15
    assert bad[0]["metric"] == "apex_to_tip"
    assert math.isnan(bad[0]["measured"])
    assert bad[0]["delta"] == math.inf


def test_compare_samples_flags_a_nan_declared_value_as_a_violation():
    declared = [dict(s) for s in DECLARED]
    declared[0]["rim_diameter"] = float("nan")
    measured = [dict(s) for s in DECLARED]
    bad = dm.compare_samples(declared, measured, 1e-3)
    assert len(bad) == 1
    assert bad[0]["clip"] == "pulse_swim"
    assert bad[0]["frame"] == 0
    assert bad[0]["metric"] == "rim_diameter"
    assert math.isnan(bad[0]["declared"])
    assert bad[0]["delta"] == math.inf


def test_compare_samples_deliberately_ignores_unmatched_extra_measurements():
    measured = [dict(s) for s in DECLARED]
    measured.append({"clip": "pulse_swim", "frame": 999,
                      "rim_diameter": 42.0, "apex_to_tip": 42.0})
    assert dm.compare_samples(DECLARED, measured, 1e-3) == []


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


# --- #743 landmark redesign: index-free, split-invariant, aggregate ---------
#
# The live Unity run measured why the old rule failed: Unity splits the
# drifter's 23,922 vertices into 93,344 on import, and the 12 lowest
# vertices on a tapered tendril cap sit 0.0-10.3 mm apart in DISTINCT
# positions. Picking "the lowest vertex" therefore names a different
# physical point in each engine, and the observed 0.6-12.1 mm deltas were
# exactly that candidate spread. These tests pin the replacement rule.


def test_position_key_collapses_a_split_vertex_and_its_twin():
    a = [1.0, 2.0, 3.0]
    b = [1.000001, 2.000001, 3.000001]
    assert dm.position_key(a) == dm.position_key(b)


def test_position_key_separates_genuinely_distinct_points():
    a = [1.0, 2.0, 3.0]
    b = [1.01, 2.0, 3.0]
    assert dm.position_key(a) != dm.position_key(b)


def test_dedupe_by_position_keeps_one_index_per_distinct_position():
    pts = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
    assert dm.dedupe_by_position(pts, [0, 1, 2]) == [0, 2]


def test_dedupe_by_position_preserves_input_order():
    pts = [[2.0, 0.0, 0.0], [0.0, 0.0, 0.0], [2.0, 0.0, 0.0]]
    assert dm.dedupe_by_position(pts, [0, 1, 2]) == [0, 1]


def test_low_band_selects_the_whole_ambiguous_cluster_not_one_winner():
    # Four cap vertices spread over 8 mm, plus a body vertex far above.
    pts = [[0.0, 0.000, 0.0], [0.01, 0.003, 0.0],
           [0.0, 0.006, 0.01], [0.01, 0.008, 0.01], [0.0, 1.0, 0.0]]
    got = dm.low_band_indices(pts, 0.012)
    assert got == [0, 1, 2, 3]


def test_low_band_is_unchanged_when_the_lowest_vertex_flips():
    # The exact failure mode: two near-equal candidates swap which is
    # lowest under float noise. The SET must not care.
    pts = [[0.0, 0.0000, 0.0], [0.01, 0.0001, 0.0], [0.0, 1.0, 0.0]]
    flipped = [[0.0, 0.0001, 0.0], [0.01, 0.0000, 0.0], [0.0, 1.0, 0.0]]
    assert dm.low_band_indices(pts, 0.012) == dm.low_band_indices(flipped, 0.012)


def test_high_band_selects_near_the_maximum():
    pts = [[0.0, 0.0, 0.0], [0.0, 0.99, 0.0], [0.0, 1.0, 0.0]]
    assert dm.high_band_indices(pts, 0.02) == [1, 2]


def test_centroid_averages_the_selected_points():
    pts = [[0.0, 0.0, 0.0], [2.0, 4.0, 6.0], [99.0, 99.0, 99.0]]
    c = dm.centroid(pts, [0, 1])
    assert c == (1.0, 2.0, 3.0)


def test_centroid_of_a_deduped_cap_ignores_split_duplicates():
    # Same cap, once clean and once with one vertex duplicated 3x. A raw
    # mean would drag toward the duplicate; a deduped one must not.
    clean = [[-1.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
    split = [[-1.0, 0.0, 0.0], [1.0, 0.0, 0.0],
             [-1.0, 0.0, 0.0], [-1.0, 0.0, 0.0]]
    a = dm.centroid(clean, dm.dedupe_by_position(clean, [0, 1]))
    b = dm.centroid(split, dm.dedupe_by_position(split, [0, 1, 2, 3]))
    assert abs(a[0] - b[0]) < 1e-12


def test_ring_diameter_of_a_unit_circle_is_two():
    pts = [[math.cos(t / 16.0 * 2 * math.pi), 0.0,
            math.sin(t / 16.0 * 2 * math.pi)] for t in range(16)]
    assert abs(dm.ring_diameter(pts, list(range(16))) - 2.0) < 1e-9


def test_ring_diameter_ignores_where_the_ring_sits():
    pts = [[math.cos(t / 16.0 * 2 * math.pi), 0.0,
            math.sin(t / 16.0 * 2 * math.pi)] for t in range(16)]
    moved = [[p[0] + 7.0, p[1] - 3.0, p[2] + 2.0] for p in pts]
    a = dm.ring_diameter(pts, list(range(16)))
    b = dm.ring_diameter(moved, list(range(16)))
    assert abs(a - b) < 1e-9


def test_ring_diameter_survives_one_dropped_member():
    # Robustness is the whole point: an aggregate must barely move when
    # the two engines disagree about one vertex's membership.
    pts = [[math.cos(t / 16.0 * 2 * math.pi), 0.0,
            math.sin(t / 16.0 * 2 * math.pi)] for t in range(16)]
    full = dm.ring_diameter(pts, list(range(16)))
    short = dm.ring_diameter(pts, list(range(15)))
    assert abs(full - short) < 0.02


def test_ring_diameter_refuses_an_empty_set():
    with pytest.raises(ValueError):
        dm.ring_diameter([[0.0, 0.0, 0.0]], [])


def test_rim_band_indices_rejects_the_tendril_cap_centres():
    # The measured trap: each tendril's polar cap vertex sits at the rim's
    # Y but ~0.02 m from the axis. A radius floor is what excludes them.
    pts = [[0.6, 3.0, 0.0], [-0.6, 3.0, 0.0], [0.02, 3.0, 0.0],
           [0.6, 0.5, 0.0]]
    got = dm.rim_band_indices(pts, 3.0, 0.06, 0.2)
    assert got == [0, 1]


# --- Rank selection: the producer declares cardinality --------------------
#
# MEASURED 2026-08-24, second live Unity run: band+dedupe alone still let
# the two engines disagree on SET SIZE - tip 105 in Maya vs 120 in Unity,
# rim 774 vs 784 - because a hard threshold (and the dedupe's own quantum
# grid) is boundary-sensitive under an FBX float32 round-trip. Constant
# offsets that causes are harmless, but during tendril_reach's curl the
# 15 extra tip members moved differently and pushed apex_to_tip 38 mm
# apart. A rank cut to a declared N removes the disagreement by
# construction: same count, same rule, both engines.


def test_lowest_n_takes_exactly_n_smallest_by_y():
    pts = [[0.0, 5.0, 0.0], [0.0, 1.0, 0.0], [0.0, 3.0, 0.0], [0.0, 2.0, 0.0]]
    assert dm.lowest_n(pts, [0, 1, 2, 3], 2) == [1, 3]


def test_lowest_n_breaks_ties_by_index_so_both_engines_agree():
    pts = [[0.0, 1.0, 0.0], [9.0, 1.0, 0.0], [0.0, 0.5, 0.0]]
    assert dm.lowest_n(pts, [0, 1, 2], 2) == [2, 0]


def test_lowest_n_returns_everything_when_n_exceeds_the_set():
    pts = [[0.0, 1.0, 0.0], [0.0, 2.0, 0.0]]
    assert dm.lowest_n(pts, [0, 1], 9) == [0, 1]


def test_highest_n_takes_the_largest_y():
    pts = [[0.0, 5.0, 0.0], [0.0, 1.0, 0.0], [0.0, 3.0, 0.0]]
    assert dm.highest_n(pts, [0, 1, 2], 2) == [0, 2]


def test_nearest_y_n_takes_those_closest_to_a_target_height():
    pts = [[0.0, 3.0, 0.0], [0.0, 3.5, 0.0], [0.0, 2.9, 0.0], [0.0, 9.0, 0.0]]
    assert dm.nearest_y_n(pts, [0, 1, 2, 3], 3.0, 2) == [0, 2]


def test_rank_selection_is_insensitive_to_a_widened_band():
    # The whole point: Unity searches a WIDER band than Maya so it can
    # never come up short, then cuts to Maya's declared N and lands on
    # the same members regardless of where the band edge fell.
    pts = [[0.0, float(i) * 0.001, 0.0] for i in range(50)]
    tight = dm.lowest_n(pts, dm.low_band_indices(pts, 0.012), 10)
    wide = dm.lowest_n(pts, dm.low_band_indices(pts, 0.030), 10)
    assert tight == wide
