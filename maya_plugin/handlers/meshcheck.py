"""Mesh integrity + shading-group discipline (golem-run lesson, #577 req 1).

Per-face shader assignment on polyCBoolOp output silently no-ops and corrupts
the shading groups (faces drop to unassigned-green in VP2). Only object-level
assignment is reliable after a boolean — ensure_object_shading collapses any
partial/absent membership to a single object-level SG and reports it.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..dispatcher import HandlerError


def _mesh_fn(name: str):
    import maya.api.OpenMaya as om  # noqa: PLC0415 - only importable inside Maya

    sel = om.MSelectionList()
    try:
        sel.add(name)
    except RuntimeError:
        raise HandlerError(
            "object %r not found" % name,
            hint="call maya_get_scene_graph to list objects",
        ) from None
    dag = sel.getDagPath(0)
    try:
        dag.extendToShape()
    except RuntimeError:
        pass  # already a shape
    return om, dag


def mesh_stats(name: str) -> Dict[str, Any]:
    om, dag = _mesh_fn(name)
    fn = om.MFnMesh(dag)
    tri_counts, _ = fn.getTriangles()
    boundary = 0
    nonmanifold = 0
    edge_it = om.MItMeshEdge(dag)
    while not edge_it.isDone():
        connected = edge_it.numConnectedFaces()
        if connected == 1:
            boundary += 1
        elif connected > 2:
            nonmanifold += 1
        edge_it.next()
    return {
        "tris": sum(tri_counts),
        "verts": fn.numVertices,
        "faces": fn.numPolygons,
        "boundary_edges": boundary,
        "nonmanifold_edges": nonmanifold,
        "watertight": boundary == 0 and nonmanifold == 0,
    }


def first_sg(cmds, shape: str) -> Optional[str]:
    engines = cmds.listConnections(shape, type="shadingEngine") or []
    return engines[0] if engines else None


def ensure_object_shading(cmds, shape: str, fallback_sg: Optional[str]) -> Dict[str, Any]:
    """Collapse shading to one object-level SG unless it is already exactly that.

    Healthy = exactly one shading group and the shape itself (not face
    components) is a member. Anything else — no SG, several SGs, or face-level
    membership — is unreliable on boolean output and gets force-assigned.
    """
    sgs = cmds.listSets(object=shape, type=1) or []
    if len(sgs) == 1:
        members = cmds.sets(sgs[0], query=True) or []
        short = shape.split("|")[-1]
        if any(m.split("|")[-1] == short and ".f[" not in m for m in members):
            return {"sg": sgs[0], "repaired": False}
    target = fallback_sg or (sgs[0] if sgs else "initialShadingGroup")
    cmds.sets(shape, edit=True, forceElement=target)
    return {"sg": target, "repaired": True}
