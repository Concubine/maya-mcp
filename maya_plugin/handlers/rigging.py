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
