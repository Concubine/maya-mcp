"""Pure array math: placement arithmetic with no Maya in sight.

The whole point of this module is that every number a maya_array call produces
can be predicted and checked without a running Maya. The handler tests that
follow assert only that Maya was DRIVEN correctly; correctness of the numbers
lives here.
"""

import math

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import arraymath


class TestValidation:
    def test_axis_index_maps_xyz(self):
        assert arraymath.axis_index("x") == 0
        assert arraymath.axis_index("y") == 1
        assert arraymath.axis_index("z") == 2

    def test_axis_rejects_anything_else(self):
        with pytest.raises(HandlerError):
            arraymath.axis_index("w")

    def test_count_of_one_is_rejected(self):
        # A one-element array is the source on its own: zero copies, no effect.
        # Silently succeeding here would be a no-op the caller reads as success.
        with pytest.raises(HandlerError):
            arraymath.resolve_count(1)

    def test_count_must_be_a_whole_number(self):
        with pytest.raises(HandlerError):
            arraymath.resolve_count(4.5)
        with pytest.raises(HandlerError):
            arraymath.resolve_count(True)

    def test_count_is_bounded(self):
        assert arraymath.resolve_count(arraymath.MAX_COUNT) == arraymath.MAX_COUNT
        with pytest.raises(HandlerError):
            arraymath.resolve_count(arraymath.MAX_COUNT + 1)

    def test_vec3_defaults_when_absent(self):
        assert arraymath.resolve_vec3(None, "pivot", [0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]

    def test_vec3_rejects_wrong_length(self):
        with pytest.raises(HandlerError):
            arraymath.resolve_vec3([1.0, 2.0], "offset")

    def test_vec3_rejects_booleans(self):
        # bool is an int subclass in Python; letting True through as 1.0 turns a
        # caller's type error into silently wrong geometry.
        with pytest.raises(HandlerError):
            arraymath.resolve_vec3([True, 0, 0], "offset")

    def test_vec3_with_no_default_is_required(self):
        with pytest.raises(HandlerError):
            arraymath.resolve_vec3(None, "offset")

    def test_count_of_none_says_it_is_missing_not_malformed(self):
        # #797: the wrapper now sends count=None on every call, so None is
        # "the caller said nothing", not "the caller said something odd".
        # "count must be a whole number, got None" sent the caller looking
        # for a type error in a value they never wrote.
        with pytest.raises(HandlerError) as exc:
            arraymath.resolve_count(None)
        assert "missing required param 'count'" in str(exc.value)
        assert "radial" in exc.value.hint and "linear" in exc.value.hint


class TestForeignParamsPerMode:
    """#797 rows 2-5: a param the chosen mode never reads is refused.

    Before this, nothing on the wrong mode was even validated - a probe
    passed `center=[1, 2]` (two numbers), `angle=720` and `offset="garbage"`
    through a mirror call and all three succeeded, because `_mirror` reads
    neither. The caller's arc, their taper and their spacing were accepted
    and dropped on the floor.
    """

    def test_every_mode_declares_what_it_reads(self):
        # The table and the mode list must not drift: a new mode with no row
        # here would KeyError inside the refusal instead of being checked.
        assert set(arraymath.MODE_PARAMS) == set(arraymath.MODES)

    def test_mirror_refuses_a_count(self):
        with pytest.raises(HandlerError) as exc:
            arraymath.refuse_foreign_params(
                "mirror", {"axis": "x", "count": 9})
        assert "array does not use 'count' in mirror mode" in str(exc.value)

    def test_mirror_refuses_every_placement_param_it_never_reads(self):
        for key, value in [("count", 9), ("center", [1, 2, 3]), ("angle", 720),
                           ("offset", [1, 0, 0]), ("step_rotate", [0, 1, 0]),
                           ("step_scale", [1, 1, 1])]:
            with pytest.raises(HandlerError) as exc:
                arraymath.refuse_foreign_params("mirror", {"axis": "x", key: value})
            assert "does not use %r in mirror mode" % key in str(exc.value)

    def test_radial_refuses_the_linear_and_mirror_params(self):
        for key, value in [("pivot", [0, 0, 0]), ("offset", [1, 0, 0]),
                           ("step_rotate", [0, 1, 0]), ("step_scale", [1, 1, 1])]:
            with pytest.raises(HandlerError) as exc:
                arraymath.refuse_foreign_params("radial", {"count": 3, key: value})
            assert "does not use %r in radial mode" % key in str(exc.value)

    def test_linear_refuses_the_radial_and_mirror_params(self):
        for key, value in [("axis", "y"), ("center", [0, 0, 0]), ("angle", 90),
                           ("pivot", [0, 0, 0])]:
            with pytest.raises(HandlerError) as exc:
                arraymath.refuse_foreign_params(
                    "linear", {"count": 3, "offset": [1, 0, 0], key: value})
            assert "does not use %r in linear mode" % key in str(exc.value)

    def test_each_mode_accepts_what_it_actually_reads(self):
        arraymath.refuse_foreign_params("mirror", {"axis": "x", "pivot": [0, 1, 0]})
        arraymath.refuse_foreign_params(
            "radial", {"count": 3, "axis": "y", "center": [0, 0, 0], "angle": 180})
        arraymath.refuse_foreign_params(
            "linear", {"count": 3, "offset": [1, 0, 0],
                       "step_rotate": [0, 5, 0], "step_scale": [0.9, 0.9, 0.9]})

    def test_the_common_params_are_never_foreign(self):
        arraymath.refuse_foreign_params(
            "mirror", {"name": "|tooth", "mode": "mirror", "axis": "x",
                       "name_prefix": "L_arm", "group_name": "arms"})

    def test_a_none_value_is_not_a_passed_param(self):
        # The wrapper sends every key on every call. Only `is not None` can
        # mean "the caller said this" - a key present and None must pass.
        arraymath.refuse_foreign_params(
            "mirror", {"axis": "x", "count": None, "angle": None,
                       "center": None, "offset": None, "step_rotate": None,
                       "step_scale": None})

    def test_the_named_offender_is_the_first_in_sorted_order(self):
        # Deterministic: two foreign params must not name a different one
        # run to run, or the same call refuses differently under dict order.
        with pytest.raises(HandlerError) as exc:
            arraymath.refuse_foreign_params(
                "mirror", {"axis": "x", "step_scale": [1, 1, 1], "angle": 90})
        assert "'angle'" in str(exc.value)

    def test_the_hint_names_what_the_mode_does_read(self):
        with pytest.raises(HandlerError) as exc:
            arraymath.refuse_foreign_params("mirror", {"axis": "x", "offset": [1, 0, 0]})
        assert "axis" in exc.value.hint and "pivot" in exc.value.hint
        assert "linear" in exc.value.hint


class TestZeroLinearOffset:
    def test_a_zero_offset_with_no_steps_is_refused(self):
        # #797 row 5, the value-level twin of radial's angle=0 refusal: with
        # nothing else varying per copy, every copy lands exactly on the
        # source and the array reads as a no-op.
        with pytest.raises(HandlerError) as exc:
            arraymath.refuse_zero_linear_offset({"offset": [0, 0, 0]})
        assert "array does not use 'offset' in linear mode" in str(exc.value)
        assert "on the source" in str(exc.value)

    def test_a_nonzero_offset_passes(self):
        arraymath.refuse_zero_linear_offset({"offset": [0, 0, 0.001]})

    def test_an_absent_offset_is_left_to_the_required_check(self):
        # Missing is a different failure with a different message; this
        # check must not pre-empt it.
        arraymath.refuse_zero_linear_offset({})
        arraymath.refuse_zero_linear_offset({"offset": None})

    def test_a_zero_offset_with_a_step_scale_builds_nested_shells(self):
        # NOT a no-op, and not reachable through any other mode: linear_steps
        # COMPOUNDS scale, so copy i is 0.8**i of the source, all sharing one
        # centre - concentric shells. Refusing this would refuse a real
        # request on the strength of a reason that does not apply to it.
        arraymath.refuse_zero_linear_offset(
            {"offset": [0, 0, 0], "step_scale": [0.8, 0.8, 0.8]})

    def test_a_zero_offset_with_a_step_rotate_builds_a_turning_stack(self):
        # linear_steps ACCUMULATES rotation, so the copies differ by angle
        # about their shared origin.
        arraymath.refuse_zero_linear_offset(
            {"offset": [0, 0, 0], "step_rotate": [0, 15, 0]})

    def test_the_neutral_steps_do_not_rescue_a_zero_offset(self):
        # step_rotate=[0,0,0] and step_scale=[1,1,1] are the identity: they
        # are what linear_steps defaults to, and they distinguish nothing.
        # Passing them explicitly must not buy a coincident array.
        for steps in [
            {"step_rotate": [0, 0, 0]},
            {"step_scale": [1, 1, 1]},
            {"step_rotate": [0, 0, 0], "step_scale": [1.0, 1.0, 1.0]},
            {"step_rotate": None, "step_scale": None},
        ]:
            with pytest.raises(HandlerError):
                arraymath.refuse_zero_linear_offset(
                    dict({"offset": [0, 0, 0]}, **steps))

    def test_the_message_says_which_steps_would_make_it_meaningful(self):
        with pytest.raises(HandlerError) as exc:
            arraymath.refuse_zero_linear_offset({"offset": [0, 0, 0]})
        assert "step_rotate" in str(exc.value) and "step_scale" in str(exc.value)
        assert "step_scale" in exc.value.hint

    def test_a_malformed_step_is_left_to_its_own_validator(self):
        # resolve_vec3 owns "step_scale must be three numbers". Refusing the
        # offset here would report the wrong param.
        arraymath.refuse_zero_linear_offset(
            {"offset": [0, 0, 0], "step_scale": "garbage"})
        arraymath.refuse_zero_linear_offset(
            {"offset": [0, 0, 0], "step_rotate": [0, 15]})


class TestRadialAngles:
    def test_full_circle_divides_by_count(self):
        # 4 elements around a full ring: the source at 0, copies at 90/180/270.
        # Dividing by count-1 here would put a copy back on top of the source.
        assert arraymath.radial_angles(4) == pytest.approx([90.0, 180.0, 270.0])

    def test_full_circle_returns_count_minus_one_angles(self):
        assert len(arraymath.radial_angles(12)) == 11

    def test_partial_arc_divides_by_count_minus_one(self):
        # A 180 degree arc of 3 elements spans endpoint to endpoint: 0, 90, 180.
        assert arraymath.radial_angles(3, 180.0) == pytest.approx([90.0, 180.0])

    def test_partial_arc_last_element_lands_on_the_endpoint(self):
        angles = arraymath.radial_angles(5, 90.0)
        assert angles[-1] == pytest.approx(90.0)

    def test_negative_arc_sweeps_the_other_way(self):
        assert arraymath.radial_angles(3, -180.0) == pytest.approx([-90.0, -180.0])

    def test_rejects_zero_angle(self):
        # step = angle / (count - 1) = 0 / n stacks every copy exactly on the
        # source - coincident geometry, the exact thing the full-circle rule
        # (dividing by count instead of count-1) exists to avoid at the seam.
        with pytest.raises(HandlerError) as exc:
            arraymath.radial_angles(4, 0.0)
        assert exc.value.hint


class TestRotatePoint:
    def test_right_hand_rule_about_y_takes_z_to_x(self):
        got = arraymath.rotate_point([0.0, 0.0, 1.0], "y", 90.0, [0.0, 0.0, 0.0])
        assert got == pytest.approx([1.0, 0.0, 0.0], abs=1e-9)

    def test_right_hand_rule_about_x_takes_y_to_z(self):
        got = arraymath.rotate_point([0.0, 1.0, 0.0], "x", 90.0, [0.0, 0.0, 0.0])
        assert got == pytest.approx([0.0, 0.0, 1.0], abs=1e-9)

    def test_right_hand_rule_about_z_takes_x_to_y(self):
        got = arraymath.rotate_point([1.0, 0.0, 0.0], "z", 90.0, [0.0, 0.0, 0.0])
        assert got == pytest.approx([0.0, 1.0, 0.0], abs=1e-9)

    def test_rotation_is_about_the_given_center(self):
        got = arraymath.rotate_point([6.0, 0.0, 0.0], "y", 180.0, [5.0, 0.0, 0.0])
        assert got == pytest.approx([4.0, 0.0, 0.0], abs=1e-9)

    def test_distance_from_center_is_preserved(self):
        center = [1.0, 2.0, 3.0]
        point = [4.0, 2.0, 7.0]
        moved = arraymath.rotate_point(point, "y", 37.0, center)
        before = math.dist(point, center)
        after = math.dist(moved, center)
        assert after == pytest.approx(before)


class TestLinearSteps:
    def test_returns_count_minus_one_steps(self):
        steps = arraymath.linear_steps(5, [1.0, 0.0, 0.0], [0, 0, 0], [1, 1, 1])
        assert len(steps) == 4

    def test_translation_accumulates_linearly(self):
        steps = arraymath.linear_steps(4, [2.0, 0.0, 0.0], [0, 0, 0], [1, 1, 1])
        assert [s["translate"][0] for s in steps] == pytest.approx([2.0, 4.0, 6.0])

    def test_rotation_accumulates_linearly(self):
        steps = arraymath.linear_steps(4, [0, 0, 0], [0.0, 15.0, 0.0], [1, 1, 1])
        assert [s["rotate"][1] for s in steps] == pytest.approx([15.0, 30.0, 45.0])

    def test_scale_compounds_geometrically(self):
        # Compounding, not accumulating. Linear accumulation reaches zero and
        # then goes negative, which is an inside-out mesh rather than a taper.
        steps = arraymath.linear_steps(4, [0, 0, 0], [0, 0, 0], [0.5, 0.5, 0.5])
        assert [s["scale"][0] for s in steps] == pytest.approx([0.5, 0.25, 0.125])

    def test_scale_of_one_leaves_size_alone(self):
        steps = arraymath.linear_steps(3, [1, 0, 0], [0, 0, 0], [1.0, 1.0, 1.0])
        assert all(s["scale"] == pytest.approx([1.0, 1.0, 1.0]) for s in steps)

    def test_scale_must_be_positive(self):
        with pytest.raises(HandlerError):
            arraymath.linear_steps(3, [1, 0, 0], [0, 0, 0], [0.0, 1.0, 1.0])
        with pytest.raises(HandlerError):
            arraymath.linear_steps(3, [1, 0, 0], [0, 0, 0], [-1.0, 1.0, 1.0])


class TestMirrorBbox:
    def test_reflects_and_swaps_on_the_axis(self):
        # Reflecting [1,5] about x=0 gives [-5,-1]: the max becomes the min.
        # Forgetting the swap yields an inside-out box that compares equal on
        # width and wrong on position.
        bmin, bmax = arraymath.mirror_bbox(
            [1.0, 0.0, 0.0], [5.0, 2.0, 3.0], "x", [0.0, 0.0, 0.0]
        )
        assert bmin == pytest.approx([-5.0, 0.0, 0.0])
        assert bmax == pytest.approx([-1.0, 2.0, 3.0])

    def test_other_axes_are_untouched(self):
        bmin, bmax = arraymath.mirror_bbox(
            [1.0, 7.0, -2.0], [5.0, 9.0, 4.0], "x", [0.0, 0.0, 0.0]
        )
        assert (bmin[1], bmax[1]) == pytest.approx((7.0, 9.0))
        assert (bmin[2], bmax[2]) == pytest.approx((-2.0, 4.0))

    def test_pivot_offsets_the_reflection(self):
        bmin, bmax = arraymath.mirror_bbox(
            [1.0, 0.0, 0.0], [3.0, 1.0, 1.0], "x", [10.0, 0.0, 0.0]
        )
        assert bmin[0] == pytest.approx(17.0)
        assert bmax[0] == pytest.approx(19.0)

    def test_mirroring_twice_returns_the_original(self):
        first = arraymath.mirror_bbox([1.0, 0.0, 0.0], [5.0, 2.0, 3.0], "z", [2.0, 0, 1.0])
        second = arraymath.mirror_bbox(first[0], first[1], "z", [2.0, 0, 1.0])
        assert second[0] == pytest.approx([1.0, 0.0, 0.0])
        assert second[1] == pytest.approx([5.0, 2.0, 3.0])


# A tetrahedron with outward-facing winding. Volume is exactly 1/6, which makes
# every assertion below an exact number rather than a tolerance.
TET_POINTS = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
TET_OUTWARD = [(1, 2, 3), (0, 3, 2), (0, 1, 3), (0, 2, 1)]


class TestSignedVolume:
    def test_outward_winding_is_positive(self):
        assert arraymath.signed_volume(TET_POINTS, TET_OUTWARD) == pytest.approx(1.0 / 6.0)

    def test_reversed_winding_is_negative(self):
        # This is the entire instrument: the mirror trap produces exactly this.
        flipped = [(c, b, a) for a, b, c in TET_OUTWARD]
        assert arraymath.signed_volume(TET_POINTS, flipped) == pytest.approx(-1.0 / 6.0)

    def test_translation_does_not_change_volume(self):
        moved = [(x + 10.0, y - 4.0, z + 2.5) for x, y, z in TET_POINTS]
        assert arraymath.signed_volume(moved, TET_OUTWARD) == pytest.approx(1.0 / 6.0)

    def test_scaling_cubes_the_volume(self):
        scaled = [(x * 2.0, y * 2.0, z * 2.0) for x, y, z in TET_POINTS]
        assert arraymath.signed_volume(scaled, TET_OUTWARD) == pytest.approx(8.0 / 6.0)

    def test_empty_mesh_is_zero(self):
        assert arraymath.signed_volume([], []) == 0.0
