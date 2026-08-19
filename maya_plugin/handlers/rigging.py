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

from ..dispatcher import HandlerError
from . import naming, rigmath, sculpt, sculpt_math, session, units


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _short(name: str) -> str:
    return name.split("|")[-1]


def _long(cmds, node: str) -> str:
    return (cmds.ls(node, long=True) or [node])[0]


def create_skeleton(params: Dict[str, Any]) -> Dict[str, Any]:
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


def bind_skin(params: Dict[str, Any]) -> Dict[str, Any]:
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
    """Transforms of every mesh whose skinCluster any of these joints drives."""
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


def pose_skeleton(params: Dict[str, Any]) -> Dict[str, Any]:
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
    for mesh in meshes:
        after = sculpt.vertex_positions(cmds, mesh)
        max_disp = max(max_disp,
                       sculpt_math.max_displacement(before[mesh], after))
        displaced += rigmath.displaced_count(before[mesh], after)

    warnings: List[str] = []
    if not meshes:
        warnings.append(
            "no skinned mesh is bound to this skeleton - the pose moved bare "
            "joints only; bind_skin first if deformation was the point")
    else:
        extent = max(sculpt_math.bbox_extent(before[m]) for m in meshes)
        if extent > 0 and max_disp < extent * NOOP_POSE_RATIO:
            warnings.append(
                "the pose moved the mesh by %.4g against a size of %.4g - "
                "near-zero deformation usually means the rotations landed on "
                "joints that own no vertices" % (max_disp, extent))

    return {"applied": len(resolved), "joints": joints_out,
            "max_displacement": max_disp, "displaced_vertices": displaced,
            "warnings": warnings}


def reset_pose(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    root_long = _require_joint(cmds, params.get("root"))
    joints = _hierarchy_joints(cmds, root_long)

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


def weight_report(params: Dict[str, Any]) -> Dict[str, Any]:
    """The perception tool: how an agent judges weights without a viewport.
    A measurement - no checkpoint, nothing in the scene changes."""
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


def mirror_weights(params: Dict[str, Any]) -> Dict[str, Any]:
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
