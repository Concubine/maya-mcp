"""Skeletal rigging, phase 1 of #602: create_skeleton, bind_skin,
pose_skeleton, reset_pose.

Angles are degrees at the boundary (#636), positions are ordinary geometry
numbers (#629/#634), and every command reports what it MEASURED, not what it
was asked for: a bind reports the vertices no joint owns, a pose reports how
far the furthest vertex actually moved - from vertices, never bounding boxes
(#640). The shaping op that did nothing and said it succeeded is the worst
defect class this project knows (#636), and this module is built so that
failure is a number, not a feeling.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError, require_known_keys
from . import clip, naming, rigmath, sculpt, sculpt_math, session, units


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _short(name: str) -> str:
    return name.split("|")[-1]


def _long(cmds, node: str) -> str:
    return (cmds.ls(node, long=True) or [node])[0]


# Every top-level key create_skeleton reads. Anything else is refused rather
# than ignored (#767): an unread key does not fail, it succeeds and does
# something else.
CREATE_SKELETON_KEYS = ("joints", "chain", "chain_prefix", "root_name")
# Both wrong words are the shorter, more natural half of a real key. Nothing
# in this toolbox is called a bare `prefix` - this command qualifies it as
# `chain_prefix` and `array` qualifies its own as `name_prefix` - so the bare
# word is what a caller reaches for. And `bones` is what the whole world
# outside Maya calls joints; Maya's node type is the only reason `joints` won.
CREATE_SKELETON_SYNONYMS = {"prefix": "chain_prefix", "bones": "joints"}


def create_skeleton(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, CREATE_SKELETON_KEYS, "create_skeleton",
                       CREATE_SKELETON_SYNONYMS)
    cmds = _cmds()
    resolved = rigmath.resolve_joints(params)
    session.auto_checkpoint("create_skeleton")

    warnings: List[str] = []
    long_names: Dict[str, str] = {}  # requested name -> created long name
    for joint in resolved:
        unique = naming.unique_name(cmds, joint["name"])
        if unique != joint["name"]:
            warnings.append(
                "%r already existed in the scene; created as %r"
                % (joint["name"], unique))
        if joint["parent"] is None:
            cmds.select(clear=True)
        else:
            cmds.select(long_names[joint["parent"]], replace=True)
        node = cmds.joint(name=unique, position=joint["position"])
        # Maya's SSC default exports as FBX InheritType 2, which Unity turns
        # into 100x scale compounding per joint level under the metres
        # declaration (#703). This toolset never scales joints, so the flag
        # buys nothing here; off at creation keeps the scene matching the
        # artifact, and the export gate refuses InheritType 2 regardless.
        cmds.setAttr(node + ".segmentScaleCompensate", 0)
        long_names[joint["name"]] = _long(cmds, node)

    root_long = long_names[resolved[0]["name"]]

    # Default orientation: aim the primary axis at the first child, Maya's own
    # convention; leaves are zeroed so nothing dangles a stray orient. The
    # explicit per-joint `orient` overrides afterwards. Whatever won is
    # REPORTED per joint, because orientation is where every rig surprise
    # lives.
    if cmds.listRelatives(root_long, children=True, type="joint"):
        cmds.joint(root_long, edit=True, orientJoint="xyz",
                   secondaryAxisOrient="yup", zeroScaleOrient=True,
                   children=True)
    for joint in resolved:
        node = long_names[joint["name"]]
        if not cmds.listRelatives(node, children=True, type="joint"):
            cmds.setAttr(node + ".jointOrient", 0.0, 0.0, 0.0)
        if joint["orient"] is not None:
            cmds.setAttr(node + ".jointOrient",
                         units.degrees_to_ui(cmds, joint["orient"][0]),
                         units.degrees_to_ui(cmds, joint["orient"][1]),
                         units.degrees_to_ui(cmds, joint["orient"][2]))

    # Setting jointOrient does not move the joint it is set on, but a child's
    # translate lives in its PARENT's frame - so re-orienting a parent swings
    # every child through world space. Asked for (0, 2.05, 0) with an explicit
    # orient, the #713 golem measured (0.33, 1.72, 0), silently (#719). The
    # requested world positions are the contract, so they are re-asserted here,
    # parents first (a parent move carries its children, which are re-asserted
    # in turn); resolve_joints guarantees that order.
    for joint in resolved:
        cmds.xform(long_names[joint["name"]], worldSpace=True,
                   translation=joint["position"])

    joints_out = []
    for joint in resolved:
        node = long_names[joint["name"]]
        pos = cmds.xform(node, query=True, worldSpace=True, translation=True)
        raw = cmds.getAttr(node + ".jointOrient")[0]
        joints_out.append({
            "name": node,
            "position": [float(v) for v in pos],
            "parent": long_names[joint["parent"]] if joint["parent"] else None,
            "orient": [round(units.ui_to_degrees(cmds, v), 6) for v in raw],
        })
    return {"root": root_long, "joints": joints_out, "warnings": warnings}


# bindMethod values cmds.skinCluster actually takes, by the names the tool
# surface speaks. 1 (closest in hierarchy) is deliberately absent until a
# run fights for it.
BIND_METHODS = {"closestDistance": 0, "heatMap": 2, "geodesicVoxel": 3}
MAX_INFLUENCES_CEILING = 8


def _require_joint(cmds, name) -> str:
    node = naming.require_object(cmds, str(name or ""))
    if cmds.nodeType(node) != "joint":
        raise HandlerError(
            "%s is not a joint" % node,
            hint="pass the skeleton root maya_create_skeleton returned")
    return node


def _skin_weights(skin_cluster: str,
                  mesh_shape: str) -> Tuple[List[str], List[float], int]:
    """Every weight in ONE call, via the API.

    cmds.skinPercent is a call per vertex - on a real mesh that is the whole
    timeout. MFnSkinCluster.getWeights returns the entire table at once, and
    its columns follow influenceObjects() order, which is NOT necessarily the
    cmds query order - so the influence names come from the same API call.
    """
    import maya.api.OpenMaya as om          # noqa: PLC0415
    import maya.api.OpenMayaAnim as oma     # noqa: PLC0415

    sel = om.MSelectionList()
    sel.add(mesh_shape)
    sel.add(skin_cluster)
    dag = sel.getDagPath(0)
    fn = oma.MFnSkinCluster(sel.getDependNode(1))
    comp_fn = om.MFnSingleIndexedComponent()
    comp = comp_fn.create(om.MFn.kMeshVertComponent)
    num_verts = om.MFnMesh(dag).numVertices
    comp_fn.setCompleteData(num_verts)
    weights, _ncols = fn.getWeights(dag, comp)
    influences = [dp.fullPathName() for dp in fn.influenceObjects()]
    return influences, list(weights), num_verts


# Every top-level key bind_skin reads. Anything else is refused rather than
# ignored (#767): an unread key does not fail, it succeeds and does something
# else.
BIND_SKIN_KEYS = ("mesh", "root", "method", "max_influences")
# A caller thinks of the thing being bound to as the skeleton - it is what
# create_skeleton just handed back - while this command names it by the one
# joint at its top. `influences` is weight_report's own vocabulary, the word
# its histogram entries and per_joint counts are phrased in, so it reads as
# the input for the cap that is actually spelled `max_influences`. And
# `bind_method` is the qualified spelling the BIND_METHODS table invites.
BIND_SKIN_SYNONYMS = {"skeleton": "root", "influences": "max_influences",
                      "bind_method": "method"}


def bind_skin(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, BIND_SKIN_KEYS, "bind_skin",
                       BIND_SKIN_SYNONYMS)
    cmds = _cmds()
    mesh_long, mesh_shape = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    root_long = _require_joint(cmds, params.get("root"))

    method = params.get("method", "closestDistance")
    if method not in BIND_METHODS:
        # The brief's test asserts `match="closestDistance"` against the raised
        # exception, but HandlerError.__str__ (dispatcher.py) folds in only the
        # message, never .hint - every other test in this codebase checks hint
        # text via `exc.value.hint`, not `pytest.raises(match=...)`. So the
        # valid-methods list has to live in the message itself, not just the
        # hint, for that assertion to pass.
        raise HandlerError(
            "unknown bind method %r; one of: %s"
            % (method, ", ".join(sorted(BIND_METHODS))),
            hint="one of: %s" % ", ".join(sorted(BIND_METHODS)))
    max_influences = params.get("max_influences", 4)
    if (not isinstance(max_influences, int) or isinstance(max_influences, bool)
            or not 1 <= max_influences <= MAX_INFLUENCES_CEILING):
        raise HandlerError(
            "max_influences must be an integer 1..%d" % MAX_INFLUENCES_CEILING,
            hint="4 is the game-engine convention and the default")

    existing = cmds.ls(cmds.listHistory(mesh_shape, pruneDagObjects=True) or [],
                       type="skinCluster") or []
    if existing:
        raise HandlerError(
            "%s is already bound (skinCluster %s)" % (mesh_long, existing[0]),
            hint="stacked skinClusters are Maya's quietest way to make weights "
                 "unexplainable, so re-binding is refused. Unbind first via "
                 "maya_execute_python: cmds.skinCluster(%r, edit=True, "
                 "unbind=True) - or restore the checkpoint taken before the "
                 "first bind" % existing[0])

    session.auto_checkpoint("bind_skin")
    sc = cmds.skinCluster(
        root_long, mesh_long,
        bindMethod=BIND_METHODS[method],
        maximumInfluences=max_influences,
        obeyMaxInfluences=True,
        toSelectedBones=False,
        name=naming.unique_name(cmds, _short(mesh_long) + "_skin"),
    )[0]

    influences, weights, num_verts = _skin_weights(sc, mesh_shape)
    stats = rigmath.weight_stats(influences, weights, num_verts, max_influences)

    warnings: List[str] = []
    hierarchy = set(_hierarchy_joints(cmds, root_long))
    outside = [inf for inf in influences if inf not in hierarchy]
    if outside:
        warnings.append(
            "%d influence(s) sit OUTSIDE the hierarchy under %s: %s - "
            "skinCluster binds the whole skeleton the root belongs to; pass "
            "the true root to silence this"
            % (len(outside), _short(root_long),
               ", ".join(_short(j) for j in outside[:8])))
    empty = [p["joint"] for p in stats["per_joint"] if p["vertices"] == 0]
    if empty:
        warnings.append(
            "%d joint(s) own no vertices and will move nothing when posed: %s"
            % (len(empty), ", ".join(_short(j) for j in empty[:8])))
    if stats["unweighted_vertices"]:
        warnings.append(
            "%d vertices belong to NO joint - they stay behind when the "
            "creature moves, and nothing looks wrong at bind time. This bind "
            "fails the phase gate." % stats["unweighted_vertices"])
    if stats["max_influences_exceeded"]:
        warnings.append(
            "%d vertices carry more than max_influences=%d meaningful weights"
            % (stats["max_influences_exceeded"], max_influences))

    return {
        "mesh": mesh_long,
        "root": root_long,
        "skin_cluster": sc,
        "influences": influences,
        "unweighted_vertices": stats["unweighted_vertices"],
        "max_influences_exceeded": stats["max_influences_exceeded"],
        "per_joint": stats["per_joint"],
        "warnings": warnings,
    }


# Below this fraction of the bound mesh's own bbox diagonal, a pose is the
# "reported success, moved nothing" failure (#636) and warns loudly. Same
# constant and rationale as sculpt.NOOP_DISPLACEMENT_RATIO.
NOOP_POSE_RATIO = 1e-2


def _hierarchy_joints(cmds, root_long: str) -> List[str]:
    """root_long, then every descendant joint, each parent before its children.

    NOT `listRelatives(allDescendents=True)`: measured against a real Maya
    (mayapy probe while pinning this test), that flag returns joints
    leaf-first (bottom of the hierarchy first), so for a straight 4-joint
    chain `joints[-1]` was the SECOND joint, not the tip - and
    TestPoseSkeletonInMaya.test_a_bend_actually_moves_the_mesh, which reads
    `out["joints"][-1]` as the tip, would silently check the wrong joint. A
    breadth-first walk over direct children guarantees a parent is placed
    before its children, so a single unbranched chain always ends with its
    leaf last.
    """
    order = [root_long]
    frontier = [root_long]
    while frontier:
        node = frontier.pop(0)
        children = cmds.listRelatives(
            node, children=True, type="joint", fullPath=True) or []
        order.extend(children)
        frontier.extend(children)
    return order


def _bound_meshes(cmds, joint_set) -> List[str]:
    """Transforms of every mesh this skeleton MOVES - by deformation or by
    rigid parenting.

    Two rig shapes are legal here. A skinned mesh is found through its
    skinCluster's influences. A rigid-parent rig (#713: chunks parented under
    joints, no deformer anywhere) is found structurally - a mesh transform
    under a joint moves with that joint, and reporting zero displacement for
    it would be an echo, not a measurement (#636, #720).

    Skinned meshes come first, then descendants; de-duplicated, long names.
    """
    out: List[str] = []
    for sc in cmds.ls(type="skinCluster") or []:
        influences = cmds.skinCluster(sc, query=True, influence=True) or []
        influences = set(cmds.ls(influences, long=True) or [])
        if not influences & joint_set:
            continue
        for shape in cmds.skinCluster(sc, query=True, geometry=True) or []:
            transform = cmds.listRelatives(shape, parent=True, fullPath=True)
            if transform and transform[0] not in out:
                out.append(transform[0])
    for joint in sorted(joint_set):
        for node in cmds.listRelatives(joint, allDescendents=True,
                                       fullPath=True, type="transform") or []:
            if not cmds.listRelatives(node, shapes=True, fullPath=True,
                                      type="mesh"):
                continue
            if node not in out:
                out.append(node)
    return out


def _resolve_rotations(cmds, joints: List[str], rotations) -> Dict[str, List[float]]:
    if not isinstance(rotations, dict) or not rotations:
        raise HandlerError(
            "rotations must be a non-empty map of joint name to [rx, ry, rz] "
            "in DEGREES",
            hint='e.g. rotations={"spine_03": [0, 0, 8.2]}')
    by_short: Dict[str, List[str]] = {}
    for j in joints:
        by_short.setdefault(_short(j), []).append(j)
    resolved: Dict[str, List[float]] = {}
    resolved_via: Dict[str, str] = {}  # target long name -> the spelling that named it
    for name, value in rotations.items():
        triple = rigmath.vec3(value, "rotations[%r]" % name)
        if triple is None:
            raise HandlerError("rotations[%r] must be [rx, ry, rz]" % name)
        if name in joints:
            target = name
        else:
            matches = by_short.get(_short(name), [])
            if not matches:
                raise HandlerError(
                    "rotations names %r, which is not a joint under this root" % name,
                    hint="joints here: %s"
                         % ", ".join(_short(j) for j in joints[:12]))
            if len(matches) > 1:
                raise HandlerError(
                    "%r is ambiguous under this root (%d matches)" % (name, len(matches)),
                    hint="use the long name, e.g. %s" % matches[0])
            target = matches[0]
        if target in resolved_via:
            # Two spellings of the same joint (e.g. "arm" and "|r|arm") would
            # otherwise collapse last-write-wins and `applied` would
            # under-report - refuse instead of guessing which one wins.
            raise HandlerError(
                "rotations names %s twice: %r and %r"
                % (target, resolved_via[target], name),
                hint="use one spelling per joint - both resolve to %s" % target)
        resolved[target] = triple
        resolved_via[target] = name
    return resolved


# Every top-level key pose_skeleton reads. Anything else is refused rather
# than ignored (#767): an unread key does not fail, it succeeds and does
# something else.
POSE_SKELETON_KEYS = ("root", "rotations", "space")
# `pose` is the command's own noun, and add_corrective takes a pose under a
# neighbouring spelling, so a caller naturally names the payload after the
# operation rather than after the degrees it actually carries. `skeleton` is
# the same slip bind_skin sees: the argument feels like the whole skeleton,
# not the single joint at its top.
POSE_SKELETON_SYNONYMS = {"pose": "rotations", "skeleton": "root"}


def pose_skeleton(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, POSE_SKELETON_KEYS, "pose_skeleton",
                       POSE_SKELETON_SYNONYMS)
    cmds = _cmds()
    root_long = _require_joint(cmds, params.get("root"))
    space = params.get("space", "local")
    if space != "local":
        raise HandlerError(
            "space %r is not supported" % (space,),
            hint="a pose is per-joint LOCAL euler rotations in degrees - the "
                 "same currency a phase-6 clip keys. Reaching a world-space "
                 "target is phase 3's pose_ik")
    joints = _hierarchy_joints(cmds, root_long)
    clip.guard_static_pose(cmds, root_long, joints, "pose_skeleton")
    resolved = _resolve_rotations(cmds, joints, params.get("rotations"))

    session.auto_checkpoint("pose_skeleton")
    meshes = _bound_meshes(cmds, set(joints))
    before = {m: sculpt.vertex_positions(cmds, m) for m in meshes}

    for joint, triple in resolved.items():
        cmds.setAttr(joint + ".rotate",
                     units.degrees_to_ui(cmds, triple[0]),
                     units.degrees_to_ui(cmds, triple[1]),
                     units.degrees_to_ui(cmds, triple[2]))

    joints_out = [{
        "name": j,
        "world_position": [float(v) for v in cmds.xform(
            j, query=True, worldSpace=True, translation=True)],
    } for j in joints]

    max_disp = 0.0
    displaced = 0
    per_mesh: List[Dict[str, Any]] = []
    for mesh in meshes:
        after = sculpt.vertex_positions(cmds, mesh)
        mesh_disp = sculpt_math.max_displacement(before[mesh], after)
        mesh_count = rigmath.displaced_count(before[mesh], after)
        per_mesh.append({"mesh": mesh, "max_displacement": mesh_disp,
                         "displaced_vertices": mesh_count})
        max_disp = max(max_disp, mesh_disp)
        displaced += mesh_count

    warnings: List[str] = []
    if not meshes:
        warnings.append(
            "this skeleton moves no mesh (no skinned bind, no mesh parented "
            "under its joints) - the pose moved bare joints only; the "
            "displacement below is measured against nothing")
    else:
        # Per mesh, not combined: a combined max hides one inert mesh among
        # several (#668 review item a).
        for entry in per_mesh:
            extent = sculpt_math.bbox_extent(before[entry["mesh"]])
            if extent > 0 and entry["max_displacement"] < extent * NOOP_POSE_RATIO:
                warnings.append(
                    "%s moved by %.4g against a size of %.4g - near-zero "
                    "deformation usually means the rotations landed on joints "
                    "that own none of its vertices"
                    % (entry["mesh"], entry["max_displacement"], extent))

    return {"applied": len(resolved), "joints": joints_out,
            "max_displacement": max_disp, "displaced_vertices": displaced,
            "per_mesh": per_mesh, "warnings": warnings}


# Every top-level key reset_pose reads. Anything else is refused rather than
# ignored (#767): an unread key does not fail, it succeeds and does something
# else.
RESET_POSE_KEYS = ("root",)
# `skeleton` again: with a single argument the caller has nothing to
# disambiguate against, and what they mean to reset is the whole skeleton.
RESET_POSE_SYNONYMS = {"skeleton": "root"}


def reset_pose(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, RESET_POSE_KEYS, "reset_pose",
                       RESET_POSE_SYNONYMS)
    cmds = _cmds()
    root_long = _require_joint(cmds, params.get("root"))
    joints = _hierarchy_joints(cmds, root_long)
    clip.guard_static_pose(cmds, root_long, joints, "reset_pose")

    session.auto_checkpoint("reset_pose")
    meshes = _bound_meshes(cmds, set(joints))
    before = {m: sculpt.vertex_positions(cmds, m) for m in meshes}

    warnings: List[str] = []
    poses = cmds.dagPose(root_long, query=True, bindPose=True) or []
    if poses:
        cmds.dagPose(poses[0], restore=True, g=True)
        if len(poses) > 1:
            warnings.append("%d bind poses exist; restored %s"
                            % (len(poses), poses[0]))
    else:
        for joint in joints:
            cmds.setAttr(joint + ".rotate", 0.0, 0.0, 0.0)
        warnings.append(
            "no bind pose exists (nothing is bound); rotations zeroed, which "
            "is the create_skeleton rest pose")

    max_disp = 0.0
    for mesh in meshes:
        after = sculpt.vertex_positions(cmds, mesh)
        max_disp = max(max_disp,
                       sculpt_math.max_displacement(before[mesh], after))
    return {"reset": True, "max_displacement": max_disp, "warnings": warnings}


def _skin_cluster_for(cmds, mesh_long: str, mesh_shape: str) -> str:
    """The mesh's one skinCluster. One is all there can be: bind_skin refuses
    stacking, and every weight op edits an existing bind rather than guessing."""
    existing = cmds.ls(cmds.listHistory(mesh_shape, pruneDagObjects=True) or [],
                       type="skinCluster") or []
    if not existing:
        raise HandlerError(
            "%s is not bound" % mesh_long,
            hint="bind_skin first - weight ops edit an existing skinCluster")
    return existing[0]


# Every top-level key weight_report reads. Anything else is refused rather
# than ignored (#767): an unread key does not fail, it succeeds and does
# something else.
WEIGHT_REPORT_KEYS = ("mesh",)


def weight_report(params: Dict[str, Any]) -> Dict[str, Any]:
    """The perception tool: how an agent judges weights without a viewport.
    A measurement - no checkpoint, nothing in the scene changes."""
    require_known_keys(params, WEIGHT_REPORT_KEYS, "weight_report")
    cmds = _cmds()
    mesh_long, mesh_shape = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    sc = _skin_cluster_for(cmds, mesh_long, mesh_shape)
    max_influences = int(cmds.getAttr(sc + ".maxInfluences"))
    influences, weights, num_verts = _skin_weights(sc, mesh_shape)
    stats = rigmath.weight_report_stats(influences, weights, num_verts,
                                        max_influences)
    warnings: List[str] = []
    if stats["unweighted_vertices"]:
        warnings.append(
            "%d vertices belong to NO joint - they stay behind when the "
            "creature moves. set_region_weights can hand them to a joint; "
            "unweighted_sample says where to aim."
            % stats["unweighted_vertices"])
    if stats["max_influences_exceeded"]:
        warnings.append(
            "%d vertices carry more than the cluster's max_influences=%d"
            % (stats["max_influences_exceeded"], max_influences))
    empty = [p["joint"] for p in stats["per_joint"] if p["vertices"] == 0]
    if empty:
        warnings.append(
            "%d joint(s) own no vertices: %s"
            % (len(empty), ", ".join(_short(j) for j in empty[:8])))
    return {
        "mesh": mesh_long,
        "skin_cluster": sc,
        "vertices": num_verts,
        "max_influences": max_influences,
        "unweighted_vertices": stats["unweighted_vertices"],
        "unweighted_sample": stats["unweighted_sample"],
        "max_influences_exceeded": stats["max_influences_exceeded"],
        "exceeded_sample": stats["exceeded_sample"],
        "max_weight_sum_error": stats["max_weight_sum_error"],
        "histogram": stats["histogram"],
        "per_joint": stats["per_joint"],
        "warnings": warnings,
    }


MIRROR_AXES = {"x": 0, "y": 1, "z": 2}
MIRROR_DIRECTIONS = {"+to-": True, "-to+": False}
# Positional match radius, scene units. Numbers mean metres here (#629/#634),
# so this is a millimetre - tight enough that a real partner is unambiguous,
# loose enough for float noise from combine/freeze.
MIRROR_TOL = 1e-3


def _set_skin_weights(skin_cluster: str, mesh_shape: str, ncols: int,
                      weights: List[float]) -> None:
    """The one write path: the whole table in one API call, no normalization
    by Maya (normalize=False) - rows arrive normalized from rigmath, and
    letting the node renormalize would un-measure what we just computed."""
    import maya.api.OpenMaya as om          # noqa: PLC0415
    import maya.api.OpenMayaAnim as oma     # noqa: PLC0415

    sel = om.MSelectionList()
    sel.add(mesh_shape)
    sel.add(skin_cluster)
    dag = sel.getDagPath(0)
    fn = oma.MFnSkinCluster(sel.getDependNode(1))
    comp_fn = om.MFnSingleIndexedComponent()
    comp = comp_fn.create(om.MFn.kMeshVertComponent)
    comp_fn.setCompleteData(om.MFnMesh(dag).numVertices)
    fn.setWeights(dag, comp, om.MIntArray(range(ncols)),
                  om.MDoubleArray(weights), False)


def _pose_warning(cmds, influences: List[str]) -> Optional[str]:
    """Weight ops pair vertices by POSITION; a posed mesh pairs garbage."""
    for joint in influences:
        rot = cmds.getAttr(joint + ".rotate")[0]
        if any(abs(v) > 1e-6 for v in rot):
            return ("the skeleton is posed (%s carries rotation) - vertex "
                    "positions drive the pairing, so mirror from the bind "
                    "pose: reset_pose first" % _short(joint))
    return None


# Every top-level key mirror_weights reads. Anything else is refused rather
# than ignored (#767): an unread key does not fail, it succeeds and does
# something else.
MIRROR_WEIGHTS_KEYS = ("mesh", "axis", "direction")


def mirror_weights(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, MIRROR_WEIGHTS_KEYS, "mirror_weights")
    cmds = _cmds()
    mesh_long, mesh_shape = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    axis = params.get("axis", "x")
    if axis not in MIRROR_AXES:
        raise HandlerError("unknown axis %r; one of: x, y, z" % (axis,),
                           hint="the mirror plane is the one the axis crosses")
    direction = params.get("direction", "+to-")
    if direction not in MIRROR_DIRECTIONS:
        raise HandlerError(
            "unknown direction %r; one of: %s"
            % (direction, ", ".join(sorted(MIRROR_DIRECTIONS))),
            hint="'+to-' copies the +%s side onto the -%s side" % (axis, axis))
    sc = _skin_cluster_for(cmds, mesh_long, mesh_shape)
    influences, weights, num_verts = _skin_weights(sc, mesh_shape)

    inf_positions = [
        [float(v) for v in cmds.xform(j, query=True, worldSpace=True,
                                      translation=True)]
        for j in influences]
    mapping, unmatched = rigmath.mirror_influence_map(
        inf_positions, MIRROR_AXES[axis], MIRROR_TOL)
    if unmatched:
        raise HandlerError(
            "%d influence(s) have no mirror partner across %s: %s"
            % (len(unmatched), axis,
               ", ".join(_short(influences[i]) for i in unmatched[:8])),
            hint="mirroring needs a bilaterally symmetric skeleton - a joint "
                 "on one side must have a positional twin on the other")

    warnings: List[str] = []
    posed = _pose_warning(cmds, influences)
    if posed:
        warnings.append(posed)

    positions = sculpt.vertex_positions(cmds, mesh_long)
    pairs, on_plane, unpaired = rigmath.mirror_pairs(
        positions, MIRROR_AXES[axis], MIRROR_TOL,
        source_positive=MIRROR_DIRECTIONS[direction])
    if unpaired:
        warnings.append(
            "%d source vertices are unpaired (no vertex within %g of the "
            "reflected position) and kept their weights - the mesh is not "
            "symmetric across %s there"
            % (len(unpaired), MIRROR_TOL, axis))

    session.auto_checkpoint("mirror_weights")
    new_table = rigmath.mirror_weight_table(weights, len(influences), pairs,
                                            mapping)
    _set_skin_weights(sc, mesh_shape, len(influences), new_table)

    _, after, _ = _skin_weights(sc, mesh_shape)
    stats = rigmath.weight_stats(influences, after, num_verts,
                                 int(cmds.getAttr(sc + ".maxInfluences")))
    if stats["unweighted_vertices"]:
        warnings.append("%d vertices belong to NO joint after the mirror"
                        % stats["unweighted_vertices"])
    return {
        "mesh": mesh_long,
        "skin_cluster": sc,
        "axis": axis,
        "direction": direction,
        "mirrored_vertices": len(pairs),
        "on_plane_vertices": len(on_plane),
        "unpaired_vertices": len(unpaired),
        "changed_vertices": rigmath.changed_rows(weights, after,
                                                 len(influences)),
        "unweighted_vertices": stats["unweighted_vertices"],
        "warnings": warnings,
    }


def _vertex_adjacency(mesh_shape: str) -> List[List[int]]:
    """Neighbour vertex ids per vertex, from the mesh graph."""
    import maya.api.OpenMaya as om          # noqa: PLC0415

    sel = om.MSelectionList()
    sel.add(mesh_shape)
    it = om.MItMeshVertex(sel.getDagPath(0))
    adjacency: List[List[int]] = []
    while not it.isDone():
        adjacency.append(list(it.getConnectedVertices()))
        it.next()
    return adjacency


def _resolve_influences(influences: List[str], names) -> List[int]:
    """Column indices for user-named joints; long or unique short names."""
    if not isinstance(names, list) or not names or not all(
            isinstance(n, str) and n.strip() for n in names):
        raise HandlerError("joints must be a non-empty list of joint names")
    by_short: Dict[str, List[int]] = {}
    for idx, j in enumerate(influences):
        by_short.setdefault(_short(j), []).append(idx)
    columns: List[int] = []
    for name in names:
        if name in influences:
            columns.append(influences.index(name))
            continue
        matches = by_short.get(_short(name), [])
        if not matches:
            raise HandlerError(
                "%r is not an influence of this skinCluster" % name,
                hint="influences here: %s"
                     % ", ".join(_short(j) for j in influences[:12]))
        if len(matches) > 1:
            raise HandlerError(
                "%r is ambiguous (%d influences match)" % (name, len(matches)),
                hint="use the long name, e.g. %s" % influences[matches[0]])
        columns.append(matches[0])
    return columns


# Every top-level key smooth_weights reads. Anything else is refused rather
# than ignored (#767): an unread key does not fail, it succeeds and does
# something else.
SMOOTH_WEIGHTS_KEYS = ("mesh", "iterations", "joints")
# `passes` is the word this handler's own hint teaches - it advises two or
# three of them - so the vocabulary the caller is handed back differs from the
# one the caller must send.
SMOOTH_WEIGHTS_SYNONYMS = {"passes": "iterations"}


def smooth_weights(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, SMOOTH_WEIGHTS_KEYS, "smooth_weights",
                       SMOOTH_WEIGHTS_SYNONYMS)
    cmds = _cmds()
    mesh_long, mesh_shape = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    iterations = params.get("iterations", 1)
    if (not isinstance(iterations, int) or isinstance(iterations, bool)
            or not 1 <= iterations <= rigmath.MAX_SMOOTH_ITERATIONS):
        raise HandlerError(
            "iterations must be an integer 1..%d"
            % rigmath.MAX_SMOOTH_ITERATIONS,
            hint="2-3 passes visibly soften a stair-step; more is mush")
    sc = _skin_cluster_for(cmds, mesh_long, mesh_shape)
    max_influences = int(cmds.getAttr(sc + ".maxInfluences"))
    influences, weights, num_verts = _skin_weights(sc, mesh_shape)

    rows = None
    if params.get("joints") is not None:
        columns = _resolve_influences(influences, params.get("joints"))
        ncols = len(influences)
        rows = {v for v in range(num_verts)
                if any(weights[v * ncols + j] > rigmath.WEIGHT_TOL
                       for j in columns)}

    # No _pose_warning here on purpose: smoothing reads the mesh GRAPH
    # (adjacency), not positions, so pose cannot corrupt it.
    warnings: List[str] = []

    session.auto_checkpoint("smooth_weights")
    adjacency = _vertex_adjacency(mesh_shape)
    new_table = rigmath.smooth_weight_table(
        weights, len(influences), adjacency, iterations, max_influences,
        rows=rows)
    _set_skin_weights(sc, mesh_shape, len(influences), new_table)

    _, after, _ = _skin_weights(sc, mesh_shape)
    stats = rigmath.weight_stats(influences, after, num_verts, max_influences)
    if stats["unweighted_vertices"]:
        warnings.append("%d vertices belong to NO joint after smoothing"
                        % stats["unweighted_vertices"])
    return {
        "mesh": mesh_long,
        "skin_cluster": sc,
        "iterations": iterations,
        "smoothed_vertices": num_verts if rows is None else len(rows),
        "changed_vertices": rigmath.changed_rows(weights, after,
                                                 len(influences)),
        "unweighted_vertices": stats["unweighted_vertices"],
        "max_influences_exceeded": stats["max_influences_exceeded"],
        "warnings": warnings,
    }


REGION_FALLOFFS = ("linear", "none")


def _region_vertex_ids_from_faces(cmds, mesh_long: str, faces) -> List[int]:
    if (not isinstance(faces, list) or not faces or not all(
            isinstance(f, int) and not isinstance(f, bool) and f >= 0
            for f in faces)):
        raise HandlerError("faces must be a non-empty list of face ids")
    face_count = cmds.polyEvaluate(mesh_long, face=True)
    bad = [f for f in faces if f >= face_count]
    if bad:
        raise HandlerError(
            "face id(s) out of range: %s (mesh has %d faces)"
            % (", ".join(str(f) for f in bad[:8]), face_count))
    comps = ["%s.f[%d]" % (mesh_long, f) for f in faces]
    verts = cmds.polyListComponentConversion(
        *comps, fromFace=True, toVertex=True) or []
    ids: List[int] = []
    for comp in cmds.ls(verts, flatten=True) or []:
        ids.append(int(comp[comp.rindex("[") + 1:-1]))
    return sorted(set(ids))


# Every top-level key set_region_weights reads. Anything else is refused
# rather than ignored (#767): an unread key does not fail, it succeeds and
# does something else.
SET_REGION_WEIGHTS_KEYS = ("mesh", "joint", "weight", "faces",
                           "within_radius_of", "radius", "falloff")
# A sphere is named by its centre everywhere else in this toolbox - `array`
# takes a literal `center` - so the caller supplies the geometric word while
# this command spells the same point as the phrase `within_radius_of`.
SET_REGION_WEIGHTS_SYNONYMS = {"center": "within_radius_of"}


def set_region_weights(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, SET_REGION_WEIGHTS_KEYS, "set_region_weights",
                       SET_REGION_WEIGHTS_SYNONYMS)
    cmds = _cmds()
    mesh_long, mesh_shape = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    weight = params.get("weight")
    if (not isinstance(weight, (int, float)) or isinstance(weight, bool)
            or not 0.0 <= float(weight) <= 1.0):
        raise HandlerError("weight must be a number in 0..1",
                           hint="1.0 hands the region fully to the joint")
    weight = float(weight)
    faces = params.get("faces")
    center = params.get("within_radius_of")
    if (faces is None) == (center is None):
        raise HandlerError(
            "pass exactly one of 'faces' or 'within_radius_of'",
            hint="faces=[ids] for a picked patch; within_radius_of=[x,y,z] "
                 "with radius for a spherical region")
    falloff = params.get("falloff")
    if faces is not None and falloff is not None:
        raise HandlerError(
            "falloff only applies to within_radius_of - faces are a hard "
            "assignment",
            hint="drop falloff, or switch to within_radius_of")
    falloff = "linear" if falloff is None else falloff
    if falloff not in REGION_FALLOFFS:
        raise HandlerError("unknown falloff %r; one of: %s"
                           % (falloff, ", ".join(REGION_FALLOFFS)))
    radius = params.get("radius")
    if center is not None:
        center = rigmath.vec3(center, "within_radius_of")
        if (not isinstance(radius, (int, float)) or isinstance(radius, bool)
                or float(radius) <= 0.0):
            raise HandlerError("within_radius_of needs a radius > 0",
                               hint="scene units, like every position here")
        radius = float(radius)
    elif radius is not None:
        raise HandlerError("radius only applies to within_radius_of")

    sc = _skin_cluster_for(cmds, mesh_long, mesh_shape)
    influences, weights, num_verts = _skin_weights(sc, mesh_shape)
    joint_col = _resolve_influences(influences, [params.get("joint")])[0]

    if faces is not None:
        factors = {v: 1.0
                   for v in _region_vertex_ids_from_faces(cmds, mesh_long,
                                                          faces)}
    else:
        positions = sculpt.vertex_positions(cmds, mesh_long)
        factors = rigmath.radius_factors(positions, center, radius, falloff)
    if not factors:
        raise HandlerError(
            "the region holds no vertices",
            hint="within_radius_of/radius missed the mesh entirely - "
                 "get_object_info reports where the mesh actually is")

    warnings: List[str] = []
    posed = _pose_warning(cmds, influences)
    if posed:
        warnings.append(posed)

    session.auto_checkpoint("set_region_weights")
    ncols = len(influences)
    new_table, _computed_sole_owner = rigmath.apply_region_weights(
        weights, ncols, joint_col, factors, weight)
    _set_skin_weights(sc, mesh_shape, ncols, new_table)

    _, after, _ = _skin_weights(sc, mesh_shape)
    stats = rigmath.weight_stats(influences, after, num_verts,
                                 int(cmds.getAttr(sc + ".maxInfluences")))

    # Measured from the re-read, not the computed table (#636 lying-success
    # class): a vertex counts as sole-owned only if it (a) had no other
    # influence and a positive joint weight BEFORE the edit, (b) was asked to
    # shed weight (weight < 1.0 - at weight 1.0 nothing was asked to shed, so
    # the count is 0 by definition), and (c) is STILL fully owned in the
    # table Maya actually holds now.
    sole_owner = 0
    if weight < 1.0:
        for v in factors:
            base = v * ncols
            old_j = weights[base + joint_col]
            others = sum(weights[base + j] for j in range(ncols)
                        if j != joint_col)
            if (others <= 0.0 and old_j > 0.0
                    and after[base + joint_col] > 1.0 - rigmath.WEIGHT_TOL):
                sole_owner += 1

    if sole_owner:
        warnings.append(
            "%d vertices are solely owned by %s - a weight below 1.0 has no "
            "other influence to give the remainder to, so they stay fully "
            "owned" % (sole_owner, _short(influences[joint_col])))
    if stats["unweighted_vertices"]:
        warnings.append("%d vertices belong to NO joint after the edit"
                        % stats["unweighted_vertices"])
    if stats["max_influences_exceeded"]:
        warnings.append(
            "%d vertices carry more than the cluster's max_influences=%d "
            "after the edit"
            % (stats["max_influences_exceeded"],
               int(cmds.getAttr(sc + ".maxInfluences"))))
    return {
        "mesh": mesh_long,
        "skin_cluster": sc,
        "joint": influences[joint_col],
        "vertices_in_region": len(factors),
        "changed_vertices": rigmath.changed_rows(weights, after, ncols),
        "sole_owner_vertices": sole_owner,
        "unweighted_vertices": stats["unweighted_vertices"],
        "max_influences_exceeded": stats["max_influences_exceeded"],
        "warnings": warnings,
    }


# --- phase 3 (#671): pose_ik -------------------------------------------------

# A chain whose interior joints deviate by less than this fraction of its
# reach is "straight": Maya's RP solver cannot fold a collinear chain on its
# own (zero preferred angle), so pose_ik pre-bends it PREBEND_DEG toward the
# pole to break the tie. The solve overwrites the nudge; residual reports
# whatever the solver actually achieved.
COLLINEAR_RATIO = 0.01
PREBEND_DEG = 5.0
IK_SOLVER = "ikRPsolver"
# Above this miss (scene units) a solve that COULD have reached warns; an
# out-of-reach miss is explained by the reach warning instead.
RESIDUAL_WARN = 1e-3


def _resolve_joint(cmds, joints: List[str], name, what: str) -> str:
    """One joint out of `joints`, by long or unique short name."""
    if not isinstance(name, str) or not name.strip():
        raise HandlerError("missing required param %r" % what,
                           hint="a joint name from maya_create_skeleton")
    if name in joints:
        return name
    matches = [j for j in joints if _short(j) == _short(name)]
    if not matches:
        raise HandlerError(
            "%s %r is not a joint under this root" % (what, name),
            hint="joints here: %s" % ", ".join(_short(j) for j in joints[:12]))
    if len(matches) > 1:
        raise HandlerError(
            "%s %r is ambiguous under this root (%d matches)"
            % (what, name, len(matches)),
            hint="use the long name, e.g. %s" % matches[0])
    return matches[0]


def _chain_between(cmds, joints: List[str], start: str, end: str) -> List[str]:
    """start..end inclusive, parents first; refuses a non-ancestor start."""
    chain = [end]
    node = end
    while node != start:
        parents = [p for p in (cmds.listRelatives(
            node, parent=True, fullPath=True, type="joint") or [])
            if p in joints]
        if not parents:
            raise HandlerError(
                "%s is not an ancestor of %s" % (_short(start), _short(end)),
                hint="start must sit above joint on the same chain")
        node = parents[0]
        chain.append(node)
    chain.reverse()
    return chain


def solve_ik_plan(cmds, chain: List[str], target: List[float],
                  pole: Optional[List[float]] = None) -> Dict[str, Any]:
    """Read-only analytic prep for `solve_ik_and_bake`: the chain's current
    positions, how far `target` sits against the chain's reach, and the pole
    the solve will use (given, or #671's own-bend-plane default). Nothing
    here mutates Maya, so a caller can snapshot state (pose_ik's own
    mesh/rotate "before", for its `keep=false` restore) between this call
    and the bake with nothing lost.

    Extracted from pose_ik (#774 Task 5, review: extraction with zero
    behavior change) so `solve_ik_chain` - and through it, clean_clip's
    contact-lock pass - reuses the SAME solve pose_ik does, rather than a
    second, slightly different implementation.
    """
    positions = [[float(v) for v in cmds.xform(
        j, query=True, worldSpace=True, translation=True)] for j in chain]
    reach = rigmath.chain_reach(positions)
    distance = rigmath.dist(positions[0], target)
    warnings: List[str] = []
    if distance > reach:
        warnings.append(
            "the target sits %.4g from %s but the chain reaches only %.4g - "
            "the solve will fall short and residual reports the miss"
            % (distance, _short(chain[0]), reach))

    pole_used = pole if pole is not None else rigmath.default_pole(
        positions, COLLINEAR_RATIO)
    straight = rigmath.chain_deviation(positions) < COLLINEAR_RATIO * reach
    if straight and pole_used is None:
        warnings.append(
            "the chain is STRAIGHT and no pole was given - the solver has no "
            "bend plane, so which way the limb folds is Maya's guess; pass "
            "pole=[x,y,z], the world position the knee/elbow should face")
    return {
        "positions": positions,
        "reach": reach,
        "distance": distance,
        "pole_used": pole_used,
        "straight": straight,
        "warnings": warnings,
    }


def solve_ik_and_bake(cmds, chain: List[str], target: List[float],
                      plan: Dict[str, Any]) -> Dict[str, Any]:
    """The mutating half of the #671 solve: pre-bend a straight chain toward
    `plan`'s pole, solve a transient ikHandle (the RP-solver window never
    persists past this call - handle/effector/pole locator all die in the
    `finally`, on the error path too), and bake the result as plain FK onto
    `chain`. `plan` is `solve_ik_plan`'s return for the SAME chain/target/
    pole; callers normally reach this only through `solve_ik_chain`.
    """
    positions = plan["positions"]
    pole_used = plan["pole_used"]
    straight = plan["straight"]
    distance = plan["distance"]
    reach = plan["reach"]
    start, end = chain[0], chain[-1]

    prior_preferred = {}
    if straight and pole_used is not None:
        # A straight chain gives the solver no fold to amplify: nudge the
        # interior joints a few degrees toward the pole. The solve
        # overwrites the .rotate nudge; .preferredAngle is restored below
        # regardless of what the caller does with the baked pose.
        matrices = {i: [float(v) for v in cmds.xform(
            chain[i], query=True, worldSpace=True, matrix=True)]
            for i in range(1, len(chain) - 1)}
        for i, triple in rigmath.prebend_rotations(
                positions, matrices, target, pole_used, PREBEND_DEG).items():
            prior_preferred[chain[i]] = tuple(
                cmds.getAttr(chain[i] + ".preferredAngle")[0])
            current = cmds.getAttr(chain[i] + ".rotate")[0]
            cmds.setAttr(chain[i] + ".rotate",
                         current[0] + units.degrees_to_ui(cmds, triple[0]),
                         current[1] + units.degrees_to_ui(cmds, triple[1]),
                         current[2] + units.degrees_to_ui(cmds, triple[2]))
            cmds.setAttr(chain[i] + ".preferredAngle",
                         units.degrees_to_ui(cmds, triple[0]),
                         units.degrees_to_ui(cmds, triple[1]),
                         units.degrees_to_ui(cmds, triple[2]))

    # No persistent IK state may ever exist (#671 final review): an
    # exception anywhere between the ikHandle's creation and the doomed-node
    # delete must still restore the seeded .preferredAngle and remove
    # whatever transient nodes got as far as being created.
    handle = effector = locator = None
    baked: Dict[str, List[float]] = {}
    try:
        handle, effector = cmds.ikHandle(
            startJoint=start, endEffector=end, solver=IK_SOLVER,
            name=naming.unique_name(cmds, _short(end) + "_ikh"))
        if pole_used is not None:
            locator = cmds.spaceLocator(
                name=naming.unique_name(cmds, _short(end) + "_pole"))[0]
            cmds.xform(locator, worldSpace=True, translation=pole_used)
            cmds.poleVectorConstraint(locator, handle)
        cmds.xform(handle, worldSpace=True, translation=target)

        # Reading the effector's world position pulls the IK evaluation;
        # the solved joint rotations are then plain attribute reads, in
        # degrees (#636's unit rule).
        cmds.xform(end, query=True, worldSpace=True, translation=True)
        for j in chain:
            raw = cmds.getAttr(j + ".rotate")[0]
            baked[j] = [round(units.ui_to_degrees(cmds, v), 6) for v in raw]
    finally:
        for j, angle in prior_preferred.items():
            cmds.setAttr(j + ".preferredAngle", angle[0], angle[1], angle[2])
        doomed = [n for n in (handle, effector, locator)
                  if n and cmds.objExists(n)]
        if doomed:
            cmds.delete(*doomed)
    # The bake: deleting a handle can snap joints back, so the solved values
    # are re-applied as plain FK - the same currency pose_skeleton speaks.
    for j in chain:
        cmds.setAttr(j + ".rotate",
                     units.degrees_to_ui(cmds, baked[j][0]),
                     units.degrees_to_ui(cmds, baked[j][1]),
                     units.degrees_to_ui(cmds, baked[j][2]))

    achieved = [float(v) for v in cmds.xform(
        end, query=True, worldSpace=True, translation=True)]
    residual = rigmath.dist(achieved, target)
    warnings: List[str] = []
    if residual > RESIDUAL_WARN and distance <= reach:
        warnings.append(
            "the solve missed a REACHABLE target by %.4g - joint limits, a "
            "degenerate pole, or a bend the pre-bend could not break can do "
            "this; try a pole on the intended bend side" % residual)

    return {
        "achieved_position": achieved,
        "residual": residual,
        "rotations": baked,
        "warnings": warnings,
    }


def solve_ik_chain(cmds, chain: List[str], target: List[float],
                   pole: Optional[List[float]] = None) -> Dict[str, Any]:
    """`solve_ik_plan` then `solve_ik_and_bake` in one call - the entry
    point for a caller that wants #671's 2(+)-bone analytic solve without
    pose_ik's own checkpoint/mesh-measurement/keep=false bookkeeping wrapped
    around it (clean_clip's contact-lock pass, #774 Task 5)."""
    plan = solve_ik_plan(cmds, chain, target, pole)
    solved = solve_ik_and_bake(cmds, chain, target, plan)
    return {
        "achieved_position": solved["achieved_position"],
        "residual": solved["residual"],
        "rotations": solved["rotations"],
        "chain": chain,
        "pole_used": plan["pole_used"],
        "reach": plan["reach"],
        "distance": plan["distance"],
        "warnings": plan["warnings"] + solved["warnings"],
    }


# Every top-level key pose_ik reads. Anything else is refused rather than
# ignored (#767): an unread key does not fail, it succeeds and does something
# else.
POSE_IK_KEYS = ("root", "joint", "target", "pole", "start", "keep")
# `start` IS a key here, so the caller pairs it with `end` for the far end of
# the chain - which is what this handler calls the joint internally too, only
# after resolving it. `skeleton` is the same slip bind_skin and pose_skeleton
# see: the argument feels like the whole skeleton, not its topmost joint.
POSE_IK_SYNONYMS = {"end": "joint", "skeleton": "root"}


def pose_ik(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, POSE_IK_KEYS, "pose_ik", POSE_IK_SYNONYMS)
    cmds = _cmds()
    root_long = _require_joint(cmds, params.get("root"))
    joints = _hierarchy_joints(cmds, root_long)
    clip.guard_static_pose(cmds, root_long, joints, "pose_ik")
    end = _resolve_joint(cmds, joints, params.get("joint"), "joint")
    if end == root_long:
        raise HandlerError(
            "joint must sit BELOW the root - the root has no chain above it",
            hint="e.g. root=pelvis, joint=L_ankle solves the left leg")
    target = rigmath.vec3(params.get("target"), "target")
    if target is None:
        raise HandlerError(
            "missing required param 'target'",
            hint="world position [x, y, z] the joint should reach")
    pole = rigmath.vec3(params.get("pole"), "pole")
    keep = params.get("keep", True)
    if not isinstance(keep, bool):
        raise HandlerError(
            "keep must be true or false",
            hint="true bakes the solved pose; false measures it, then "
                 "restores the pose the call found")

    if params.get("start") is not None:
        start = _resolve_joint(cmds, joints, params.get("start"), "start")
    else:
        # Default: two joints up - the classic 2-bone limb (hip for an
        # ankle, shoulder for a wrist). Longer chains pass start explicitly.
        path = _chain_between(cmds, joints, root_long, end)
        if len(path) < 3:
            raise HandlerError(
                "%s hangs directly under the root - no default chain exists"
                % _short(end),
                hint="pass start explicitly, or aim single bones with "
                     "pose_skeleton")
        start = path[-3]
    chain = _chain_between(cmds, joints, start, end)
    if len(chain) < 3:
        raise HandlerError(
            "the chain %s..%s is a single bone - IK needs at least two"
            % (_short(start), _short(end)),
            hint="a single bone is an aim, not a solve: rotate it with "
                 "pose_skeleton, or pass a higher start")

    plan = solve_ik_plan(cmds, chain, target, pole)
    warnings: List[str] = list(plan["warnings"])
    pole_used = plan["pole_used"]

    session.auto_checkpoint("pose_ik")
    meshes = _bound_meshes(cmds, set(joints))
    before = {m: sculpt.vertex_positions(cmds, m) for m in meshes}
    prior = {j: tuple(cmds.getAttr(j + ".rotate")[0]) for j in chain}

    # MEASURED (#671): ikRPsolver does NOT seed its fold direction from a
    # joint's current .rotate at ikHandle-creation time - a same-sized nudge
    # on .rotate alone left a collinear chain fully extended (effector
    # landed at the chain's full reach, the interior joint solved back to
    # 0,0,0). The solver reads the persistent .preferredAngle attribute
    # instead; setting that (in addition to the visible .rotate nudge, so a
    # mid-solve inspection still shows a bent chain) is what actually folds
    # the knee. preferredAngle is a solver-seeding implementation detail,
    # not part of the pose, so `solve_ik_and_bake` restores it to whatever
    # it held before this call once the solve is read, regardless of
    # `keep` - and the whole transient IK window (handle, effector, pole
    # locator) never survives an exception either (#671 final review): its
    # try/finally cleans up whatever got as far as being created.
    solved = solve_ik_and_bake(cmds, chain, target, plan)
    warnings.extend(solved["warnings"])
    baked = solved["rotations"]
    achieved = solved["achieved_position"]
    residual = solved["residual"]

    max_disp = 0.0
    displaced = 0
    per_mesh: List[Dict[str, Any]] = []
    for mesh in meshes:
        after = sculpt.vertex_positions(cmds, mesh)
        mesh_disp = sculpt_math.max_displacement(before[mesh], after)
        mesh_count = rigmath.displaced_count(before[mesh], after)
        per_mesh.append({"mesh": mesh, "max_displacement": mesh_disp,
                         "displaced_vertices": mesh_count})
        max_disp = max(max_disp, mesh_disp)
        displaced += mesh_count
    if not meshes:
        warnings.append(
            "this skeleton moves no mesh (no skinned bind, no mesh parented "
            "under its joints) - the solve moved bare joints only; the "
            "displacement below is measured against nothing")
    else:
        for entry in per_mesh:
            extent = sculpt_math.bbox_extent(before[entry["mesh"]])
            if extent > 0 and entry["max_displacement"] < extent * NOOP_POSE_RATIO:
                warnings.append(
                    "%s moved by %.4g against a size of %.4g - near-zero "
                    "deformation usually means the chain owns none of its "
                    "vertices"
                    % (entry["mesh"], entry["max_displacement"], extent))

    if not keep:
        for j, rot in prior.items():
            cmds.setAttr(j + ".rotate", rot[0], rot[1], rot[2])
        warnings.append(
            "keep=false: the solved pose was measured, then the pose the "
            "call found was restored - apply rotations via pose_skeleton to "
            "commit it")

    return {
        "achieved_position": achieved,
        "residual": residual,
        "rotations": baked,
        "chain": chain,
        "pole_used": pole_used,
        "kept": keep,
        "max_displacement": max_disp,
        "displaced_vertices": displaced,
        "per_mesh": per_mesh,
        "warnings": warnings,
    }
