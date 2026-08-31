"""#771: apply_delta_mush + add_corrective - deformation quality for rigs
the toolbox already builds.

apply_delta_mush relaxes skinning artifacts: one deltaMush at the END of the
chain (blendShape -> skinCluster -> deltaMush; measured, evals/
correctives_probe/), identity at rest, reported as measured edge-stretch
ratios against the orig shape's edge lengths.

add_corrective completes the phase-5 story (#691): an EXISTING blendshape
target fires AT a joint angle instead of at a hand-set weight, via the
poseInterpolator plugin (loaded by default on this install). The measured
mechanics this module is built on (probe, 2026-08-31):

- cmds.poseInterpolator(joint, name=...) creates transform+shape wired
  driver[0].driverMatrix <- joint.matrix; the shipped MEL helper
  poseInterpolatorAddPose(shape, name) snapshots the driver's CURRENT
  rotation as a pose and returns its index.
- With neutral/neutralSwing/neutralTwist recorded at rest and one pose at
  the trigger rotation, output[pose] ramps 0 -> 1 monotonically (0.5 at
  half angle) and a connected weight follows it exactly.
- setAttr on a driven weight raises; setKeyframe on one SILENTLY no-ops
  (returns 0, no curve) - which is why the guard closures in blendshape.py
  and clip.py exist.
- FBX export bakes a driven weight into real per-frame DeformPercent curves
  (reimport tracks the driver), so correctives ship in clip exports with no
  in-scene baking; a deltaMush, by contrast, is DROPPED byte-identically -
  export.py warns.

Every refusal fires before any node is created. The one mutation block runs
under session.auto_checkpoint; failure deletes what this call created and
restores the driver joint's rotation in a finally.

The duplicate-pose refusal reads this module's own `mcp_correctives` string
attr (JSON list of {pose, target, mesh, blend_shape, rotation}) off the
interpolator shape - the mcp_clip precedent: the tool's records are the
tool's memory, because pose[i].poseRotation internals are not a contract.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError, require_known_keys
from . import blendshape, clip, naming, sculpt, sculpt_math, session, units

APPLY_DELTA_MUSH_KEYS = ("mesh", "smoothing_iterations", "smoothing_step",
                         "pin_border_vertices", "distance_weight")
DELTA_MUSH_SYNONYMS = {"iterations": "smoothing_iterations",
                       "step": "smoothing_step",
                       "pin_border": "pin_border_vertices",
                       "object": "mesh", "name": "mesh"}
MAX_MUSH_ITERATIONS = 50  # mirrors rigmath.MAX_SMOOTH_ITERATIONS
DEFAULT_MUSH_ITERATIONS = 10  # Maya's own default
DEFAULT_MUSH_STEP = 0.5
# NOT Maya's default (0.0). MEASURED (evals/correctives_probe/
# probe_mush_spike.py, crouched humanoid): uniform smoothing on this
# toolbox's primitive meshes - 2 mm circumference rings beside 70 mm
# length edges, the #669 anisotropy - drags tiny-edge vertices toward
# their huge neighbours and SPIKES them (worst edge 8.9x its bind length
# at iterations 10, 15.5x at 20, a visible 17-31 mm tear). Distance-
# weighted smoothing removes the spike entirely AND beats the pre-mush
# stretch on both currencies (unfiltered 1.943 -> 1.54, visible 1.234 ->
# 1.216), so it is the default here.
DEFAULT_DISTANCE_WEIGHT = 1.0

ADD_CORRECTIVE_KEYS = ("mesh", "target", "joint", "rotation")
ADD_CORRECTIVE_SYNONYMS = {"angle": "rotation", "pose": "rotation",
                           "bone": "joint", "shape": "target",
                           "weight": "target"}
ZERO_ROTATION_TOL_DEG = 1e-3
DUPLICATE_POSE_TOL_DEG = 1.0
CORRECTIVE_ATTR = "mcp_correctives"
NEUTRAL_POSES = ("neutral", "neutralSwing", "neutralTwist")
# The inert-wire floor (#764 class): a freshly added pose evaluated AT its
# own trigger rotation measured 1.0 exactly; anything under 0.5 means the
# wiring did not take and the call must fail loudly, not return ok.
WEIGHT_AT_POSE_FLOOR = 0.5
REST_WEIGHT_WARN = 0.01

ROTATE_ATTRS = ("rotateX", "rotateY", "rotateZ")
# Below this angle on every axis of every influence, the rig counts as
# unposed and the delta-mush measurement means little.
REST_ANGLE_TOL_DEG = 1e-3


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _mel():
    import maya.mel as mel  # noqa: PLC0415 - only importable inside Maya

    return mel


def _short(name: str) -> str:
    return name.split("|")[-1]


def _points(mesh_long: str) -> List[float]:
    """World-space vertex positions through the real deformer chain.
    Module-level so mayapy tests can monkeypatch (the blendshape._points
    precedent)."""
    return sculpt.vertex_positions(_cmds(), mesh_long)


# ---------------------------------------------------------------------------
# apply_delta_mush
# ---------------------------------------------------------------------------


def validate_delta_mush(params: Dict[str, Any], cmds) -> Dict[str, Any]:
    """Everything checkable before a node is created."""
    require_known_keys(params, APPLY_DELTA_MUSH_KEYS, "apply_delta_mush",
                       DELTA_MUSH_SYNONYMS)

    mesh_name = params.get("mesh")
    if not isinstance(mesh_name, str) or not mesh_name.strip():
        raise HandlerError(
            "missing required param 'mesh'",
            hint="the skinned mesh to relax; maya_get_scene_graph lists "
                 "what the scene contains")
    mesh_long, mesh_shape = naming.require_mesh(cmds, mesh_name)

    iterations = params.get("smoothing_iterations", DEFAULT_MUSH_ITERATIONS)
    if (isinstance(iterations, bool) or not isinstance(iterations, int)
            or not 1 <= iterations <= MAX_MUSH_ITERATIONS):
        raise HandlerError(
            "smoothing_iterations must be an integer in 1..%d"
            % MAX_MUSH_ITERATIONS,
            hint="got %r; default is %d (Maya's own)"
                 % (iterations, DEFAULT_MUSH_ITERATIONS))

    step = params.get("smoothing_step", DEFAULT_MUSH_STEP)
    if (isinstance(step, bool) or not isinstance(step, (int, float))
            or not 0.01 <= float(step) <= 1.0):
        raise HandlerError(
            "smoothing_step must be a number in 0.01..1.0",
            hint="got %r; default is %g" % (step, DEFAULT_MUSH_STEP))

    pin_border = params.get("pin_border_vertices", True)
    if not isinstance(pin_border, bool):
        raise HandlerError(
            "pin_border_vertices must be a boolean",
            hint="got %r; default true (Maya's own)" % (pin_border,))

    distance_weight = params.get("distance_weight", DEFAULT_DISTANCE_WEIGHT)
    if (isinstance(distance_weight, bool)
            or not isinstance(distance_weight, (int, float))
            or not 0.0 <= float(distance_weight) <= 1.0):
        raise HandlerError(
            "distance_weight must be a number in 0..1",
            hint="got %r; default %g - 0 (uniform smoothing) measurably "
                 "SPIKES the small edges of anisotropic meshes (2 mm rings "
                 "beside 70 mm length edges) up to 15x their bind length"
                 % (distance_weight, DEFAULT_DISTANCE_WEIGHT))

    history = cmds.listHistory(mesh_shape, pruneDagObjects=True) or []
    skins = [n for n in history if cmds.nodeType(n) == "skinCluster"]
    if not skins:
        raise HandlerError(
            "apply_delta_mush relaxes SKINNING - %s has no skinCluster"
            % mesh_long,
            hint="bind_skin first; a mush without a skin has nothing to "
                 "relax and this tool's report would be meaningless")
    mushes = [n for n in history if cmds.nodeType(n) == "deltaMush"]
    if mushes:
        raise HandlerError(
            "%s already has a deltaMush (%s)" % (mesh_long, mushes[0]),
            hint="delete_objects it first - stacked smoothing is the "
                 "stacked-skinCluster problem with a different node type")

    return {"mesh_long": mesh_long, "mesh_shape": mesh_shape,
            "iterations": int(iterations), "step": float(step),
            "pin_border": pin_border,
            "distance_weight": float(distance_weight),
            "skin_cluster": skins[0]}


def _orig_shape(cmds, mesh_long: str) -> Optional[str]:
    """The intermediate (pre-deformation) shape, or None."""
    shapes = cmds.listRelatives(mesh_long, shapes=True, fullPath=True) or []
    orig = cmds.ls(shapes, intermediateObjects=True) or []
    return orig[0] if orig else None


def _edge_lengths(mesh_node: str, world: bool) -> List[float]:
    import maya.api.OpenMaya as om  # noqa: PLC0415

    sel = om.MSelectionList()
    sel.add(mesh_node)
    try:
        dag = sel.getDagPath(0)
        it = om.MItMeshEdge(dag)
    except RuntimeError:
        # An intermediate shape has no DAG path evaluation of its own frame;
        # object space via MObject still measures its stored points.
        it = om.MItMeshEdge(sel.getDependNode(0))
    space = om.MSpace.kWorld if world else om.MSpace.kObject
    lengths = []
    while not it.isDone():
        p0 = it.point(0, space)
        p1 = it.point(1, space)
        lengths.append((p0 - p1).length())
        it.next()
    return lengths


def worst_edge_ratio(cmds, mesh_long: str) -> Optional[float]:
    """Worst current-world / orig-shape edge-length ratio, or None.

    The orig shape holds the bind geometry, so no pose mutation is needed to
    know bind lengths - the same currency humanoid_live's tear detector
    speaks. Orig points are object-space; the export gate's identity-scale
    culture makes that equal to world at bind."""
    orig = _orig_shape(cmds, mesh_long)
    if orig is None:
        return None
    current = _edge_lengths(mesh_long, world=True)
    bind = _edge_lengths(orig, world=False)
    if len(current) != len(bind):
        return None
    worst = 0.0
    for now, was in zip(current, bind):
        if was > 1e-9:
            worst = max(worst, now / was)
    return worst


def _rig_is_at_rest(cmds, skin_cluster: str) -> bool:
    influences = cmds.skinCluster(skin_cluster, query=True,
                                  influence=True) or []
    for joint in influences:
        for attr in ROTATE_ATTRS:
            value = units.ui_to_degrees(
                cmds, float(cmds.getAttr("%s.%s" % (joint, attr))))
            if abs(value) > REST_ANGLE_TOL_DEG:
                return False
    return True


def apply_delta_mush(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    plan = validate_delta_mush(params, cmds)
    mesh_long = plan["mesh_long"]
    warnings: List[str] = []

    checkpoint = session.auto_checkpoint("apply_delta_mush")

    ratio_before = worst_edge_ratio(cmds, mesh_long)
    before_pts = _points(mesh_long)

    node = cmds.deltaMush(
        mesh_long,
        smoothingIterations=plan["iterations"],
        smoothingStep=plan["step"],
        pinBorderVertices=plan["pin_border"])[0]
    # distanceWeight is set post-create: the deltaMush command has no flag
    # for it, and the attr write re-evaluates the node either way.
    cmds.setAttr(node + ".distanceWeight", plan["distance_weight"])
    try:
        history = cmds.listHistory(plan["mesh_shape"],
                                   pruneDagObjects=True) or []
        mushes = [n for n in history if cmds.nodeType(n) == "deltaMush"]
        if len(mushes) != 1:
            raise HandlerError(
                "postcondition failed: expected exactly one deltaMush in "
                "%s's history, found %d" % (mesh_long, len(mushes)),
                hint="restore checkpoint %r" % checkpoint["checkpoint_id"])
    except Exception:
        if cmds.objExists(node):
            cmds.delete(node)
        raise

    ratio_after = worst_edge_ratio(cmds, mesh_long)
    max_displacement = sculpt_math.max_displacement(
        before_pts, _points(mesh_long))

    if _rig_is_at_rest(cmds, plan["skin_cluster"]):
        warnings.append(
            "measured at rest - deltaMush is identity at the bind pose "
            "(measured), so both ratios read ~1.0 and max_displacement ~0; "
            "pose the rig to measure the relaxation")

    return {"mesh": mesh_long, "delta_mush": node,
            "worst_edge_ratio_before": ratio_before,
            "worst_edge_ratio_after": ratio_after,
            "max_displacement": max_displacement,
            "warnings": warnings}


# ---------------------------------------------------------------------------
# add_corrective
# ---------------------------------------------------------------------------


def _incoming(cmds, plug: str) -> Optional[str]:
    srcs = cmds.listConnections(plug, source=True, destination=False,
                                plugs=True) or []
    return srcs[0] if srcs else None


def interp_for_joint(cmds, joint_long: str) -> Optional[str]:
    """The scene poseInterpolator shape driven by this joint, or None."""
    for shape in cmds.ls(type="poseInterpolator") or []:
        srcs = cmds.listConnections(shape + ".driver[0].driverMatrix",
                                    source=True, destination=False) or []
        for src in srcs:
            resolved = cmds.ls(src, long=True) or [src]
            if resolved[0] == joint_long:
                return shape
    return None


def corrective_records(cmds, interp: str) -> List[Dict[str, Any]]:
    """This module's own record of the poses it added to `interp`."""
    if not cmds.attributeQuery(CORRECTIVE_ATTR, node=interp, exists=True):
        return []
    raw = cmds.getAttr("%s.%s" % (interp, CORRECTIVE_ATTR))
    try:
        parsed = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def validate_corrective(params: Dict[str, Any], cmds) -> Dict[str, Any]:
    require_known_keys(params, ADD_CORRECTIVE_KEYS, "add_corrective",
                       ADD_CORRECTIVE_SYNONYMS)

    mesh_name = params.get("mesh")
    if not isinstance(mesh_name, str) or not mesh_name.strip():
        raise HandlerError(
            "missing required param 'mesh'",
            hint="the mesh whose blendshape target should become a "
                 "corrective")
    mesh_long, mesh_shape = naming.require_mesh(cmds, mesh_name)

    warnings: List[str] = []
    node = blendshape._blend_node_for(cmds, mesh_shape, warnings)
    if node is None:
        raise HandlerError(
            "%s has no blendShape" % mesh_long,
            hint="create_blendshape authors the corrective shape first; "
                 "add_corrective only makes an existing target fire at a "
                 "joint angle")
    aliases = blendshape._aliases(cmds, node)
    target = params.get("target")
    if target not in aliases:
        raise HandlerError(
            "%r is not a target of %s" % (target, node),
            hint="targets here: %s" % ", ".join(aliases))

    joint_name = params.get("joint")
    if not isinstance(joint_name, str) or not joint_name.strip():
        raise HandlerError(
            "missing required param 'joint'",
            hint="the driver joint whose rotation fires the corrective")
    joint_long = naming.require_object(cmds, joint_name)
    if cmds.nodeType(joint_long) != "joint":
        raise HandlerError(
            "%s is not a joint" % joint_long,
            hint="the driver must be a joint - its local rotation is what "
                 "the pose interpolator reads")

    rotation_raw = params.get("rotation")
    ok_shape = (isinstance(rotation_raw, (list, tuple))
                and len(rotation_raw) == 3
                and all(isinstance(r, (int, float))
                        and not isinstance(r, bool) for r in rotation_raw))
    if not ok_shape:
        raise HandlerError(
            "rotation must be [rx, ry, rz] in LOCAL degrees",
            hint="the same currency pose_skeleton speaks; got %r"
                 % (rotation_raw,))
    rotation = [float(r) for r in rotation_raw]
    if all(abs(r) < ZERO_ROTATION_TOL_DEG for r in rotation):
        raise HandlerError(
            "rotation (0,0,0) IS the neutral pose",
            hint="give the bent pose the corrective should peak at, e.g. "
                 "[0, 0, -90] for a 90-degree local-Z bend")

    weight_plug = "%s.%s" % (node, target)
    src = _incoming(cmds, weight_plug)
    if src is not None:
        src_node = src.split(".")[0]
        src_type = cmds.nodeType(src_node)
        if src_type.startswith("animCurve"):
            raise HandlerError(
                "a clip owns weight %r (driven by %s)" % (target, src_node),
                hint="delete_clip returns the channel to static control "
                     "before a corrective can take it over")
        if src_type == "poseInterpolator":
            raise HandlerError(
                "%r is already a corrective, driven by %s" % (target, src_node),
                hint="delete_objects the interpolator to re-author every "
                     "corrective on that joint")
        raise HandlerError(
            "weight %r is already driven by %s" % (target, src),
            hint="disconnect it before wiring a corrective")

    driven = clip._anim_curves(
        cmds, ["%s.%s" % (joint_long, a) for a in ROTATE_ATTRS])
    if driven:
        raise HandlerError(
            "add_corrective refuses while animation curves drive %s - the "
            "handler must pose the joint to record the trigger, and a "
            "static write here would fight the curves" % joint_long,
            hint="delete_clip first, add the corrective, then re-author "
                 "the motion")

    interp = interp_for_joint(cmds, joint_long)
    if interp is not None:
        for record in corrective_records(cmds, interp):
            recorded = record.get("rotation") or []
            if (len(recorded) == 3
                    and all(abs(float(a) - b) < DUPLICATE_POSE_TOL_DEG
                            for a, b in zip(recorded, rotation))):
                raise HandlerError(
                    "a pose at that rotation already exists on %s (pose %r "
                    "driving %r)" % (interp, record.get("pose"),
                                     record.get("target")),
                    hint="two poses within %g degrees make the "
                         "interpolation ill-conditioned; pick a distinct "
                         "trigger angle" % DUPLICATE_POSE_TOL_DEG)

    return {"mesh_long": mesh_long, "mesh_shape": mesh_shape,
            "blend_node": node, "target": target, "joint_long": joint_long,
            "rotation": rotation, "interpolator": interp,
            "warnings": warnings}


def _set_rotate(cmds, joint: str, degrees: Tuple[float, float, float]) -> None:
    cmds.setAttr(joint + ".rotate",
                 units.degrees_to_ui(cmds, degrees[0]),
                 units.degrees_to_ui(cmds, degrees[1]),
                 units.degrees_to_ui(cmds, degrees[2]))


def _add_pose(mel, interp: str, name: str) -> int:
    return int(mel.eval('poseInterpolatorAddPose("%s", "%s")'
                        % (interp, name)))


def _unique_pose_name(existing: List[str], requested: str) -> str:
    if requested not in existing:
        return requested
    i = 2
    while "%s_%d" % (requested, i) in existing:
        i += 1
    return "%s_%d" % (requested, i)


def add_corrective(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    mel = _mel()
    plan = validate_corrective(params, cmds)
    mesh_long = plan["mesh_long"]
    node = plan["blend_node"]
    target = plan["target"]
    joint = plan["joint_long"]
    rotation = plan["rotation"]
    warnings = list(plan["warnings"])

    checkpoint = session.auto_checkpoint("add_corrective")

    snapshot = tuple(
        units.ui_to_degrees(cmds, v)
        for v in (cmds.getAttr(joint + ".rotate")[0]))
    created_transform: Optional[str] = None
    connected = False
    pose_added: Optional[str] = None
    interp = plan["interpolator"]
    weight_plug = "%s.%s" % (node, target)
    try:
        if interp is None:
            # Neutral poses must record the driver at REST: zero, create,
            # add the three neutrals the Pose Editor itself records.
            _set_rotate(cmds, joint, (0.0, 0.0, 0.0))
            created_transform = cmds.poseInterpolator(
                joint, name=naming.unique_name(
                    cmds, _short(joint) + "_poseInterp"))[0]
            shapes = cmds.listRelatives(created_transform, shapes=True,
                                        fullPath=False) or []
            if not shapes:
                raise HandlerError(
                    "poseInterpolator created no shape under %r"
                    % created_transform,
                    hint="restore checkpoint %r"
                         % checkpoint["checkpoint_id"])
            interp = shapes[0]
            for neutral in NEUTRAL_POSES:
                _add_pose(mel, interp, neutral)

        existing_names = list(
            cmds.poseInterpolator(interp, query=True, poseNames=True) or [])
        pose_name = _unique_pose_name(existing_names, target)

        _set_rotate(cmds, joint, tuple(rotation))
        pose_index = _add_pose(mel, interp, pose_name)
        pose_added = pose_name

        # The corrective's own contribution, measured through the real
        # chain at the trigger pose: skin-only before, skin+shape after.
        pre = _points(mesh_long)
        cmds.connectAttr("%s.output[%d]" % (interp, pose_index), weight_plug)
        connected = True
        post = _points(mesh_long)
        corrective_displacement = sculpt_math.max_displacement(pre, post)

        weight_at_pose = float(cmds.getAttr(weight_plug))
        if weight_at_pose < WEIGHT_AT_POSE_FLOOR:
            raise HandlerError(
                "the corrective did not take: weight %r reads %.3f at its "
                "own trigger pose (expected ~1.0) - the wiring is inert"
                % (target, weight_at_pose),
                hint="restore checkpoint %r and inspect the interpolator's "
                     "driver" % checkpoint["checkpoint_id"])

        _set_rotate(cmds, joint, (0.0, 0.0, 0.0))
        weight_at_rest = float(cmds.getAttr(weight_plug))
        if abs(weight_at_rest) > REST_WEIGHT_WARN:
            warnings.append(
                "weight %r reads %.3f at rest (expected ~0) - neighbouring "
                "poses on this interpolator overlap the neutral"
                % (target, weight_at_rest))

        extent = sculpt_math.bbox_extent(pre)
        if corrective_displacement < max(extent, 1.0) * blendshape.ZERO_DELTA_RATIO:
            warnings.append(
                "corrective measured max displacement %.3g at its trigger "
                "pose - the target is (near-)identical to the base"
                % corrective_displacement)

        records = corrective_records(cmds, interp)
        records.append({"pose": pose_name, "target": target,
                        "mesh": mesh_long, "blend_shape": node,
                        "rotation": rotation})
        if not cmds.attributeQuery(CORRECTIVE_ATTR, node=interp, exists=True):
            cmds.addAttr(interp, longName=CORRECTIVE_ATTR, dataType="string")
        cmds.setAttr("%s.%s" % (interp, CORRECTIVE_ATTR),
                     json.dumps(records), type="string")
    except Exception:
        # Undo what THIS call created; the checkpoint covers the rest.
        try:
            if connected:
                srcs = cmds.listConnections(weight_plug, source=True,
                                            destination=False,
                                            plugs=True) or []
                for src in srcs:
                    cmds.disconnectAttr(src, weight_plug)
            if created_transform is not None and cmds.objExists(
                    created_transform):
                cmds.delete(created_transform)
            elif pose_added is not None:
                mel.eval('poseInterpolatorDeletePose("%s", "%s")'
                         % (interp, pose_added))
        except Exception:  # noqa: BLE001 - rollback is best-effort
            pass
        raise
    finally:
        _set_rotate(cmds, joint, snapshot)

    return {"mesh": mesh_long, "blend_shape": node, "target": target,
            "joint": joint, "interpolator": interp,
            "pose_name": pose_name, "pose_index": pose_index,
            "weight_at_pose": weight_at_pose,
            "weight_at_rest": weight_at_rest,
            "corrective_displacement": corrective_displacement,
            "warnings": warnings}
