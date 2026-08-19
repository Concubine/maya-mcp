"""Rigging handlers (#602 phase 1) - orchestration under a FakeCmds.

Real joints, real skinClusters and real deformation are mayapy's job
(tests/test_handlers_mayapy.py); this file pins the call SEQUENCE: one
checkpoint, unique naming, parent selection order, measured-not-echoed
reporting, and every refusal path.
"""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import rigging, session


class FakeCmds:
    def __init__(self, angle_unit="deg"):
        self.objects = []
        self.calls = []
        self.attrs = {}
        self.parents = {}       # child long -> parent long
        self._angle_unit = angle_unit
        self.selection = []
        self.node_types = {}   # explicit overrides; unset defaults to "joint"
        self.skin_history = []  # set by tests: skinClusters in the mesh's history
        self.skin_clusters = []  # set by tests: all skinClusters in the scene,
                                  # what cmds.ls(type="skinCluster") returns
        self.skin_influences = {}  # sc name -> [joint long names]
        self.skin_geometry = {}    # sc name -> [shape long names]
        self.bind_poses = []    # set by tests: dagPose(query=True, bindPose=True)

    # --- names
    def objExists(self, name):
        return any(o.split("|")[-1] == name or o == name for o in self.objects)

    def ls(self, pattern=None, long=False, type=None, **kw):
        if type == "skinCluster":
            if pattern is None:
                # cmds.ls(type="skinCluster"): every skinCluster in the scene,
                # for _bound_meshes to scan.
                return list(self.skin_clusters)
            # mirrors cmds.ls(history_nodes, type="skinCluster"): the fake's
            # listHistory already returns only skinClusters, so the input
            # list IS the filtered result - present only when a bind exists.
            nodes = pattern if isinstance(pattern, list) else ([pattern] if pattern else [])
            return list(nodes) if self.skin_history else []
        if pattern is None:
            return list(self.objects)
        names = pattern if isinstance(pattern, list) else [pattern]
        out = []
        for n in names:
            matches = [o for o in self.objects
                      if o == n or o.split("|")[-1] == n]
            out.extend(matches or [n])
        return out

    def nodeType(self, node):
        if node in self.node_types:
            return self.node_types[node]
        # a shape node (by naming convention, "...Shape") is a mesh unless a
        # test says otherwise; anything else defaults to "joint" - the fake
        # never has to know about "transform" until a test asks for one.
        return "mesh" if "Shape" in node.split("|")[-1] else "joint"

    # --- creation
    def select(self, *args, **kw):
        if kw.get("clear"):
            self.selection = []
        elif args:
            self.selection = list(args)
        self.calls.append(("select", tuple(args), kw.get("clear", False)))

    def joint(self, *args, **kw):
        if kw.get("edit"):
            self.calls.append(("joint_edit", args, kw))
            return None
        name = kw["name"]
        parent = self.selection[0] if self.selection else None
        long = (parent + "|" + name) if parent else ("|" + name)
        self.objects.append(long)
        self.parents[long] = parent
        self.attrs[long + ".jointOrient"] = [(0.0, 0.0, 0.0)]
        self.calls.append(("joint", name, tuple(kw["position"]), parent))
        return name

    def listRelatives(self, node, children=False, allDescendents=False,
                      type=None, fullPath=False, **kw):
        kids = [o for o, p in self.parents.items() if p == node]
        if allDescendents:
            out = []
            frontier = list(kids)
            while frontier:
                k = frontier.pop()
                out.append(k)
                frontier.extend(o for o, p in self.parents.items() if p == k)
            return out or None
        return kids or None

    def xform(self, node, query=False, worldSpace=False, translation=False, **kw):
        self.calls.append(("xform_query", node))
        return [1.0, 2.0, 3.0]  # deliberately NOT the input - proves measurement

    def setAttr(self, plug, *values, **kw):
        self.attrs[plug] = [tuple(values)] if len(values) == 3 else list(values)
        self.calls.append(("setAttr", plug, values))

    def getAttr(self, plug, type=False, **kw):
        if type:
            return "doubleAngle"
        return self.attrs.get(plug, [(0.0, 0.0, 0.0)])

    def currentUnit(self, query=False, angle=False, linear=False, **kw):
        return self._angle_unit if angle else "cm"

    # --- binding
    def listHistory(self, node, pruneDagObjects=False, **kw):
        self.calls.append(("listHistory", node))
        return list(self.skin_history)

    def skinCluster(self, *args, **kw):
        self.calls.append(("skinCluster", args, kw))
        if kw.get("query"):
            sc = args[0] if args else None
            if kw.get("influence"):
                return list(self.skin_influences.get(sc, []))
            if kw.get("geometry"):
                return list(self.skin_geometry.get(sc, []))
            return None
        return ["fakeSkin1"]

    # --- posing
    def dagPose(self, *args, query=False, bindPose=False, restore=False, **kw):
        self.calls.append(("dagPose", args,
                          dict(kw, query=query, bindPose=bindPose, restore=restore)))
        if query and bindPose:
            return list(self.bind_poses)
        return None


@pytest.fixture
def fake(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(rigging, "_cmds", lambda: fake)
    monkeypatch.setattr(session, "auto_checkpoint",
                        lambda reason: {"checkpoint_id": "001_" + reason,
                                        "path": "x.ma"})
    return fake


class TestCreateSkeleton:
    def test_chain_parents_each_joint_under_the_previous(self, fake):
        out = rigging.create_skeleton({
            "chain": [[0, 0, 0], [0, 1, 0], [0, 2, 0]], "chain_prefix": "s"})
        made = [c for c in fake.calls if c[0] == "joint"]
        assert [m[1] for m in made] == ["s_01", "s_02", "s_03"]
        assert made[0][3] is None
        assert made[1][3] == "|s_01"
        assert out["root"] == "|s_01"
        assert [j["parent"] for j in out["joints"]] == [None, "|s_01", "|s_01|s_02"]

    def test_positions_are_measured_back_not_echoed(self, fake):
        out = rigging.create_skeleton({"chain": [[0, 0, 0], [0, 9, 0]]})
        assert out["joints"][0]["position"] == [1.0, 2.0, 3.0]

    def test_one_checkpoint_before_any_joint(self, fake, monkeypatch):
        events = []
        monkeypatch.setattr(session, "auto_checkpoint",
                            lambda reason: events.append("checkpoint") or
                            {"checkpoint_id": "001", "path": "x.ma"})
        real_joint = fake.joint
        def logged_joint(*a, **kw):
            events.append("joint")
            return real_joint(*a, **kw)
        fake.joint = logged_joint
        rigging.create_skeleton({"chain": [[0, 0, 0], [0, 1, 0]]})
        assert events[0] == "checkpoint"
        assert events.count("checkpoint") == 1

    def test_a_name_collision_warns_and_renames(self, fake):
        fake.objects.append("|s_01")
        fake.parents["|s_01"] = None
        out = rigging.create_skeleton({"chain": [[0, 0, 0], [0, 1, 0]],
                                       "chain_prefix": "s"})
        assert any("s_01" in w for w in out["warnings"])
        made = [c[1] for c in fake.calls if c[0] == "joint"]
        assert "s_01_001" in made

    def test_validation_failure_costs_nothing(self, fake, monkeypatch):
        monkeypatch.setattr(session, "auto_checkpoint",
                            lambda reason: pytest.fail("checkpointed a bad call"))
        with pytest.raises(HandlerError):
            rigging.create_skeleton({"chain": [[0, 0, 0]]})
        assert fake.objects == []


class TestBindSkinValidation:
    def _mesh(self, fake):
        fake.objects.append("|serpent")
        fake.shapes = {"|serpent": "|serpent|serpentShape"}
        def listRelatives(node, shapes=False, **kw):
            if shapes:
                return [fake.shapes.get(node)]
            return FakeCmds.listRelatives(fake, node, **kw)
        fake.listRelatives = listRelatives

    def test_root_must_be_a_joint(self, fake):
        self._mesh(fake)
        fake.objects.append("|not_a_joint")
        fake.node_types = {"|not_a_joint": "transform"}
        with pytest.raises(HandlerError, match="not a joint"):
            rigging.bind_skin({"mesh": "serpent", "root": "not_a_joint"})

    def test_unknown_method_lists_the_valid_ones(self, fake):
        self._mesh(fake)
        fake.objects.append("|root_j")
        with pytest.raises(HandlerError, match="closestDistance"):
            rigging.bind_skin({"mesh": "serpent", "root": "root_j",
                               "method": "psychic"})

    def test_max_influences_bounds(self, fake):
        self._mesh(fake)
        fake.objects.append("|root_j")
        with pytest.raises(HandlerError, match="max_influences"):
            rigging.bind_skin({"mesh": "serpent", "root": "root_j",
                               "max_influences": 0})

    def test_rebind_is_refused_with_the_unbind_hint(self, fake):
        self._mesh(fake)
        fake.objects.append("|root_j")
        fake.skin_history = ["oldSkin"]
        with pytest.raises(HandlerError, match="already bound") as err:
            rigging.bind_skin({"mesh": "serpent", "root": "root_j"})
        assert "unbind" in err.value.hint


class TestPoseValidation:
    def _skeleton(self, fake):
        fake.objects += ["|r", "|r|a"]
        fake.parents = {"|r|a": "|r"}

    def test_space_other_than_local_is_refused(self, fake):
        self._skeleton(fake)
        with pytest.raises(HandlerError, match="space"):
            rigging.pose_skeleton({"root": "r", "space": "world",
                                   "rotations": {"a": [0, 0, 10]}})

    def test_empty_rotations_refused(self, fake):
        self._skeleton(fake)
        with pytest.raises(HandlerError, match="rotations"):
            rigging.pose_skeleton({"root": "r", "rotations": {}})

    def test_a_joint_outside_the_root_is_refused_by_name(self, fake):
        self._skeleton(fake)
        with pytest.raises(HandlerError, match="stranger"):
            rigging.pose_skeleton({"root": "r",
                                   "rotations": {"stranger": [0, 0, 10]}})

    def test_rotations_reach_maya_in_scene_units(self, fake):
        import math
        fake._angle_unit = "rad"
        self._skeleton(fake)
        rigging.pose_skeleton({"root": "r", "rotations": {"a": [0, 0, 90]}})
        wrote = [c for c in fake.calls
                 if c[0] == "setAttr" and c[1] == "|r|a.rotate"]
        assert wrote[0][2][2] == pytest.approx(math.pi / 2)

    def test_no_bound_mesh_is_a_warning_not_silence(self, fake):
        self._skeleton(fake)
        out = rigging.pose_skeleton({"root": "r", "rotations": {"a": [0, 0, 10]}})
        assert any("no skinned mesh" in w for w in out["warnings"])
        assert out["max_displacement"] == 0.0

    def test_a_unique_short_name_resolves_to_its_joint(self, fake):
        fake.objects += ["|r", "|r|arm"]
        fake.parents["|r|arm"] = "|r"
        out = rigging.pose_skeleton({"root": "r", "rotations": {"arm": [0, 0, 10]}})
        wrote = [c for c in fake.calls
                 if c[0] == "setAttr" and c[1] == "|r|arm.rotate"]
        assert wrote
        assert out["applied"] == 1

    def test_two_spellings_of_the_same_joint_are_refused(self, fake):
        fake.objects += ["|r", "|r|arm"]
        fake.parents["|r|arm"] = "|r"
        with pytest.raises(HandlerError, match="twice") as err:
            rigging.pose_skeleton({
                "root": "r",
                "rotations": {"arm": [0, 0, 10], "|r|arm": [0, 0, 20]}})
        assert "|r|arm" in str(err.value)

    def test_an_ambiguous_short_name_is_refused_with_the_long_name_fix(self, fake):
        fake.objects += ["|r", "|r|a", "|r|b", "|r|a|tip", "|r|b|tip"]
        fake.parents.update({
            "|r|a": "|r",
            "|r|b": "|r",
            "|r|a|tip": "|r|a",
            "|r|b|tip": "|r|b",
        })
        with pytest.raises(HandlerError, match="ambiguous") as err:
            rigging.pose_skeleton({"root": "r", "rotations": {"tip": [0, 0, 10]}})
        assert "|r|a|tip" in err.value.hint


class TestResetPose:
    def test_unbound_skeleton_zeroes_rotations_with_a_warning(self, fake):
        fake.objects += ["|r", "|r|a"]
        fake.parents = {"|r|a": "|r"}
        out = rigging.reset_pose({"root": "r"})
        assert out["reset"] is True
        assert any("no bind pose" in w for w in out["warnings"])
        zeroed = [c for c in fake.calls
                  if c[0] == "setAttr" and c[1].endswith(".rotate")]
        assert len(zeroed) == 2


class TestWeightReport:
    def _bound_mesh(self, fake, monkeypatch):
        fake.objects.append("|serpent")
        fake.shapes = {"|serpent": "|serpent|serpentShape"}
        def listRelatives(node, shapes=False, **kw):
            if shapes:
                return [fake.shapes.get(node)]
            return FakeCmds.listRelatives(fake, node, **kw)
        fake.listRelatives = listRelatives
        fake.skin_history = ["skin1"]
        fake.attrs["skin1.maxInfluences"] = 4
        # 3 verts x 2 joints: v2 unweighted
        monkeypatch.setattr(
            rigging, "_skin_weights",
            lambda sc, shape: (["|r|a", "|r|b"],
                               [1.0, 0.0, 0.6, 0.4, 0.0, 0.0], 3))

    def test_report_is_measured_and_never_checkpoints(self, fake, monkeypatch):
        self._bound_mesh(fake, monkeypatch)
        monkeypatch.setattr(session, "auto_checkpoint",
                            lambda reason: pytest.fail("a measurement checkpointed"))
        out = rigging.weight_report({"mesh": "serpent"})
        assert out["skin_cluster"] == "skin1"
        assert out["vertices"] == 3
        assert out["max_influences"] == 4
        assert out["unweighted_vertices"] == 1
        assert out["unweighted_sample"] == [2]
        assert any("belong to NO joint" in w for w in out["warnings"])

    def test_unbound_mesh_is_refused_with_the_bind_hint(self, fake, monkeypatch):
        self._bound_mesh(fake, monkeypatch)
        fake.skin_history = []
        with pytest.raises(HandlerError, match="not bound") as err:
            rigging.weight_report({"mesh": "serpent"})
        assert "bind_skin" in err.value.hint


class TestMirrorWeights:
    def _bound(self, fake, monkeypatch,
               positions=(1.0, 0.5, 0.0,  -1.0, 0.5, 0.0),
               weights=(0.0, 1.0, 0.0,     1.0, 0.0, 0.0),
               joints=("|r", "|r|L_a", "|r|R_a"),
               joint_pos=((0.0, 1, 0), (0.5, 1, 0), (-0.5, 1, 0))):
        fake.objects.append("|hum")
        fake.shapes = {"|hum": "|hum|humShape"}
        def listRelatives(node, shapes=False, **kw):
            if shapes:
                return [fake.shapes.get(node)]
            return FakeCmds.listRelatives(fake, node, **kw)
        fake.listRelatives = listRelatives
        fake.skin_history = ["skin1"]
        fake.attrs["skin1.maxInfluences"] = 4
        for j, p in zip(joints, joint_pos):
            fake.attrs[j + ".rotate"] = [(0.0, 0.0, 0.0)]
        state = {"weights": list(weights)}
        monkeypatch.setattr(
            rigging, "_skin_weights",
            lambda sc, shape: (list(joints), list(state["weights"]),
                               len(positions) // 3))
        written = {}
        def set_weights(sc, shape, ncols, table):
            written["table"] = list(table)
            state["weights"] = list(table)
        monkeypatch.setattr(rigging, "_set_skin_weights", set_weights)
        from maya_plugin.handlers import sculpt
        monkeypatch.setattr(sculpt, "vertex_positions",
                            lambda cmds, mesh: list(positions))
        jp = {j: list(p) for j, p in zip(joints, joint_pos)}
        def xform(node, query=False, worldSpace=False, translation=False, **kw):
            return jp.get(node, [0.0, 0.0, 0.0])
        fake.xform = xform
        return written

    def test_mirror_writes_swapped_columns_and_measures_back(self, fake, monkeypatch):
        written = self._bound(fake, monkeypatch)
        out = rigging.mirror_weights({"mesh": "hum"})
        assert written["table"][3:6] == [0.0, 0.0, 1.0]   # L column -> R column
        assert out["mirrored_vertices"] == 1
        assert out["changed_vertices"] == 1
        assert out["unweighted_vertices"] == 0

    def test_unknown_axis_and_direction_are_refused(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        with pytest.raises(HandlerError, match="axis"):
            rigging.mirror_weights({"mesh": "hum", "axis": "w"})
        with pytest.raises(HandlerError, match="direction"):
            rigging.mirror_weights({"mesh": "hum", "direction": "sideways"})

    def test_an_asymmetric_skeleton_is_refused_by_name(self, fake, monkeypatch):
        self._bound(fake, monkeypatch,
                    joints=("|r", "|r|L_a"),
                    joint_pos=((0.0, 1, 0), (0.5, 1, 0)),
                    weights=(0.0, 1.0, 1.0, 0.0))
        with pytest.raises(HandlerError, match="no mirror partner") as err:
            rigging.mirror_weights({"mesh": "hum"})
        assert "L_a" in str(err.value)

    def test_unpaired_vertices_warn_but_do_not_refuse(self, fake, monkeypatch):
        self._bound(fake, monkeypatch,
                    positions=(1.0, 0.5, 0.0,  -1.0, 0.5, 0.0,  2.0, 9.0, 0.0),
                    weights=(0.0, 1.0, 0.0,  1.0, 0.0, 0.0,  0.0, 1.0, 0.0))
        out = rigging.mirror_weights({"mesh": "hum"})
        assert out["unpaired_vertices"] == 1
        assert any("unpaired" in w for w in out["warnings"])

    def test_a_posed_skeleton_warns_before_mirroring(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        fake.attrs["|r|L_a.rotate"] = [(0.0, 0.0, 30.0)]
        out = rigging.mirror_weights({"mesh": "hum"})
        assert any("posed" in w for w in out["warnings"])

    def test_mirror_checkpoints_once_after_validation(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        events = []
        monkeypatch.setattr(session, "auto_checkpoint",
                            lambda reason: events.append(reason) or
                            {"checkpoint_id": "001", "path": "x.ma"})
        rigging.mirror_weights({"mesh": "hum"})
        assert events == ["mirror_weights"]
