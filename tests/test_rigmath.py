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
