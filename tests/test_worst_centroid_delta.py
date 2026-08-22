"""Unit tests for worst_centroid_delta - the backward-contamination proof function.

worst_centroid_delta measures max per-axis absolute difference between two
per-frame centroid series. Its discrimination depends on an absolute quantity
(centroid) rather than a relative difference (max_displacement), which is what
makes it the actual proof that a missing backward-pin guard would be caught.
This test covers the two discrimination paths: a known constant offset and
the identical-series case.
"""

import pytest


def worst_centroid_delta(before, after):
    """Pure function from multi_take_live.py - compute max per-axis centroid
    delta across two series.
    """
    return max(abs(a["centroid"][i] - b["centroid"][i])
              for a, b in zip(before, after) for i in range(3))


class TestWorstCentroidDelta:
    def test_detects_constant_offset_on_single_axis(self):
        """A known constant offset (0.03 on one axis) should return exactly
        that offset, not a smaller or larger value. This is the case that
        proves a missing backward pin would be caught: a curve holding a
        neighbour's key backward in time introduces a uniform constant offset
        on every frame's centroid.
        """
        # Two series differing by +0.03 on Y axis (index 1)
        before = [
            {"centroid": [0.0, 1.0, 0.0]},
            {"centroid": [0.1, 1.1, 0.1]},
            {"centroid": [0.2, 1.2, 0.2]},
        ]
        after = [
            {"centroid": [0.0, 1.03, 0.0]},
            {"centroid": [0.1, 1.13, 0.1]},
            {"centroid": [0.2, 1.23, 0.2]},
        ]
        assert worst_centroid_delta(before, after) == pytest.approx(0.03)

    def test_identical_series_returns_zero(self):
        """When before and after are identical, the delta should be exactly
        zero - proving the function returns a true zero, not a near-zero that
        might sneak past a loose tolerance.
        """
        identical = [
            {"centroid": [1.0, 2.0, 3.0]},
            {"centroid": [4.0, 5.0, 6.0]},
            {"centroid": [7.0, 8.0, 9.0]},
        ]
        assert worst_centroid_delta(identical, identical) == 0.0
