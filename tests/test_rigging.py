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
        self.positions = {}    # node long name -> [x, y, z] for xform queries
        self.matrices = {}     # node long name -> 16 floats for matrix queries

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

    def listRelatives(self, node, children=False, parent=False,
                      allDescendents=False, type=None, fullPath=False, **kw):
        if parent:
            p = self.parents.get(node)
            return [p] if p else None
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

    def xform(self, node, query=False, worldSpace=False, translation=False,
              matrix=False, **kw):
        if query and matrix:
            self.calls.append(("xform_matrix", node))
            return self.matrices.get(
                node, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
        if not query and not isinstance(translation, bool):
            self.calls.append(("xform_set", node, tuple(translation)))
            return None
        self.calls.append(("xform_query", node))
        return list(self.positions.get(node, [1.0, 2.0, 3.0]))

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

    def ikHandle(self, startJoint=None, endEffector=None, solver=None,
                 name=None, **kw):
        handle, effector = "|" + name, "|" + name + "_eff"
        self.objects.extend([handle, effector])
        self.calls.append(("ikHandle", startJoint, endEffector, solver, name))
        return [handle, effector]

    def spaceLocator(self, name=None, **kw):
        self.objects.append("|" + name)
        self.calls.append(("spaceLocator", name))
        return ["|" + name]

    def poleVectorConstraint(self, locator, handle, **kw):
        self.calls.append(("poleVectorConstraint", locator, handle))
        return [handle + "_pvc"]

    def delete(self, *names, **kw):
        self.calls.append(("delete", names))
        for n in names:
            if n in self.objects:
                self.objects.remove(n)

    # --- posing
    def dagPose(self, *args, query=False, bindPose=False, restore=False, **kw):
        self.calls.append(("dagPose", args,
                          dict(kw, query=query, bindPose=bindPose, restore=restore)))
        if query and bindPose:
            return list(self.bind_poses)
        return None

    def attributeQuery(self, attr, node=None, exists=False):
        # For clip metadata check - always return False (no mcp_clip attr)
        if exists:
            return False
        return None

    def listConnections(self, plug, source=False, destination=True,
                        type=None):
        if plug in getattr(self, "curve_plugs", ()):
            return [plug.replace("|", "_").replace(".", "_") + "_crv"]
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


class TestPosePerMesh:
    def test_reset_with_two_bind_poses_warns_and_restores_the_first(self, fake):
        fake.objects += ["|r", "|r|a"]
        fake.parents = {"|r|a": "|r"}
        fake.bind_poses = ["bindPose1", "bindPose2"]
        out = rigging.reset_pose({"root": "r"})
        assert any("2 bind poses" in w for w in out["warnings"])
        restored = [c for c in fake.calls
                    if c[0] == "dagPose" and c[2].get("restore")]
        assert restored and restored[0][1][0] == "bindPose1"

    def test_pose_reports_per_mesh_and_names_the_inert_one(self, fake, monkeypatch):
        fake.objects += ["|r", "|r|a"]
        fake.parents = {"|r|a": "|r"}
        fake.skin_clusters = ["scA", "scB"]
        fake.skin_influences = {"scA": ["|r|a"], "scB": ["|r|a"]}
        fake.skin_geometry = {"scA": ["|meshA|meshAShape"],
                              "scB": ["|meshB|meshBShape"]}
        fake.objects += ["|meshA", "|meshB"]
        fake.parents.update({"|meshA|meshAShape": "|meshA",
                             "|meshB|meshBShape": "|meshB"})
        # _bound_meshes asks a shape for its parent transform; the base fake
        # only answers children queries.
        def listRelatives(node, parent=False, fullPath=False, **kw):
            if parent:
                p = fake.parents.get(node)
                return [p] if p else None
            return FakeCmds.listRelatives(fake, node, **kw)
        fake.listRelatives = listRelatives
        from maya_plugin.handlers import sculpt
        state = {"posed": False}
        def positions(cmds, mesh):
            # meshA moves 1.0 when posed; meshB never moves.
            if mesh == "|meshA" and state["posed"]:
                return [0.0, 1.0, 0.0,  0.0, 3.0, 0.0]
            if mesh == "|meshA":
                return [0.0, 0.0, 0.0,  0.0, 2.0, 0.0]
            return [5.0, 0.0, 0.0,  5.0, 2.0, 0.0]
        monkeypatch.setattr(sculpt, "vertex_positions", positions)
        real_set = fake.setAttr
        def set_attr(plug, *values, **kw):
            state["posed"] = True
            return real_set(plug, *values, **kw)
        fake.setAttr = set_attr
        out = rigging.pose_skeleton({"root": "r",
                                     "rotations": {"a": [0, 0, 30]}})
        assert len(out["per_mesh"]) == 2
        by_mesh = {m["mesh"]: m for m in out["per_mesh"]}
        assert by_mesh["|meshA"]["max_displacement"] == pytest.approx(1.0)
        assert by_mesh["|meshB"]["max_displacement"] == 0.0
        assert out["max_displacement"] == pytest.approx(1.0)
        assert any("meshB" in w and "near-zero" in w for w in out["warnings"])


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


class TestSmoothWeights:
    def _bound(self, fake, monkeypatch, weights, joints=("|r|a", "|r|b"),
               adjacency=((1,), (0, 2), (1,))):
        fake.objects.append("|hum")
        fake.shapes = {"|hum": "|hum|humShape"}
        def listRelatives(node, shapes=False, **kw):
            if shapes:
                return [fake.shapes.get(node)]
            return FakeCmds.listRelatives(fake, node, **kw)
        fake.listRelatives = listRelatives
        fake.skin_history = ["skin1"]
        fake.attrs["skin1.maxInfluences"] = 4
        for j in joints:
            fake.attrs[j + ".rotate"] = [(0.0, 0.0, 0.0)]
        state = {"weights": list(weights)}
        monkeypatch.setattr(
            rigging, "_skin_weights",
            lambda sc, shape: (list(joints), list(state["weights"]),
                               len(weights) // len(joints)))
        def set_weights(sc, shape, ncols, table):
            state["weights"] = list(table)
        monkeypatch.setattr(rigging, "_set_skin_weights", set_weights)
        monkeypatch.setattr(rigging, "_vertex_adjacency",
                            lambda shape: [list(a) for a in adjacency])
        return state

    def test_smooth_measures_what_changed(self, fake, monkeypatch):
        state = self._bound(fake, monkeypatch,
                            [1.0, 0.0, 1.0, 0.0, 0.0, 1.0])
        out = rigging.smooth_weights({"mesh": "hum"})
        assert out["iterations"] == 1
        assert out["smoothed_vertices"] == 3
        assert out["changed_vertices"] >= 1
        assert out["unweighted_vertices"] == 0
        assert state["weights"][2:4] == pytest.approx([0.75, 0.25])

    def test_joints_filter_selects_rows_by_held_weight(self, fake, monkeypatch):
        self._bound(fake, monkeypatch, [1.0, 0.0, 1.0, 0.0, 0.0, 1.0])
        out = rigging.smooth_weights({"mesh": "hum", "joints": ["b"]})
        # only v2 holds b -> only v2 is a smoothing target
        assert out["smoothed_vertices"] == 1

    def test_unknown_joint_is_refused_with_candidates(self, fake, monkeypatch):
        self._bound(fake, monkeypatch, [1.0, 0.0, 1.0, 0.0, 0.0, 1.0])
        with pytest.raises(HandlerError, match="not an influence") as err:
            rigging.smooth_weights({"mesh": "hum", "joints": ["nope"]})
        assert "a" in err.value.hint

    def test_iterations_bounds(self, fake, monkeypatch):
        self._bound(fake, monkeypatch, [1.0, 0.0, 1.0, 0.0, 0.0, 1.0])
        with pytest.raises(HandlerError, match="iterations"):
            rigging.smooth_weights({"mesh": "hum", "iterations": 0})
        with pytest.raises(HandlerError, match="iterations"):
            rigging.smooth_weights({"mesh": "hum", "iterations": 999})


class TestSetRegionWeights:
    def _bound(self, fake, monkeypatch,
               positions=(0.0, 0.0, 0.0,  1.0, 0.0, 0.0),
               weights=(0.5, 0.5, 0.5, 0.5),
               joints=("|r|a", "|r|b")):
        fake.objects.append("|hum")
        fake.shapes = {"|hum": "|hum|humShape"}
        def listRelatives(node, shapes=False, **kw):
            if shapes:
                return [fake.shapes.get(node)]
            return FakeCmds.listRelatives(fake, node, **kw)
        fake.listRelatives = listRelatives
        fake.skin_history = ["skin1"]
        fake.attrs["skin1.maxInfluences"] = 4
        for j in joints:
            fake.attrs[j + ".rotate"] = [(0.0, 0.0, 0.0)]
        state = {"weights": list(weights)}
        monkeypatch.setattr(
            rigging, "_skin_weights",
            lambda sc, shape: (list(joints), list(state["weights"]),
                               len(positions) // 3))
        def set_weights(sc, shape, ncols, table):
            state["weights"] = list(table)
        monkeypatch.setattr(rigging, "_set_skin_weights", set_weights)
        from maya_plugin.handlers import sculpt
        monkeypatch.setattr(sculpt, "vertex_positions",
                            lambda cmds, mesh: list(positions))
        fake.face_count = 4
        def polyEvaluate(mesh, face=False, vertex=False, **kw):
            return fake.face_count if face else len(positions) // 3
        fake.polyEvaluate = polyEvaluate
        def plcc(*comps, fromFace=False, toVertex=False, **kw):
            return ["|hum.vtx[0]"]
        fake.polyListComponentConversion = plcc
        return state

    def test_radius_mode_blends_and_reports(self, fake, monkeypatch):
        state = self._bound(fake, monkeypatch)
        out = rigging.set_region_weights({
            "mesh": "hum", "joint": "a", "within_radius_of": [0, 0, 0],
            "radius": 0.5, "weight": 1.0})
        assert out["vertices_in_region"] == 1
        assert out["changed_vertices"] == 1
        assert state["weights"][:2] == pytest.approx([1.0, 0.0])
        assert state["weights"][2:] == pytest.approx([0.5, 0.5])

    def test_faces_mode_converts_and_assigns_hard(self, fake, monkeypatch):
        state = self._bound(fake, monkeypatch)
        out = rigging.set_region_weights({
            "mesh": "hum", "joint": "b", "faces": [0], "weight": 1.0})
        assert out["vertices_in_region"] == 1
        assert state["weights"][:2] == pytest.approx([0.0, 1.0])

    def test_exactly_one_region_form(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        with pytest.raises(HandlerError, match="exactly one"):
            rigging.set_region_weights({"mesh": "hum", "joint": "a",
                                        "weight": 1.0})
        with pytest.raises(HandlerError, match="exactly one"):
            rigging.set_region_weights({
                "mesh": "hum", "joint": "a", "faces": [0],
                "within_radius_of": [0, 0, 0], "radius": 1, "weight": 1.0})

    def test_weight_bounds_and_radius_requirements(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        with pytest.raises(HandlerError, match="weight"):
            rigging.set_region_weights({"mesh": "hum", "joint": "a",
                                        "faces": [0], "weight": 1.5})
        with pytest.raises(HandlerError, match="radius"):
            rigging.set_region_weights({
                "mesh": "hum", "joint": "a", "within_radius_of": [0, 0, 0],
                "weight": 1.0})

    def test_falloff_is_a_radius_mode_concept(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        with pytest.raises(HandlerError, match="falloff"):
            rigging.set_region_weights({
                "mesh": "hum", "joint": "a", "faces": [0], "weight": 1.0,
                "falloff": "linear"})

    def test_an_empty_region_is_refused_not_a_noop(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        with pytest.raises(HandlerError, match="no vertices"):
            rigging.set_region_weights({
                "mesh": "hum", "joint": "a", "within_radius_of": [99, 99, 99],
                "radius": 0.1, "weight": 1.0})

    def test_out_of_range_face_is_refused(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        with pytest.raises(HandlerError, match="face"):
            rigging.set_region_weights({"mesh": "hum", "joint": "a",
                                        "faces": [99], "weight": 1.0})

    def test_sole_owner_vertices_is_measured_from_the_reread(
            self, fake, monkeypatch):
        # Vertex 0 is solely owned by 'a' ([1.0, 0.0]) and is the only vertex
        # within_radius_of picks up; vertex 1 is untouched (outside radius).
        state = self._bound(fake, monkeypatch, weights=(1.0, 0.0, 0.5, 0.5))
        out = rigging.set_region_weights({
            "mesh": "hum", "joint": "a", "within_radius_of": [0, 0, 0],
            "radius": 0.5, "weight": 0.6})
        # It has nobody to shed weight to, so it stays fully owned - the
        # RE-READ table (state["weights"]) proves it, not the request.
        assert state["weights"][:2] == pytest.approx([1.0, 0.0])
        assert out["sole_owner_vertices"] == 1
        assert any("solely owned by a" in w for w in out["warnings"])

        # weight == 1.0 never asks anything to shed - 0 by definition, not by
        # measurement.
        state["weights"] = [1.0, 0.0, 0.5, 0.5]
        out2 = rigging.set_region_weights({
            "mesh": "hum", "joint": "a", "within_radius_of": [0, 0, 0],
            "radius": 0.5, "weight": 1.0})
        assert out2["sole_owner_vertices"] == 0
        assert not any("solely owned" in w for w in out2["warnings"])

    def test_max_influences_exceeded_is_reported_after_blend(
            self, fake, monkeypatch):
        # Vertex 0 already holds 4 other joints at maxInfluences=4; blending
        # in a 5th adds an influence rather than dropping one - nothing
        # prunes a region blend the way smooth_weights prunes. That must be
        # surfaced, not silently left for the exporter to discover.
        joints = ("|r|a", "|r|b", "|r|c", "|r|d", "|r|e")
        self._bound(fake, monkeypatch, positions=(0.0, 0.0, 0.0),
                    weights=(0.25, 0.25, 0.25, 0.25, 0.0), joints=joints)
        out = rigging.set_region_weights({
            "mesh": "hum", "joint": "e", "faces": [0], "weight": 0.5})
        assert out["max_influences_exceeded"] == 1
        assert any("max_influences" in w for w in out["warnings"])


class TestPoseIk:
    def _rig(self, fake, bent=True):
        fake.objects = ["|pelvis", "|pelvis|hip", "|pelvis|hip|knee",
                        "|pelvis|hip|knee|ankle"]
        fake.parents = {"|pelvis|hip": "|pelvis",
                        "|pelvis|hip|knee": "|pelvis|hip",
                        "|pelvis|hip|knee|ankle": "|pelvis|hip|knee"}
        knee_z = 0.05 if bent else 0.0   # bent skips the prebend path
        fake.positions = {"|pelvis": [0.0, 1.0, 0.0],
                          "|pelvis|hip": [0.1, 0.95, 0.0],
                          "|pelvis|hip|knee": [0.1, 0.5, knee_z],
                          "|pelvis|hip|knee|ankle": [0.1, 0.08, 0.0]}

    def test_default_start_is_two_joints_up(self, fake):
        self._rig(fake)
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [0.1, 0.6, 0.2]})
        assert out["chain"] == ["|pelvis|hip", "|pelvis|hip|knee",
                                "|pelvis|hip|knee|ankle"]
        made = [c for c in fake.calls if c[0] == "ikHandle"]
        assert made == [("ikHandle", "|pelvis|hip", "|pelvis|hip|knee|ankle",
                         rigging.IK_SOLVER, "ankle_ikh")]

    def test_solve_bake_delete_order(self, fake):
        self._rig(fake)
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [0.1, 0.6, 0.2]})
        names = [c[0] for c in fake.calls]
        # the handle is moved to the target, rotations are read, the IK
        # nodes die, and ONLY THEN the rotations are re-applied as plain FK
        target_set = names.index("xform_set")
        deleted = names.index("delete")
        assert target_set < deleted
        rebakes = [i for i, c in enumerate(fake.calls)
                   if c[0] == "setAttr" and c[1].endswith(".rotate")
                   and i > deleted]
        assert len(rebakes) == 3          # one per chain joint
        # nothing IK-shaped survives
        assert not any("ikh" in o for o in fake.objects)
        assert out["kept"] is True
        assert set(out["rotations"]) == set(out["chain"])

    def test_default_pole_rides_the_bent_knee(self, fake):
        self._rig(fake, bent=True)
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [0.1, 0.6, 0.2]})
        assert out["pole_used"] is not None
        assert out["pole_used"][2] > 0            # knee bends +Z
        assert any(c[0] == "poleVectorConstraint" for c in fake.calls)

    def test_straight_chain_without_pole_warns_and_uses_no_constraint(self, fake):
        self._rig(fake, bent=False)
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [0.1, 0.6, 0.2]})
        assert out["pole_used"] is None
        assert not any(c[0] == "poleVectorConstraint" for c in fake.calls)
        assert any("STRAIGHT" in w for w in out["warnings"])

    def test_straight_chain_with_pole_prebends_the_knee(self, fake):
        self._rig(fake, bent=False)
        rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                         "target": [0.1, 0.6, 0.2], "pole": [0.1, 0.5, 0.5]})
        handle_at = [i for i, c in enumerate(fake.calls)
                     if c[0] == "ikHandle"][0]
        prebends = [i for i, c in enumerate(fake.calls)
                    if c[0] == "setAttr" and c[1] == "|pelvis|hip|knee.rotate"
                    and i < handle_at]
        assert prebends, "the interior joint must be nudged BEFORE the handle exists"
        # regression: preferredAngle seed and restore - no persistent IK state
        pa_calls = [c for c in fake.calls
                    if c[0] == "setAttr" and c[1] == "|pelvis|hip|knee.preferredAngle"]
        assert len(pa_calls) >= 2, (
            "preferredAngle must be set at least twice (seed and restore)")
        assert fake.attrs["|pelvis|hip|knee.preferredAngle"] == [(0.0, 0.0, 0.0)], (
            "the final preferredAngle must restore to the prior value")

    def test_error_inside_the_solve_window_still_cleans_up(self, fake, monkeypatch):
        # regression (#671 final review): a RuntimeError anywhere between
        # ikHandle creation and the doomed-node delete must not leave the
        # handle, effector, pole locator, or a seeded .preferredAngle behind
        # - "no persistent IK state ever exists" has to hold on the error
        # path too, not just the success path.
        self._rig(fake, bent=False)   # prebend path also seeds preferredAngle
        def boom(*a, **kw):
            raise RuntimeError("maya blew up mid-solve")
        monkeypatch.setattr(fake, "poleVectorConstraint", boom)
        with pytest.raises(RuntimeError, match="maya blew up mid-solve"):
            rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                             "target": [0.1, 0.6, 0.2], "pole": [0.1, 0.5, 0.5]})
        assert not any("ikh" in o or "pole" in o for o in fake.objects), (
            "the handle, effector, or pole locator survived the exception")
        assert fake.attrs["|pelvis|hip|knee.preferredAngle"] == [(0.0, 0.0, 0.0)], (
            "the preferredAngle seed must be restored even when the solve "
            "never finished")

    def test_out_of_reach_target_warns_with_the_reach(self, fake):
        self._rig(fake)
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [5.0, 5.0, 5.0]})
        assert any("reaches only" in w for w in out["warnings"])

    def test_keep_false_restores_and_says_so(self, fake):
        self._rig(fake)
        fake.attrs["|pelvis|hip|knee.rotate"] = [(0.0, 7.0, 0.0)]
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [0.1, 0.6, 0.2], "keep": False})
        assert out["kept"] is False
        assert fake.attrs["|pelvis|hip|knee.rotate"] == [(0.0, 7.0, 0.0)]
        assert any("keep=false" in w for w in out["warnings"])

    def test_one_checkpoint_after_validation(self, fake, monkeypatch):
        self._rig(fake)
        events = []
        monkeypatch.setattr(session, "auto_checkpoint",
                            lambda reason: events.append(reason) or
                            {"checkpoint_id": "001_" + reason, "path": "x.ma"})
        with pytest.raises(HandlerError):
            rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                             "target": "not-a-vec"})
        assert events == []
        rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                         "target": [0.1, 0.6, 0.2]})
        assert events == ["pose_ik"]

    def test_refusals(self, fake):
        self._rig(fake)
        with pytest.raises(HandlerError, match="BELOW the root"):
            rigging.pose_ik({"root": "pelvis", "joint": "pelvis",
                             "target": [0, 0, 0]})
        with pytest.raises(HandlerError, match="missing required param 'target'"):
            rigging.pose_ik({"root": "pelvis", "joint": "ankle"})
        with pytest.raises(HandlerError, match="keep must be"):
            rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                             "target": [0, 0, 0], "keep": "yes"})
        with pytest.raises(HandlerError, match="single bone"):
            rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                             "target": [0, 0, 0], "start": "knee"})
        with pytest.raises(HandlerError, match="not an ancestor"):
            rigging.pose_ik({"root": "pelvis", "joint": "knee",
                             "target": [0, 0, 0], "start": "ankle"})
        with pytest.raises(HandlerError, match="no default chain"):
            rigging.pose_ik({"root": "pelvis", "joint": "hip",
                             "target": [0, 0, 0]})
        with pytest.raises(HandlerError, match="not a joint under this root"):
            rigging.pose_ik({"root": "pelvis", "joint": "elbow",
                             "target": [0, 0, 0]})


class TestClipGuard:
    """#695: while animation curves drive the skeleton, static pose writes
    refuse - a value a curve overrides on the next frame change is the
    quietest way to lie about a pose."""

    def test_pose_skeleton_refuses_on_a_driven_skeleton(self, fake):
        fake.objects += ["|<root>", "|<root>|<child>"]
        fake.parents = {"|<root>|<child>": "|<root>"}
        fake.curve_plugs = {"|<root>|<child>.rotateZ"}
        with pytest.raises(HandlerError, match="animation curves"):
            rigging.pose_skeleton({"root": "<root>",
                                   "rotations": {"<child>": [0, 0, 10]}})

    def test_reset_pose_refuses_on_a_driven_skeleton(self, fake):
        fake.objects += ["|<root>", "|<root>|<child>"]
        fake.parents = {"|<root>|<child>": "|<root>"}
        fake.curve_plugs = {"|<root>.rotateX"}
        with pytest.raises(HandlerError, match="animation curves"):
            rigging.reset_pose({"root": "<root>"})

    def test_pose_ik_refuses_on_a_driven_skeleton(self, fake):
        fake.objects += ["|<root>", "|<root>|<mid>", "|<root>|<mid>|<tip>"]
        fake.parents = {"|<root>|<mid>": "|<root>",
                       "|<root>|<mid>|<tip>": "|<root>|<mid>"}
        fake.curve_plugs = {"|<root>|<mid>.rotateY"}
        with pytest.raises(HandlerError, match="animation curves"):
            rigging.pose_ik({"root": "<root>", "joint": "<tip>",
                             "target": [1.0, 0.0, 0.0], "start": "<root>"})

    def test_an_undriven_skeleton_poses_exactly_as_before(self, fake):
        fake.objects += ["|<root>", "|<root>|<child>"]
        fake.parents = {"|<root>|<child>": "|<root>"}
        # no curve_plugs: the ordinary happy-path pose test body, unchanged
        out = rigging.pose_skeleton({"root": "<root>",
                                     "rotations": {"<child>": [0, 0, 10]}})
        assert out["applied"] == 1


class TestBoundMeshes:
    """#720: two rig shapes are legal. A skinned mesh is found through its
    skinCluster; a rigid-parent rig (#713 - chunks parented under joints, no
    deformer at all) is found structurally. Reporting zero displacement for
    the second shape is an echo, not a measurement (#636).
    """

    @staticmethod
    def _hierarchy(fake, parents, shapes):
        """Wire the fake for shape queries and type-filtered descendants.

        The base fake answers children queries only and ignores `type`; real
        Maya excludes shapes from type="transform" and returns mesh shapes
        for shapes=True.
        """
        fake.parents = dict(parents)
        fake.shapes = dict(shapes)
        shape_nodes = set(shapes.values())

        def listRelatives(node, shapes=False, type=None, **kw):
            if shapes:
                shape = fake.shapes.get(node)
                if shape is None or type not in (None, "mesh"):
                    return None
                return [shape]
            out = FakeCmds.listRelatives(fake, node, **kw) or []
            if type == "transform":
                out = [n for n in out if n not in shape_nodes]
            return out or None
        fake.listRelatives = listRelatives

    def test_finds_rigidly_parented_children(self, fake):
        """A chunk parented under a joint moves with it, skinCluster or not."""
        self._hierarchy(
            fake,
            parents={"|root|jnt_torso": "|root",
                     "|root|jnt_torso|torso_plates": "|root|jnt_torso",
                     "|root|jnt_torso|torso_plates|torso_platesShape":
                         "|root|jnt_torso|torso_plates"},
            shapes={"|root|jnt_torso|torso_plates":
                    "|root|jnt_torso|torso_plates|torso_platesShape"})
        found = rigging._bound_meshes(fake, {"|root|jnt_torso"})
        assert found == ["|root|jnt_torso|torso_plates"]

    def test_a_chunk_under_a_descendant_joint_counts_too(self, fake):
        """The skeleton MOVES it - depth through the joint chain is not a
        reason to call the displacement zero."""
        self._hierarchy(
            fake,
            parents={"|root|jnt_a": "|root",
                     "|root|jnt_a|jnt_b": "|root|jnt_a",
                     "|root|jnt_a|jnt_b|shin": "|root|jnt_a|jnt_b",
                     "|root|jnt_a|jnt_b|shin|shinShape":
                         "|root|jnt_a|jnt_b|shin"},
            shapes={"|root|jnt_a|jnt_b|shin": "|root|jnt_a|jnt_b|shin|shinShape"})
        assert rigging._bound_meshes(fake, {"|root|jnt_a", "|root|jnt_a|jnt_b"}) \
            == ["|root|jnt_a|jnt_b|shin"]

    def test_a_shapeless_group_under_a_joint_is_not_a_mesh(self, fake):
        """Locators, empty groups and child joints are not geometry."""
        self._hierarchy(
            fake,
            parents={"|root|jnt_a": "|root",
                     "|root|jnt_a|grp_empty": "|root|jnt_a"},
            shapes={})
        assert rigging._bound_meshes(fake, {"|root|jnt_a"}) == []

    def test_a_skinned_mesh_that_is_also_a_descendant_appears_once(self, fake):
        self._hierarchy(
            fake,
            parents={"|root|jnt_a": "|root",
                     "|root|jnt_a|body": "|root|jnt_a",
                     "|root|jnt_a|body|bodyShape": "|root|jnt_a|body"},
            shapes={"|root|jnt_a|body": "|root|jnt_a|body|bodyShape"})
        fake.skin_clusters = ["skinCluster1"]
        fake.skin_influences = {"skinCluster1": ["|root|jnt_a"]}
        fake.skin_geometry = {"skinCluster1": ["|root|jnt_a|body|bodyShape"]}
        assert rigging._bound_meshes(fake, {"|root|jnt_a"}) == ["|root|jnt_a|body"]

    def test_an_unrelated_skinned_mesh_is_unaffected(self, fake):
        """The skinned path is untouched: a mesh bound to these joints but
        living outside their hierarchy still comes back."""
        self._hierarchy(
            fake,
            parents={"|root|jnt_a": "|root",
                     "|meshA|meshAShape": "|meshA"},
            shapes={"|meshA": "|meshA|meshAShape"})
        fake.skin_clusters = ["scA"]
        fake.skin_influences = {"scA": ["|root|jnt_a"]}
        fake.skin_geometry = {"scA": ["|meshA|meshAShape"]}
        assert rigging._bound_meshes(fake, {"|root|jnt_a"}) == ["|meshA"]
