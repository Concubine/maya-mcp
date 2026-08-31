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

    # -- naming / resolution ------------------------------------------------
    def _all(self):
        return (list(self.meshes) + list(self.meshes.values())
                + list(self.types))

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
        if node in self.meshes.values():
            return "mesh"
        return self.types.get(node, "transform")

    def listRelatives(self, node, shapes=False, fullPath=False,
                      noIntermediate=False, **kw):
        if shapes and node in self.meshes:
            return [self.meshes[node]]
        return None

    def listHistory(self, node, pruneDagObjects=False, **kw):
        return list(self.history.get(node, []))

    def listAttr(self, plug, multi=False, **kw):
        node = plug.split(".")[0]
        if plug.endswith(".w"):
            return list(self.aliases.get(node, []))
        return []

    def listConnections(self, plug, source=False, destination=True,
                        plugs=False, type=None, **kw):
        if not source:
            return None
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
        return ("%s.%s" % (node, attr)) in self.string_attrs

    def getAttr(self, plug, lock=False, **kw):
        if lock:
            return plug in getattr(self, "locked_plugs", set())
        return self.attr_values.get(plug)

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
        assert "animation curves" in msg

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
