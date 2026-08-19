"""Pure rigging math (#602 phase 1): everything establishable without a scene."""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import rigmath


class TestResolveJointsChain:
    def test_chain_becomes_a_parented_run(self):
        out = rigmath.resolve_joints({
            "chain": [[0, 0, 0], [0, 1, 0], [0, 2, 0]], "chain_prefix": "spine"})
        assert [j["name"] for j in out] == ["spine_01", "spine_02", "spine_03"]
        assert [j["parent"] for j in out] == [None, "spine_01", "spine_02"]
        assert out[1]["position"] == [0.0, 1.0, 0.0]
        assert all(j["orient"] is None for j in out)

    def test_root_name_renames_the_first_joint_only(self):
        out = rigmath.resolve_joints({
            "chain": [[0, 0, 0], [0, 1, 0]], "chain_prefix": "s",
            "root_name": "serpent_root"})
        assert out[0]["name"] == "serpent_root"
        assert out[1]["parent"] == "serpent_root"

    def test_one_position_is_not_a_chain(self):
        with pytest.raises(HandlerError, match="at least 2"):
            rigmath.resolve_joints({"chain": [[0, 0, 0]]})

    def test_chain_positions_are_validated_as_vec3(self):
        with pytest.raises(HandlerError, match="chain\\[1\\]"):
            rigmath.resolve_joints({"chain": [[0, 0, 0], [0, "x", 0]]})

    def test_both_forms_refused(self):
        with pytest.raises(HandlerError, match="exactly one"):
            rigmath.resolve_joints({
                "chain": [[0, 0, 0], [0, 1, 0]],
                "joints": [{"name": "a", "position": [0, 0, 0]}]})

    def test_neither_form_refused(self):
        with pytest.raises(HandlerError, match="exactly one"):
            rigmath.resolve_joints({})

    def test_chain_prefix_with_explicit_joints_refused(self):
        with pytest.raises(HandlerError, match="chain_prefix"):
            rigmath.resolve_joints({
                "joints": [{"name": "a", "position": [0, 0, 0]}],
                "chain_prefix": "x"})


class TestResolveJointsExplicit:
    def _one(self, **over):
        joint = {"name": "a", "position": [0, 0, 0]}
        joint.update(over)
        return joint

    def test_single_joint_skeleton_is_fine(self):
        out = rigmath.resolve_joints({"joints": [self._one()]})
        assert out == [{"name": "a", "position": [0.0, 0.0, 0.0],
                        "parent": None, "orient": None}]

    def test_orient_is_carried_through(self):
        out = rigmath.resolve_joints({"joints": [self._one(orient=[0, 0, 90])]})
        assert out[0]["orient"] == [0.0, 0.0, 90.0]

    def test_unknown_keys_refused(self):
        with pytest.raises(HandlerError, match="unknown"):
            rigmath.resolve_joints({"joints": [self._one(radius=2)]})

    def test_duplicate_names_refused(self):
        with pytest.raises(HandlerError, match="duplicate"):
            rigmath.resolve_joints({"joints": [self._one(), self._one()]})

    def test_unknown_parent_refused(self):
        with pytest.raises(HandlerError, match="ghost"):
            rigmath.resolve_joints({"joints": [self._one(parent="ghost")]})

    def test_two_roots_refused(self):
        with pytest.raises(HandlerError, match="root"):
            rigmath.resolve_joints({"joints": [
                self._one(), self._one(name="b")]})

    def test_a_cycle_is_refused_not_looped(self):
        with pytest.raises(HandlerError, match="cycle"):
            rigmath.resolve_joints({"joints": [
                self._one(name="root"),
                self._one(name="a", parent="b"),
                self._one(name="b", parent="a")]})

    def test_parents_may_be_listed_after_children(self):
        out = rigmath.resolve_joints({"joints": [
            self._one(name="hand", parent="arm"),
            self._one(name="arm", parent="root"),
            self._one(name="root")]})
        assert [j["name"] for j in out] == ["root", "arm", "hand"]

    def test_the_joint_ceiling_holds(self):
        joints = [self._one(name="j%d" % i, parent="j0" if i else None)
                  for i in range(rigmath.MAX_JOINTS + 1)]
        with pytest.raises(HandlerError, match=str(rigmath.MAX_JOINTS)):
            rigmath.resolve_joints({"joints": joints})


class TestWeightStats:
    def test_per_joint_ownership_and_means(self):
        # 3 verts x 2 joints, vertex-major.
        out = rigmath.weight_stats(
            ["|a", "|b"], [1.0, 0.0, 0.5, 0.5, 0.0, 1.0], 3, max_influences=4)
        a, b = out["per_joint"]
        assert (a["joint"], a["vertices"]) == ("|a", 2)
        assert a["mean_weight"] == pytest.approx(0.75)
        assert (b["joint"], b["vertices"]) == ("|b", 2)
        assert out["unweighted_vertices"] == 0
        assert out["max_influences_exceeded"] == 0

    def test_a_vertex_no_joint_owns_is_counted(self):
        out = rigmath.weight_stats(["|a"], [1.0, 0.0], 2, max_influences=4)
        assert out["unweighted_vertices"] == 1

    def test_float_dust_is_not_an_influence(self):
        out = rigmath.weight_stats(
            ["|a", "|b"], [1.0, rigmath.WEIGHT_TOL / 10], 1, max_influences=1)
        assert out["max_influences_exceeded"] == 0
        assert out["per_joint"][1]["vertices"] == 0

    def test_over_budget_vertices_are_counted(self):
        out = rigmath.weight_stats(
            ["|a", "|b", "|c"], [0.4, 0.3, 0.3], 1, max_influences=2)
        assert out["max_influences_exceeded"] == 1

    def test_a_joint_owning_nothing_reports_zero_mean_not_nan(self):
        out = rigmath.weight_stats(["|a", "|b"], [1.0, 0.0], 1, max_influences=4)
        assert out["per_joint"][1] == {
            "joint": "|b", "vertices": 0, "mean_weight": 0.0}

    def test_a_shape_mismatch_is_an_internal_error(self):
        with pytest.raises(ValueError):
            rigmath.weight_stats(["|a"], [1.0, 1.0, 1.0], 2, max_influences=4)


class TestDisplacedCount:
    def test_counts_only_vertices_that_moved(self):
        before = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        after = [0.0, 0.0, 0.0, 1.0, 2.0, 0.0]
        assert rigmath.displaced_count(before, after) == 1

    def test_motion_below_tol_is_rest(self):
        assert rigmath.displaced_count([0.0, 0.0, 0.0], [0.0, 1e-7, 0.0]) == 0

    def test_mismatched_lengths_are_an_internal_error(self):
        with pytest.raises(ValueError):
            rigmath.displaced_count([0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
                                    [0.0, 0.0, 0.0])

    def test_a_non_triple_length_is_an_internal_error(self):
        with pytest.raises(ValueError):
            rigmath.displaced_count([0.0, 0.0], [0.0, 0.0])


class TestRowPrimitives:
    def test_normalize_row_sums_to_one(self):
        assert rigmath.normalize_row([1.0, 3.0]) == [0.25, 0.75]

    def test_normalize_all_zero_row_stays_zero(self):
        assert rigmath.normalize_row([0.0, 0.0]) == [0.0, 0.0]

    def test_prune_keeps_the_largest_and_renormalizes(self):
        out = rigmath.prune_row([0.5, 0.3, 0.15, 0.05], 2)
        assert out == pytest.approx([0.625, 0.375, 0.0, 0.0])

    def test_prune_with_room_changes_nothing(self):
        assert rigmath.prune_row([0.6, 0.4, 0.0], 4) == pytest.approx([0.6, 0.4, 0.0])

    def test_changed_rows_counts_rows_not_cells(self):
        before = [1.0, 0.0, 0.5, 0.5]
        after = [0.0, 1.0, 0.5, 0.5]          # row 0: both cells moved
        assert rigmath.changed_rows(before, after, 2) == 1

    def test_changed_rows_ignores_float_dust(self):
        assert rigmath.changed_rows([1.0, 0.0], [1.0 - 1e-6, 1e-6], 2) == 0

    def test_changed_rows_refuses_mismatched_tables(self):
        with pytest.raises(ValueError, match="not the same"):
            rigmath.changed_rows([1.0], [1.0, 0.0], 2)


class TestWeightReportStats:
    # 3 verts x 2 joints: v0 owned by j0, v1 split, v2 unweighted
    TABLE = [1.0, 0.0,   0.6, 0.4,   0.0, 0.0]

    def test_report_carries_the_stats_plus_samples(self):
        out = rigmath.weight_report_stats(["j0", "j1"], self.TABLE, 3, 4)
        assert out["unweighted_vertices"] == 1
        assert out["unweighted_sample"] == [2]
        assert out["exceeded_sample"] == []
        assert out["per_joint"][0]["vertices"] == 2

    def test_histogram_buckets_by_influence_count(self):
        out = rigmath.weight_report_stats(["j0", "j1"], self.TABLE, 3, 4)
        assert out["histogram"] == [
            {"influences": 0, "vertices": 1},
            {"influences": 1, "vertices": 1},
            {"influences": 2, "vertices": 1}]

    def test_weight_sum_error_measures_held_rows_only(self):
        table = [0.7, 0.2,   0.0, 0.0]      # v0 sums to 0.9, v1 holds nothing
        out = rigmath.weight_report_stats(["a", "b"], table, 2, 4)
        assert out["max_weight_sum_error"] == pytest.approx(0.1)

    def test_exceeded_sample_lists_the_offenders(self):
        table = [0.4, 0.3, 0.3,   1.0, 0.0, 0.0]
        out = rigmath.weight_report_stats(["a", "b", "c"], table, 2, 2)
        assert out["max_influences_exceeded"] == 1
        assert out["exceeded_sample"] == [0]

    def test_sample_lists_are_capped(self):
        table = [0.0] * 20                   # 10 verts x 2, all unweighted
        out = rigmath.weight_report_stats(["a", "b"], table, 10, 4, sample=3)
        assert out["unweighted_vertices"] == 10
        assert out["unweighted_sample"] == [0, 1, 2]


class TestMirrorPairs:
    # 4 verts: +X pair, -X pair, on-plane, +X orphan
    POS = [1.0, 0.0, 0.0,   -1.0, 0.0, 0.0,
           0.0, 5.0, 0.0,    2.0, 9.0, 0.0]

    def test_pairs_source_positive_by_default(self):
        pairs, on_plane, unpaired = rigmath.mirror_pairs(self.POS, 0, 1e-3)
        assert pairs == [(0, 1)]
        assert on_plane == [2]
        assert unpaired == [3]

    def test_direction_reverses_source_and_destination(self):
        pairs, _, unpaired = rigmath.mirror_pairs(
            self.POS, 0, 1e-3, source_positive=False)
        assert pairs == [(1, 0)]
        assert unpaired == []          # vert 3 sits on the +X side now

    def test_tolerance_is_the_match_radius(self):
        pos = [1.0, 0.0, 0.0,   -1.0, 0.05, 0.0]
        assert rigmath.mirror_pairs(pos, 0, 1e-3)[0] == []
        assert rigmath.mirror_pairs(pos, 0, 0.1)[0] == [(0, 1)]

    def test_other_axes_reflect_their_own_coordinate(self):
        pos = [0.0, 1.0, 0.0,   0.0, -1.0, 0.0]
        assert rigmath.mirror_pairs(pos, 1, 1e-3)[0] == [(0, 1)]


class TestMirrorInfluenceMap:
    def test_bilateral_joints_pair_and_center_maps_to_self(self):
        joints = [[0.0, 1.0, 0.0], [0.5, 1.0, 0.0], [-0.5, 1.0, 0.0]]
        mapping, unmatched = rigmath.mirror_influence_map(joints, 0, 1e-3)
        assert mapping == [0, 2, 1]
        assert unmatched == []

    def test_an_off_plane_joint_without_a_partner_is_named(self):
        joints = [[0.0, 1.0, 0.0], [0.5, 1.0, 0.0]]
        mapping, unmatched = rigmath.mirror_influence_map(joints, 0, 1e-3)
        assert mapping == [0, 1]
        assert unmatched == [1]


class TestMirrorWeightTable:
    def test_source_weights_land_on_swapped_columns(self):
        # 2 verts x 3 joints (center, L, R): v0 is the +X source
        weights = [0.2, 0.8, 0.0,   1.0, 0.0, 0.0]
        out = rigmath.mirror_weight_table(
            weights, 3, [(0, 1)], [0, 2, 1])
        assert out[3:] == [0.2, 0.0, 0.8]
        assert out[:3] == [0.2, 0.8, 0.0]       # source untouched


class TestSmoothWeightTable:
    # 3 verts in a line (0-1-2), 2 joints, a hard stair-step at v1
    TABLE = [1.0, 0.0,   1.0, 0.0,   0.0, 1.0]
    ADJ = [[1], [0, 2], [1]]

    def test_one_pass_softens_the_step_and_stays_normalized(self):
        out = rigmath.smooth_weight_table(self.TABLE, 2, self.ADJ, 1, 4)
        # v1: 0.5*own(1,0) + 0.5*mean((1,0),(0,1)) = (0.75, 0.25)
        assert out[2:4] == pytest.approx([0.75, 0.25])
        assert sum(out[0:2]) == pytest.approx(1.0)
        assert sum(out[4:6]) == pytest.approx(1.0)

    def test_rows_filter_limits_who_moves(self):
        out = rigmath.smooth_weight_table(self.TABLE, 2, self.ADJ, 1, 4,
                                          rows={1})
        assert out[0:2] == pytest.approx([1.0, 0.0])   # v0 untouched
        assert out[4:6] == pytest.approx([0.0, 1.0])   # v2 untouched
        assert out[2:4] == pytest.approx([0.75, 0.25])

    def test_pruning_holds_the_influence_ceiling(self):
        table = [1.0, 0.0, 0.0,   0.0, 1.0, 0.0,   0.0, 0.0, 1.0]
        adj = [[1, 2], [0, 2], [0, 1]]
        out = rigmath.smooth_weight_table(table, 3, adj, 1, 2)
        for v in range(3):
            row = out[3 * v:3 * v + 3]
            assert sum(1 for w in row if w > rigmath.WEIGHT_TOL) <= 2
            assert sum(row) == pytest.approx(1.0)

    def test_isolated_vertices_are_left_alone(self):
        out = rigmath.smooth_weight_table([1.0, 0.0], 2, [[]], 3, 4)
        assert out == [1.0, 0.0]

    def test_more_iterations_propagate_further(self):
        # Under Jacobi, v1 is at this config's fixed point after one pass
        # (its neighbours average to its own value), so depth shows at v0:
        # one pass leaves v0 untouched (its neighbour was still hard), three
        # passes erode it through the propagated smooth.
        one = rigmath.smooth_weight_table(self.TABLE, 2, self.ADJ, 1, 4)
        three = rigmath.smooth_weight_table(self.TABLE, 2, self.ADJ, 3, 4)
        assert one[0] == pytest.approx(1.0)
        assert three[0] < one[0]


class TestRadiusFactors:
    POS = [0.0, 0.0, 0.0,   1.0, 0.0, 0.0,   3.0, 0.0, 0.0]

    def test_linear_falloff_fades_with_distance(self):
        out = rigmath.radius_factors(self.POS, [0, 0, 0], 2.0, "linear")
        assert out[0] == pytest.approx(1.0)
        assert out[1] == pytest.approx(0.5)
        assert 2 not in out

    def test_none_falloff_is_flat_inside(self):
        out = rigmath.radius_factors(self.POS, [0, 0, 0], 2.0, "none")
        assert out == {0: 1.0, 1: 1.0}


class TestApplyRegionWeights:
    def test_target_blends_and_others_rescale_proportionally(self):
        # 1 vert x 3 joints: j0 has 0.2, j1 0.6, j2 0.2 - push j0 to 0.8
        out, sole = rigmath.apply_region_weights(
            [0.2, 0.6, 0.2], 3, 0, {0: 1.0}, 0.8)
        assert out == pytest.approx([0.8, 0.15, 0.05])
        assert sole == 0

    def test_factor_scales_the_blend(self):
        out, _ = rigmath.apply_region_weights(
            [0.0, 1.0], 2, 0, {0: 0.5}, 1.0)
        assert out == pytest.approx([0.5, 0.5])

    def test_sole_owner_with_partial_weight_is_counted(self):
        out, sole = rigmath.apply_region_weights(
            [1.0, 0.0], 2, 0, {0: 1.0}, 0.6)
        assert out == pytest.approx([1.0, 0.0])   # nowhere to put the rest
        assert sole == 1

    def test_unfactored_vertices_are_untouched(self):
        out, _ = rigmath.apply_region_weights(
            [1.0, 0.0, 0.0, 1.0], 2, 0, {1: 1.0}, 1.0)
        assert out[:2] == [1.0, 0.0]
        assert out[2:] == pytest.approx([1.0, 0.0])
