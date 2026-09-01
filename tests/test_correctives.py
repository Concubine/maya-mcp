"""#771: what apply_delta_mush and add_corrective refuse and resolve.

Headless coverage stops at the validate layer (refusals, synonym hints,
defaults) plus the driven-weight guard closures - the FakeCmds here cannot
deform, and the measured behavior (chain order, edge ratios, weight ramps)
lives in tests/test_handlers_mayapy.py and the live gate.

FakeCmds is its own fake (the house rule: copied shape, never imported from
another suite). It models: |arm (shape |arm|armShape) with a skinCluster
`arm_skin` and a blendShape `arm_shapes` (aliases elbow_fix, bulge) in
history; a 3-joint chain |arm_01/|arm_01|arm_02/...; connections in a
dst-plug -> [src plugs] dict, filterable by source node type the way
listConnections(type=...) filters.
"""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import correctives


class FakeCmds:
    def __init__(self):
        self.meshes = {"|arm": "|arm|armShape"}
        self.history = {"|arm|armShape": ["arm_shapes", "arm_skin"]}
        self.types = {
            "arm_shapes": "blendShape",
            "arm_skin": "skinCluster",
            "|arm_01": "joint",
            "|arm_01|arm_02": "joint",
            "|arm_01|arm_02|arm_03": "joint",
        }
        self.aliases = {"arm_shapes": ["elbow_fix", "bulge"]}
        self.conns = {}
        self.attr_values = {}
        self.string_attrs = set()
        # #799: names this fake once held and no longer does. EVERY query
        # below consults it, because real Maya answers "No object matches
        # name" for a node that was deleted or never created - and a fake
        # that hands back a default instead is exactly how #796 shipped a
        # nodeType-after-delete crash that no headless test could see.
        self.deleted = []

    # -- naming / resolution ------------------------------------------------
    def _all(self):
        # ROUND 2 (#799): `delete` PRUNES these registries rather than
        # keeping a tombstone list this filtered against. A permanent
        # tombstone is a fake wrong in the STRICT direction - a name
        # registered again would stay invisible forever, and Maya has no
        # such memory of a deleted node.
        return (list(self.meshes) + list(self.meshes.values())
                + list(self.types))

    def _require(self, node):
        """Real Maya's answer to a query about a node that is not there."""
        if node not in self._all():
            raise RuntimeError("No object matches name: %s" % node)

    def ls(self, *args, **kw):
        if args:
            raw = args[0]
            requested = list(raw) if isinstance(raw, (list, tuple)) else [raw]
            names = []
            for n in requested:
                if n in self._all():
                    names.append(n)
                else:
                    names.extend(x for x in self._all()
                                 if x.split("|")[-1] == n)
        else:
            names = self._all()
        if kw.get("type"):
            names = [n for n in names if self.nodeType(n) == kw["type"]]
        return names

    def objExists(self, name):
        return name in self._all()

    def nodeType(self, node):
        self._require(node)
        if node in self.meshes.values():
            return "mesh"
        if node in self.types:
            return self.types[node]
        # Reachable only for a name `self.meshes` registered - i.e. a real
        # mesh transform. Not a catch-all: an unknown name raised above
        # (#799 contract point 3).
        return "transform"

    def listRelatives(self, node, shapes=False, fullPath=False,
                      noIntermediate=False, **kw):
        self._require(node)
        if shapes and node in self.meshes:
            return [self.meshes[node]]
        return None

    def listHistory(self, node, pruneDagObjects=False, **kw):
        self._require(node)
        # MEASURED (#805): a history-less shape answers None, never [] -
        # every production call site carries `or []` for exactly this.
        return list(self.history.get(node, [])) or None

    def listAttr(self, plug, multi=False, **kw):
        node = plug.split(".")[0]
        self._require(node)
        if plug.endswith(".w"):
            # None, not [], for a blendShape with no targets: that is what
            # Maya answers for an empty multi, and `or []` at the call
            # sites is what covers it (#799).
            return list(self.aliases.get(node, [])) or None
        raise AssertionError(
            "FakeCmds.listAttr models only '<blendShape>.w' - it used to "
            "answer [] for every other plug, which is a fallback no test "
            "can fail (#799)")

    def listConnections(self, plug, source=False, destination=True,
                        plugs=False, type=None, **kw):
        self._require(plug.split(".")[0])
        if not source:
            # #799: nothing in #771's handlers walks DOWNSTREAM from a
            # plug. Answering None unconditionally would let an unmodelled
            # destination query read as "nothing connected".
            raise AssertionError(
                "FakeCmds.listConnections models source queries only "
                "(#799)")
        srcs = list(self.conns.get(plug) or [])
        if type is not None:
            srcs = [s for s in srcs
                    if self.nodeType(s.split(".")[0]) == type
                    or (type == "animCurve"
                        and self.nodeType(s.split(".")[0]).startswith(
                            "animCurve"))]
        if not srcs:
            return None
        return srcs if plugs else [s.split(".")[0] for s in srcs]

    def attributeQuery(self, attr, node=None, exists=False):
        self._require(node)
        return ("%s.%s" % (node, attr)) in self.string_attrs

    def getAttr(self, plug, lock=False, **kw):
        node = plug.split(".")[0]
        self._require(node)
        if lock:
            return plug in getattr(self, "locked_plugs", set())
        if plug in self.attr_values:
            return self.attr_values[plug]
        if plug in self.string_attrs:
            return ""            # declared by addAttr, never written
        # #799: `self.attr_values.get(plug)` handed back None for any
        # unset attribute, so a handler reading a plug the fixture never
        # set up read as "empty" instead of raising the way Maya does.
        raise RuntimeError("No object matches name: %s" % plug)

    def delete(self, *names):
        # #799: deletion has to be VISIBLE to every query, or the contract
        # point that found #796's blocking defects (a vanished node raises)
        # has nothing to consult. ROUND 2: take the node OUT of the
        # registries `_all` reads - and the shape and history Maya deletes
        # with a mesh transform - instead of tombstoning the name forever.
        for name in names:
            self.deleted.append(name)     # the call record tests read
            shape = self.meshes.pop(name, None)
            for gone in [name] + ([shape] if shape else []):
                self.types.pop(gone, None)
                self.history.pop(gone, None)
                self.aliases.pop(gone, None)
                for plug in [k for k in self.conns
                             if k.split(".")[0] == gone]:
                    self.conns.pop(plug)

    def pluginInfo(self, name, query=False, loaded=False):
        return name not in getattr(self, "missing_plugins", set())

    def loadPlugin(self, name, quiet=False):
        return None


def _err(fn, *args):
    with pytest.raises(HandlerError) as e:
        fn(*args)
    return str(e.value) + " | " + str(getattr(e.value, "hint", "") or "")


# ---------------------------------------------------------------------------
# apply_delta_mush validation
# ---------------------------------------------------------------------------


class TestDeltaMushValidate:
    def test_unknown_key_synonym_names_the_real_param(self):
        msg = _err(correctives.validate_delta_mush,
                   {"mesh": "|arm", "iterations": 5}, FakeCmds())
        assert "smoothing_iterations" in msg

    def test_missing_mesh(self):
        msg = _err(correctives.validate_delta_mush, {}, FakeCmds())
        assert "mesh" in msg

    @pytest.mark.parametrize("bad", [0, 51, True, 2.5, "10"])
    def test_iterations_out_of_range_or_type(self, bad):
        msg = _err(correctives.validate_delta_mush,
                   {"mesh": "|arm", "smoothing_iterations": bad}, FakeCmds())
        assert "smoothing_iterations" in msg

    @pytest.mark.parametrize("bad", [0.0, 1.5, True, "0.5"])
    def test_step_out_of_range_or_type(self, bad):
        msg = _err(correctives.validate_delta_mush,
                   {"mesh": "|arm", "smoothing_step": bad}, FakeCmds())
        assert "smoothing_step" in msg

    def test_pin_border_must_be_bool(self):
        msg = _err(correctives.validate_delta_mush,
                   {"mesh": "|arm", "pin_border_vertices": "yes"}, FakeCmds())
        assert "pin_border_vertices" in msg

    def test_requires_skincluster(self):
        fake = FakeCmds()
        fake.history["|arm|armShape"] = ["arm_shapes"]
        msg = _err(correctives.validate_delta_mush, {"mesh": "|arm"}, fake)
        assert "skinCluster" in msg and "bind_skin" in msg

    def test_refuses_stacked_mush(self):
        fake = FakeCmds()
        fake.types["deltaMush1"] = "deltaMush"
        fake.history["|arm|armShape"] = ["deltaMush1", "arm_shapes", "arm_skin"]
        msg = _err(correctives.validate_delta_mush, {"mesh": "|arm"}, fake)
        assert "deltaMush1" in msg

    @pytest.mark.parametrize("bad", [-0.1, 1.5, True, "1"])
    def test_distance_weight_out_of_range_or_type(self, bad):
        msg = _err(correctives.validate_delta_mush,
                   {"mesh": "|arm", "distance_weight": bad}, FakeCmds())
        assert "distance_weight" in msg

    def test_defaults_resolve(self):
        plan = correctives.validate_delta_mush({"mesh": "|arm"}, FakeCmds())
        assert plan["iterations"] == 10
        assert plan["step"] == 0.5
        assert plan["pin_border"] is True
        # NOT Maya's 0.0: uniform smoothing measurably spikes anisotropic
        # edges (see the module constant's provenance comment).
        assert plan["distance_weight"] == 1.0
        assert plan["skin_cluster"] == "arm_skin"
        assert plan["mesh_long"] == "|arm"


# ---------------------------------------------------------------------------
# add_corrective validation
# ---------------------------------------------------------------------------


def _params(**over):
    base = {"mesh": "|arm", "target": "elbow_fix",
            "joint": "|arm_01|arm_02", "rotation": [0.0, 0.0, -90.0]}
    base.update(over)
    return base


class TestAddCorrectiveValidate:
    def test_unknown_key_synonym_names_rotation(self):
        msg = _err(correctives.validate_corrective,
                   _params(angle=[0, 0, -90]), FakeCmds())
        assert "rotation" in msg

    def test_no_blendshape(self):
        fake = FakeCmds()
        fake.history["|arm|armShape"] = ["arm_skin"]
        msg = _err(correctives.validate_corrective, _params(), fake)
        assert "create_blendshape" in msg

    def test_unknown_target_lists_aliases(self):
        msg = _err(correctives.validate_corrective,
                   _params(target="nope"), FakeCmds())
        assert "elbow_fix" in msg and "bulge" in msg

    def test_joint_missing(self):
        msg = _err(correctives.validate_corrective,
                   _params(joint="|nope"), FakeCmds())
        assert "nope" in msg

    def test_joint_not_a_joint(self):
        msg = _err(correctives.validate_corrective,
                   _params(joint="|arm"), FakeCmds())
        assert "joint" in msg

    @pytest.mark.parametrize("bad", [None, [0, 0], [0, 0, 0, 0],
                                     ["a", 0, 0], [True, 0, 0], 90])
    def test_rotation_shape(self, bad):
        msg = _err(correctives.validate_corrective,
                   _params(rotation=bad), FakeCmds())
        assert "rotation" in msg

    def test_zero_rotation_is_the_neutral_pose(self):
        msg = _err(correctives.validate_corrective,
                   _params(rotation=[0.0, 0.0, 0.0]), FakeCmds())
        assert "neutral" in msg

    def test_target_owned_by_clip_refuses(self):
        fake = FakeCmds()
        fake.types["curve1"] = "animCurveTU"
        fake.conns["arm_shapes.elbow_fix"] = ["curve1.output"]
        msg = _err(correctives.validate_corrective, _params(), fake)
        assert "clip" in msg.lower()

    def test_target_already_a_corrective_refuses(self):
        fake = FakeCmds()
        fake.types["elbowInterpShape"] = "poseInterpolator"
        fake.conns["arm_shapes.elbow_fix"] = ["elbowInterpShape.output[3]"]
        msg = _err(correctives.validate_corrective, _params(), fake)
        assert "elbowInterpShape" in msg and "corrective" in msg

    def test_target_driven_by_anything_else_refuses(self):
        fake = FakeCmds()
        fake.types["oddNode"] = "multiplyDivide"
        fake.conns["arm_shapes.elbow_fix"] = ["oddNode.outputX"]
        msg = _err(correctives.validate_corrective, _params(), fake)
        assert "oddNode" in msg

    def test_joint_with_anim_curves_refuses(self):
        fake = FakeCmds()
        fake.types["rotCurve"] = "animCurveTA"
        fake.conns["|arm_01|arm_02.rotateZ"] = ["rotCurve.output"]
        msg = _err(correctives.validate_corrective, _params(), fake)
        # Singular since #802 moved the diagnosis into the shared guard,
        # which names the ONE curve it found rather than a class of them.
        # The claim is unchanged: a curve is named as a curve, not folded
        # into a generic "a connection owns this".
        assert "animation curve" in msg
        assert "rotCurve" in msg

    def test_duplicate_rotation_reuses_the_existing_pose(self):
        # A second pose within a degree would ill-condition the
        # interpolation - the plan reuses the recorded pose for the new
        # target instead of refusing an ordinary rig shape (two shapes
        # riding one elbow bend).
        fake = FakeCmds()
        fake.types["elbowInterpShape"] = "poseInterpolator"
        fake.conns["elbowInterpShape.driver[0].driverMatrix"] = [
            "|arm_01|arm_02.matrix"]
        fake.string_attrs.add("elbowInterpShape.mcp_correctives")
        fake.attr_values["elbowInterpShape.mcp_correctives"] = (
            '[{"pose": "bulge", "target": "bulge", "mesh": "|arm", '
            '"blend_shape": "arm_shapes", "rotation": [0.0, 0.0, -89.5]}]')
        plan = correctives.validate_corrective(_params(), fake)
        assert plan["reuse_pose"] == "bulge"
        assert any("reusing pose" in w for w in plan["warnings"])

    def test_unreadable_record_refuses_instead_of_overwriting(self):
        fake = FakeCmds()
        fake.types["elbowInterpShape"] = "poseInterpolator"
        fake.conns["elbowInterpShape.driver[0].driverMatrix"] = [
            "|arm_01|arm_02.matrix"]
        fake.string_attrs.add("elbowInterpShape.mcp_correctives")
        fake.attr_values["elbowInterpShape.mcp_correctives"] = "{not json"
        msg = _err(correctives.validate_corrective, _params(), fake)
        assert "unreadable" in msg

    def test_locked_joint_refuses(self):
        fake = FakeCmds()
        fake.locked_plugs = {"|arm_01|arm_02.rotateY"}
        msg = _err(correctives.validate_corrective, _params(), fake)
        assert "locked" in msg

    def test_constrained_joint_refuses_with_the_source_named(self):
        fake = FakeCmds()
        fake.types["oc1"] = "orientConstraint"
        fake.conns["|arm_01|arm_02.rotateX"] = ["oc1.constraintRotateX"]
        msg = _err(correctives.validate_corrective, _params(), fake)
        assert "oc1" in msg

    def test_missing_plugin_refuses_with_a_hint(self):
        fake = FakeCmds()
        fake.missing_plugins = {"poseInterpolator"}
        msg = _err(correctives.validate_corrective, _params(), fake)
        assert "poseInterpolator" in msg and "plugin" in msg

    def test_nearby_but_distinct_pose_passes(self):
        fake = FakeCmds()
        fake.types["elbowInterpShape"] = "poseInterpolator"
        fake.conns["elbowInterpShape.driver[0].driverMatrix"] = [
            "|arm_01|arm_02.matrix"]
        fake.string_attrs.add("elbowInterpShape.mcp_correctives")
        fake.attr_values["elbowInterpShape.mcp_correctives"] = (
            '[{"pose": "bulge", "target": "bulge", "mesh": "|arm", '
            '"blend_shape": "arm_shapes", "rotation": [0.0, 0.0, -120.0]}]')
        plan = correctives.validate_corrective(_params(), fake)
        assert plan["interpolator"] == "elbowInterpShape"
        assert plan["target"] == "elbow_fix"

    def test_valid_plan_without_existing_interp(self):
        plan = correctives.validate_corrective(_params(), FakeCmds())
        assert plan["interpolator"] is None
        assert plan["joint_long"] == "|arm_01|arm_02"
        assert plan["rotation"] == [0.0, 0.0, -90.0]
        assert plan["blend_node"] == "arm_shapes"


class TestTheFakeRefusesWhatMayaRefuses:
    """#799 round 2: the regression barrier for THIS file's FakeCmds.

    Round 1 hardened the fake and nothing asserted the hardening - a
    reviewer measured that reverting every behavioural change left the
    suite fully green, which is this ticket's own "a green suite proves
    nothing" moved up one level. These assertions go red the day someone
    loosens the fake back toward answering anything.

    Only what this fake models is pinned: it has no setAttr and no
    setKeyframe (the #771 handlers reach neither headlessly), so the
    write-refusal contract lives in tests/test_blendshape.py and the
    driven-weight contract is pinned here through the queries the guard
    actually makes - getAttr(lock) and listConnections.
    """

    _GONE = "No object matches name"

    def test_a_node_no_fixture_created_raises_from_every_query(self):
        f = FakeCmds()
        calls = [
            lambda: f.nodeType("|ghost"),
            lambda: f.listRelatives("|ghost", shapes=True),
            lambda: f.listHistory("|ghost"),
            lambda: f.listAttr("|ghost.w"),
            lambda: f.listConnections("|ghost.tx", source=True),
            lambda: f.attributeQuery("mcp_corrective", node="|ghost",
                                     exists=True),
            lambda: f.getAttr("|ghost.tx"),
        ]
        for call in calls:
            with pytest.raises(RuntimeError, match=self._GONE):
                call()
        assert f.ls("|ghost") == []
        assert f.objExists("|ghost") is False

    def test_a_deleted_node_stops_answering(self):
        f = FakeCmds()
        assert f.nodeType("|arm") == "transform"
        assert f.listRelatives("|arm", shapes=True) == ["|arm|armShape"]
        f.delete("|arm")
        for call in (lambda: f.nodeType("|arm"),
                     lambda: f.nodeType("|arm|armShape"),
                     lambda: f.listRelatives("|arm", shapes=True),
                     lambda: f.listHistory("|arm|armShape")):
            with pytest.raises(RuntimeError, match=self._GONE):
                call()
        assert f.ls("|arm") == []
        assert f.objExists("|arm") is False

    def test_a_name_registered_again_answers_again(self):
        # The other direction: a PERMANENT tombstone is a fake wrong in the
        # strict direction. `delete` prunes the registries instead, so a
        # fixture that re-registers the name gets a node Maya would answer
        # for - which is why `_all` no longer filters against `deleted`.
        f = FakeCmds()
        f.delete("|arm_01")
        with pytest.raises(RuntimeError, match=self._GONE):
            f.nodeType("|arm_01")
        f.types["|arm_01"] = "joint"
        assert f.nodeType("|arm_01") == "joint"

    def test_getAttr_answers_only_what_a_fixture_declared(self):
        f = FakeCmds()
        f.attr_values["arm_shapes.envelope"] = 1.0
        assert f.getAttr("arm_shapes.envelope") == 1.0
        # An attribute nothing declared is not an empty None the handler can
        # read past - it is a refusal, the way Maya answers.
        with pytest.raises(RuntimeError, match=self._GONE):
            f.getAttr("arm_shapes.weightList")

    def test_getAttr_lock_reports_only_locked_plugs(self):
        f = FakeCmds()
        f.locked_plugs = {"|arm_01.rotateX"}
        assert f.getAttr("|arm_01.rotateX", lock=True) is True
        assert f.getAttr("|arm_01.rotateY", lock=True) is False

    def test_listAttr_models_only_the_weight_multi(self):
        f = FakeCmds()
        assert f.listAttr("arm_shapes.w") == ["elbow_fix", "bulge"]
        # An empty multi answers None, not [] - and every other plug is
        # refused rather than answered with the [] this used to invent.
        f.aliases["arm_shapes"] = []
        assert f.listAttr("arm_shapes.w") is None
        with pytest.raises(AssertionError, match="models only"):
            f.listAttr("arm_shapes.envelope")

    def test_listConnections_models_sources_and_derived_types(self):
        f = FakeCmds()
        f.types["curve1"] = "animCurveTU"
        f.conns["arm_shapes.elbow_fix"] = ["curve1.output"]
        assert f.listConnections("arm_shapes.elbow_fix", source=True,
                                 plugs=True) == ["curve1.output"]
        # Maya's type filter matches DERIVED types (the #796 defect-1 trap)
        assert f.listConnections("arm_shapes.elbow_fix", source=True,
                                 type="animCurve") == ["curve1"]
        assert f.listConnections("arm_shapes.elbow_fix", source=True,
                                 type="poseInterpolator") is None
        with pytest.raises(AssertionError, match="source queries only"):
            f.listConnections("arm_shapes.elbow_fix", destination=True)

    def test_attributeQuery_answers_only_declared_attributes(self):
        f = FakeCmds()
        f.string_attrs.add("|arm.mcp_corrective")
        assert f.attributeQuery("mcp_corrective", node="|arm",
                                exists=True) is True
        assert f.attributeQuery("nope", node="|arm", exists=True) is False
