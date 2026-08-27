"""curveform_math is pure - every rule here runs with no Maya anywhere."""
import math

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import curveform_math as cm


def sweep_params(**over):
    p = {"kind": "sweep", "name": "horn",
         "path": [[0, 0, 0], [0, 1, 0], [0, 2, 0.5]], "width": 0.4}
    p.update(over)
    return p


class TestValidateSpec:
    def test_sweep_normalizes_with_defaults(self):
        spec = cm.validate_spec(sweep_params())
        assert spec["kind"] == "sweep"
        assert spec["cap_ends"] is True
        assert spec["resolution"] == {"along": 32, "around": 16}
        assert spec["width"] == [(0.0, 0.4), (1.0, 0.4)]
        assert spec["profile_sides"] is None

    def test_unknown_kind_refused(self):
        with pytest.raises(HandlerError, match="kind"):
            cm.validate_spec({"kind": "birail", "name": "x",
                              "path": [[0, 0, 0], [1, 0, 0]]})

    def test_wrong_kinds_param_refused_with_hint(self):
        # profile on a sweep is the cross-kind mistake a caller will make
        with pytest.raises(HandlerError, match="profile"):
            cm.validate_spec(sweep_params(profile=[[0.5, 0]]))

    def test_duplicate_consecutive_path_points_refused(self):
        with pytest.raises(HandlerError, match="consecutive"):
            cm.validate_spec(sweep_params(
                path=[[0, 0, 0], [0, 0, 0], [1, 0, 0]]))

    def test_too_many_path_points_refused(self):
        pts = [[0, float(i), 0] for i in range(cm.MAX_PATH_POINTS + 1)]
        with pytest.raises(HandlerError, match=str(cm.MAX_PATH_POINTS)):
            cm.validate_spec(sweep_params(path=pts))

    def test_revolve_negative_radius_refused(self):
        with pytest.raises(HandlerError, match="radius"):
            cm.validate_spec({"kind": "revolve", "name": "vase",
                              "profile": [[0.5, 0], [-0.1, 1]]})

    def test_loft_mismatched_ring_counts_refused(self):
        with pytest.raises(HandlerError, match="ring"):
            cm.validate_spec({"kind": "loft", "name": "torso", "sections": [
                [[1, 0, 0], [0, 0, 1], [-1, 0, 0]],
                [[1, 1, 0], [0, 1, 1], [-1, 1, 0], [0, 1, -1]]]})

    def test_loft_needs_two_sections(self):
        with pytest.raises(HandlerError, match="section"):
            cm.validate_spec({"kind": "loft", "name": "torso", "sections": [
                [[1, 0, 0], [0, 0, 1], [-1, 0, 0]]]})


class TestRamps:
    def test_constant_becomes_flat_ramp(self):
        assert cm.parse_ramp(0.4, "width") == [(0.0, 0.4), (1.0, 0.4)]

    def test_unsorted_t_refused(self):
        with pytest.raises(HandlerError, match="increasing"):
            cm.parse_ramp([[0.8, 1.0], [0.2, 0.5]], "width")

    def test_t_outside_unit_range_refused(self):
        with pytest.raises(HandlerError, match=r"\[0, 1\]"):
            cm.parse_ramp([[0.0, 1.0], [1.2, 0.5]], "width")

    def test_nonpositive_width_refused(self):
        with pytest.raises(HandlerError, match="positive"):
            cm.parse_ramp([[0.0, 1.0], [1.0, 0.0]], "width")

    def test_linear_interpolation_between_stops(self):
        ramp = cm.parse_ramp([[0.0, 1.0], [1.0, 0.5]], "width")
        assert cm.ramp_value(ramp, 0.5) == pytest.approx(0.75)

    def test_clamped_outside_stops(self):
        ramp = cm.parse_ramp([[0.25, 1.0], [0.75, 0.5]], "width")
        assert cm.ramp_value(ramp, 0.0) == pytest.approx(1.0)
        assert cm.ramp_value(ramp, 1.0) == pytest.approx(0.5)


class TestChordParams:
    def test_fractions_by_arc_length_not_index(self):
        # 3 points, second segment 3x the first: t must be [0, .25, 1]
        t = cm.chord_params([[0, 0, 0], [1, 0, 0], [4, 0, 0]])
        assert t == pytest.approx([0.0, 0.25, 1.0])


class TestFaceBudget:
    def test_over_budget_refused_naming_resolution(self):
        with pytest.raises(HandlerError, match="resolution"):
            cm.validate_spec(sweep_params(
                resolution={"along": cm.MAX_ALONG + 1, "around": 8}))

    def test_predicted_faces_is_along_times_around_plus_caps(self):
        spec = cm.validate_spec(sweep_params(
            resolution={"along": 10, "around": 8}))
        assert cm.predicted_faces(spec) == 10 * 8 + 2  # + 2 cap n-gons


class TestStations:
    def test_revolve_stations_lie_on_the_surface_ring(self):
        spec = cm.validate_spec({"kind": "revolve", "name": "vase",
                                 "profile": [[0.5, 0.0], [0.3, 1.0]]})
        st = cm.station_expectations(spec)
        assert len(st) == 2 * 4  # each profile point at 4 angles
        p = st[0]
        assert p["expected"] == [0.0, 0.0]
        assert math.hypot(p["point"][0], p["point"][2]) == pytest.approx(0.5)
        assert p["point"][1] == pytest.approx(0.0)

    def test_sweep_interior_expected_is_half_width(self):
        spec = cm.validate_spec(sweep_params(
            path=[[0, 0, 0], [0, 1, 0], [0, 2, 0]],
            width=[[0.0, 1.0], [1.0, 0.5]]))
        st = cm.station_expectations(spec)
        assert len(st) == 1  # cap_ends=True drops both end stations
        lo, hi = st[0]["expected"]
        assert lo == hi == pytest.approx(0.75 / 2)  # ramp at t=0.5, halved

    def test_sweep_ngon_expected_is_apothem_to_circumradius_band(self):
        spec = cm.validate_spec(sweep_params(
            path=[[0, 0, 0], [0, 1, 0], [0, 2, 0]], width=1.0,
            profile_sides=4))
        lo, hi = cm.station_expectations(spec)[0]["expected"]
        assert hi == pytest.approx(0.5)
        assert lo == pytest.approx(0.5 * math.cos(math.pi / 4))

    def test_loft_stations_are_the_ring_points(self):
        rings = [[[1, 0, 0], [0, 0, 1], [-1, 0, 0], [0, 0, -1]],
                 [[1, 2, 0], [0, 2, 1], [-1, 2, 0], [0, 2, -1]]]
        spec = cm.validate_spec({"kind": "loft", "name": "t",
                                 "sections": rings})
        st = cm.station_expectations(spec)
        assert [s["point"] for s in st] == [p for r in rings for p in r]


class TestFormSize:
    def test_sweep_size_includes_width(self):
        spec = cm.validate_spec(sweep_params(
            path=[[0, 0, 0], [0, 4, 0]], width=1.0))
        assert cm.form_size(spec) == pytest.approx(4.0)
