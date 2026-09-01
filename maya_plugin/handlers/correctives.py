"""#771: apply_delta_mush + add_corrective - deformation quality for rigs
the toolbox already builds.

apply_delta_mush relaxes skinning artifacts: one deltaMush at the END of the
chain (blendShape -> skinCluster -> deltaMush; measured, evals/
correctives_probe/), identity at rest, reported as measured edge-stretch
ratios against the orig shape's edge lengths.

add_corrective completes the phase-5 story (#691): an EXISTING blendshape
target fires AT a joint angle instead of at a hand-set weight, via the
poseInterpolator plugin (loaded on demand, the curveform sweep precedent).
The measured mechanics this module is built on (probe, 2026-08-31):

- cmds.poseInterpolator(joint, name=...) creates transform+shape wired
  driver[0].driverMatrix <- joint.matrix; the shipped MEL helper
  poseInterpolatorAddPose(shape, name) snapshots the driver's CURRENT
  rotation as a pose and returns its index.
- With neutral/neutralSwing/neutralTwist recorded at rest and one pose at
  the trigger rotation, output[pose] ramps 0 -> 1 monotonically (0.5 at
  half angle) and a connected weight follows it exactly.
- setAttr on a driven weight raises; setKeyframe on one SILENTLY no-ops
  (returns 0, no curve) - which is why clip.driven_weight_source and the
  guard closures in blendshape.py and clip.py exist.
- FBX export bakes a driven weight into real per-frame DeformPercent curves
  (reimport tracks the driver), so correctives ship in clip exports with no
  in-scene baking; a deltaMush, by contrast, is DROPPED byte-identically -
  export.py warns.

Every refusal fires before any node is created. The one mutation block runs
under session.auto_checkpoint; failure deletes what this call created and
restores the driver joint's rotation.

A second corrective at the SAME rotation (within DUPLICATE_POSE_TOL_DEG)
REUSES the existing pose - it connects the same output element to the new
target instead of stacking a near-duplicate pose that would ill-condition
the interpolation. The record of what this tool authored lives in the
interpolator's `mcp_correctives` string attr (JSON list of {pose, target,
mesh, blend_shape, rotation}) - the mcp_clip precedent: the tool's records
are the tool's memory, because pose[i].poseRotation internals are not a
contract. An unreadable record REFUSES rather than being silently replaced
(overwriting it would erase every prior pose's memory and disarm the
duplicate guard).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError, require_known_keys
from . import (blendshape, clip, naming, plugwrite, rigmath, sculpt_math,
               session, units)

APPLY_DELTA_MUSH_KEYS = ("mesh", "smoothing_iterations", "smoothing_step",
                         "pin_border_vertices", "distance_weight")
APPLY_DELTA_MUSH_SYNONYMS = {"iterations": "smoothing_iterations",
                             "step": "smoothing_step",
                             "pin_border": "pin_border_vertices",
                             "object": "mesh", "name": "mesh"}
MAX_MUSH_ITERATIONS = rigmath.MAX_SMOOTH_ITERATIONS
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
# Below this vertex movement the mush changed nothing at the current pose -
# which is exactly what "measured at rest" means for a deformer that is
# identity at the bind pose. Keyed on the MEASUREMENT, not on joint
# rotations: a rig posed by translation, a constraint, or a bind pose that
# legitimately carries rotation (the #732 class) would fool a rotation test
# both ways.
NOOP_MUSH_DISPLACEMENT = 1e-6
SCALE_TOL = 1e-6


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _mel():
    import maya.mel as mel  # noqa: PLC0415 - only importable inside Maya

    return mel


def _short(name: str) -> str:
    return name.split("|")[-1]


# ---------------------------------------------------------------------------
# apply_delta_mush
# ---------------------------------------------------------------------------


def validate_delta_mush(params: Dict[str, Any], cmds) -> Dict[str, Any]:
    """Everything checkable before a node is created."""
    require_known_keys(params, APPLY_DELTA_MUSH_KEYS, "apply_delta_mush",
                       APPLY_DELTA_MUSH_SYNONYMS)

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
    skins = cmds.ls(history, type="skinCluster") or []
    if not skins:
        raise HandlerError(
            "apply_delta_mush relaxes SKINNING - %s has no skinCluster"
            % mesh_long,
            hint="bind_skin first; a mush without a skin has nothing to "
                 "relax and this tool's report would be meaningless")
    mushes = cmds.ls(history, type="deltaMush") or []
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
    it = om.MItMeshEdge(sel.getDagPath(0))
    space = om.MSpace.kWorld if world else om.MSpace.kObject
    lengths = []
    while not it.isDone():
        lengths.append(it.length(space))
        it.next()
    return lengths


def bind_edge_lengths(cmds, mesh_long: str) -> Optional[List[float]]:
    """Every edge's length on the orig (intermediate) shape, or None.

    The orig shape holds the bind geometry, so no pose mutation is needed
    to know bind lengths - the same currency humanoid_live's tear detector
    speaks. Computed once per apply (a deltaMush cannot change the orig
    shape, so re-reading it after the mutation would be duplicate work)."""
    orig = _orig_shape(cmds, mesh_long)
    if orig is None:
        return None
    return _edge_lengths(orig, world=False)


def worst_edge_ratio(cmds, mesh_long: str,
                     bind: Optional[List[float]]) -> Optional[float]:
    """Worst current-world / bind edge-length ratio, or None."""
    if bind is None:
        return None
    current = _edge_lengths(mesh_long, world=True)
    if len(current) != len(bind):
        return None
    worst = 0.0
    for now, was in zip(current, bind):
        if was > 1e-9:
            worst = max(worst, now / was)
    return worst


def apply_delta_mush(params: Dict[str, Any]) -> Dict[str, Any]:
    # Ahead of _cmds(), so a caller with the wrong word is told so without
    # needing Maya at all (#767). validate_delta_mush guards again because it
    # is the seam the headless tests drive directly; the call is idempotent.
    require_known_keys(params, APPLY_DELTA_MUSH_KEYS, "apply_delta_mush",
                       APPLY_DELTA_MUSH_SYNONYMS)
    cmds = _cmds()
    plan = validate_delta_mush(params, cmds)
    mesh_long = plan["mesh_long"]
    warnings: List[str] = []

    # Bind lengths come from the orig shape in OBJECT space; the current
    # lengths are world. A transform carrying scale makes the ratio report
    # the scale, not the stretch - say so rather than let a healthy rig
    # read as torn (only export_fbx enforces identity scale, and only at
    # export time).
    world_scale = cmds.xform(mesh_long, query=True, worldSpace=True,
                             scale=True) or [1.0, 1.0, 1.0]
    if any(abs(s - 1.0) > SCALE_TOL for s in world_scale):
        warnings.append(
            "%s's world scale is %s - the edge ratios below compare "
            "world lengths against object-space bind lengths, so they are "
            "inflated by that scale; freeze transforms for honest numbers"
            % (mesh_long, [round(s, 6) for s in world_scale]))

    checkpoint = session.auto_checkpoint("apply_delta_mush")

    bind = bind_edge_lengths(cmds, mesh_long)
    ratio_before = worst_edge_ratio(cmds, mesh_long, bind)
    before_pts = blendshape._points(mesh_long)

    node = cmds.deltaMush(
        mesh_long,
        smoothingIterations=plan["iterations"],
        smoothingStep=plan["step"],
        pinBorderVertices=plan["pin_border"])[0]
    try:
        # distanceWeight is set post-create (the deltaMush command has no
        # flag for it) INSIDE the rollback: a mush stranded at Maya's
        # default 0.0 is the uniform-smoothing spike this module's
        # constant block measures, and a failed call must not leave it
        # live (review catch, 4 finders).
        cmds.setAttr(node + ".distanceWeight", plan["distance_weight"])
    except Exception:
        if cmds.objExists(node):
            cmds.delete(node)
        raise HandlerError(
            "the deltaMush was created but its distanceWeight could not "
            "be set - the node was deleted again rather than left at "
            "Maya's uniform-smoothing default (measured to spike "
            "anisotropic edges up to 15x)",
            hint="restore checkpoint %r if the scene looks disturbed"
                 % checkpoint["checkpoint_id"])

    ratio_after = worst_edge_ratio(cmds, mesh_long, bind)
    max_displacement = sculpt_math.max_displacement(
        before_pts, blendshape._points(mesh_long))

    if max_displacement < NOOP_MUSH_DISPLACEMENT:
        warnings.append(
            "the mush changed nothing at the current pose - deltaMush is "
            "identity at the bind pose (measured), so an unposed rig "
            "reads ~1.0 on both ratios; pose the rig to measure the "
            "relaxation")

    return {"mesh": mesh_long, "delta_mush": node,
            "worst_edge_ratio_before": ratio_before,
            "worst_edge_ratio_after": ratio_after,
            "max_displacement": max_displacement,
            "warnings": warnings}


# ---------------------------------------------------------------------------
# add_corrective
# ---------------------------------------------------------------------------


def _ensure_pose_interpolator_plugin(cmds) -> None:
    """Load the poseInterpolator plugin, or refuse naming it.

    The curveform sweep precedent: without this, the failure surfaces many
    lines later - after the checkpoint and after the joint was zeroed - as
    a confusing AttributeError on cmds.poseInterpolator that names nothing
    about the plugin."""
    if cmds.pluginInfo("poseInterpolator", query=True, loaded=True):
        return
    try:
        cmds.loadPlugin("poseInterpolator", quiet=True)
    except Exception:  # noqa: BLE001 - the verdict is the re-query below
        pass
    if not cmds.pluginInfo("poseInterpolator", query=True, loaded=True):
        raise HandlerError(
            "the poseInterpolator plugin is not available in this Maya",
            hint="add_corrective drives weights through a poseInterpolator "
                 "node; load the plugin (Windows > Settings > Plug-in "
                 "Manager, poseInterpolator) or install a Maya that "
                 "ships it")


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
    """This module's own record of the poses it added to `interp`.

    An unreadable record REFUSES: returning [] here and letting the caller
    append-and-overwrite would silently erase every prior pose's memory
    and disarm the duplicate guard in one step (review catch)."""
    if not cmds.attributeQuery(CORRECTIVE_ATTR, node=interp, exists=True):
        return []
    raw = cmds.getAttr("%s.%s" % (interp, CORRECTIVE_ATTR))
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise HandlerError(
            "the %s record on %s is unreadable (%s) - refusing rather "
            "than overwrite it, which would erase every prior corrective's "
            "memory" % (CORRECTIVE_ATTR, interp, exc),
            hint="delete_objects the interpolator to re-author its "
                 "correctives from scratch, or repair the attr by hand")
    if not isinstance(parsed, list):
        raise HandlerError(
            "the %s record on %s is not a list - refusing rather than "
            "overwrite it" % (CORRECTIVE_ATTR, interp),
            hint="delete_objects the interpolator to re-author its "
                 "correctives from scratch, or repair the attr by hand")
    return parsed


def _joint_rotation_writable(cmds, joint_long: str) -> None:
    """Refuse a driver joint this handler cannot pose.

    The handler must write joint.rotate to record the trigger; a locked or
    connection-fed channel would raise mid-mutation - after the checkpoint,
    with the restore step then masking the real error (review catch).

    This was the package's ONLY writability guard, and #802 made it the
    model for the five commands that had none. It now calls that shared
    guard rather than classifying for itself: two sites answering "who owns
    this plug" independently is exactly how #771 and #796 each shipped a
    wrong hint. `plugwrite.family` asks about the compound and its three
    children, which is the plug list this function used to build by hand.
    """
    plugwrite.guard(
        cmds, [joint_long + ".rotate"], "add_corrective",
        consequence="add_corrective must pose the driver joint to record "
                    "the trigger, and it cannot pose this one",
        hint_tail="for a keyed rig: delete_clip first, add the corrective, "
                  "then re-author the motion")


def validate_corrective(params: Dict[str, Any], cmds) -> Dict[str, Any]:
    require_known_keys(params, ADD_CORRECTIVE_KEYS, "add_corrective",
                       ADD_CORRECTIVE_SYNONYMS)

    _ensure_pose_interpolator_plugin(cmds)

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
    src, kind = clip.driven_weight_source(cmds, weight_plug)
    if kind == "clip":
        raise HandlerError(
            "a clip owns weight %r (driven by %s)"
            % (target, src.split(".")[0]),
            hint="delete_clip returns the channel to static control "
                 "before a corrective can take it over")
    if kind == "corrective":
        raise HandlerError(
            "%r is already a corrective, driven by %s"
            % (target, src.split(".")[0]),
            hint="delete_objects the interpolator to re-author every "
                 "corrective on that joint")
    if kind is not None:
        raise HandlerError(
            "weight %r is already driven by %s" % (target, src),
            hint="disconnect it before wiring a corrective")

    _joint_rotation_writable(cmds, joint_long)

    interp = interp_for_joint(cmds, joint_long)
    reuse_pose: Optional[str] = None
    if interp is not None:
        for record in corrective_records(cmds, interp):
            recorded = record.get("rotation") or []
            if (len(recorded) == 3
                    and all(abs(float(a) - b) < DUPLICATE_POSE_TOL_DEG
                            for a, b in zip(recorded, rotation))):
                # Same trigger, different target (a same-target repeat was
                # already refused above as driven): REUSE the pose. Two
                # poses within a degree would ill-condition the
                # interpolation; two targets riding one pose is an
                # ordinary rig (elbow_bulge + forearm_crease on one bend).
                reuse_pose = record.get("pose")
                warnings.append(
                    "reusing pose %r (recorded at %s) for target %r - a "
                    "second pose within %g degrees would make the "
                    "interpolation ill-conditioned, so both targets ride "
                    "the one pose"
                    % (reuse_pose, recorded, target,
                       DUPLICATE_POSE_TOL_DEG))
                break

    return {"mesh_long": mesh_long, "blend_node": node, "target": target,
            "joint_long": joint_long, "rotation": rotation,
            "interpolator": interp, "reuse_pose": reuse_pose,
            "warnings": warnings}


def _set_rotate(cmds, joint: str, degrees: Tuple[float, float, float]) -> None:
    cmds.setAttr(joint + ".rotate",
                 units.degrees_to_ui(cmds, degrees[0]),
                 units.degrees_to_ui(cmds, degrees[1]),
                 units.degrees_to_ui(cmds, degrees[2]))


def _add_pose(mel, interp: str, name: str) -> int:
    return int(mel.eval('poseInterpolatorAddPose("%s", "%s")'
                        % (interp, name)))


def _pose_index_by_name(cmds, interp: str, name: str) -> Optional[int]:
    for i in cmds.getAttr(interp + ".pose", multiIndices=True) or []:
        if cmds.getAttr("%s.pose[%d].poseName" % (interp, i)) == name:
            return i
    return None


def _unique_pose_name(existing: List[str], requested: str) -> str:
    if requested not in existing:
        return requested
    i = 2
    while "%s_%d" % (requested, i) in existing:
        i += 1
    return "%s_%d" % (requested, i)


def add_corrective(params: Dict[str, Any]) -> Dict[str, Any]:
    # Ahead of _cmds()/_mel() for the reason apply_delta_mush states above:
    # an unknown key is answerable without Maya, and validate_corrective
    # keeps its own guard as the headless test seam.
    require_known_keys(params, ADD_CORRECTIVE_KEYS, "add_corrective",
                       ADD_CORRECTIVE_SYNONYMS)
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
        # A previewed shape may hold a non-zero STATIC weight; the
        # connection about to own this plug makes that value dead either
        # way, and measuring corrective_displacement against a baseline
        # that already contains the shape would report ~0 for a working
        # corrective (review catch).
        if abs(float(cmds.getAttr(weight_plug))) > 1e-9:
            cmds.setAttr(weight_plug, 0.0)
            warnings.append(
                "weight %r held a hand-set value - zeroed before wiring; "
                "the corrective's driver owns it now" % target)

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

        _set_rotate(cmds, joint, tuple(rotation))

        pose_index: Optional[int] = None
        pose_name = plan["reuse_pose"]
        if pose_name is not None:
            pose_index = _pose_index_by_name(cmds, interp, pose_name)
        if pose_index is None:
            # No reusable pose (or a stale record naming a pose deleted
            # outside this tool - then a fresh pose is the right answer).
            existing_names = list(
                cmds.poseInterpolator(interp, query=True,
                                      poseNames=True) or [])
            pose_name = _unique_pose_name(existing_names, target)
            pose_index = _add_pose(mel, interp, pose_name)
            pose_added = pose_name

        # The corrective's own contribution, measured through the real
        # chain at the trigger pose: skin-only before, skin+shape after.
        pre = blendshape._points(mesh_long)
        cmds.connectAttr("%s.output[%d]" % (interp, pose_index), weight_plug)
        connected = True
        post = blendshape._points(mesh_long)
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
        try:
            _set_rotate(cmds, joint, snapshot)
        except Exception:  # noqa: BLE001 - never mask the primary error
            pass

    return {"mesh": mesh_long, "blend_shape": node, "target": target,
            "joint": joint, "interpolator": interp,
            "pose_name": pose_name, "pose_index": pose_index,
            "weight_at_pose": weight_at_pose,
            "weight_at_rest": weight_at_rest,
            "corrective_displacement": corrective_displacement,
            "warnings": warnings}
