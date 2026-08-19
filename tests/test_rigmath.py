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
