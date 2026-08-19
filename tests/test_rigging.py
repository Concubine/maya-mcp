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

    # --- names
    def objExists(self, name):
        return any(o.split("|")[-1] == name or o == name for o in self.objects)

    def ls(self, pattern=None, long=False, type=None, **kw):
        if type == "skinCluster":
            # mirrors cmds.ls(history_nodes, type="skinCluster"): the fake's
            # listHistory already returns only skinClusters, so the input
            # list IS the filtered result - present only when a bind exists.
            nodes = pattern if isinstance(pattern, list) else ([pattern] if pattern else [])
            return list(nodes) if self.skin_history else []
        if pattern is None:
            return list(self.objects)
        return [o for o in self.objects
                if o == pattern or o.split("|")[-1] == pattern]

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
        return ["fakeSkin1"]


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
