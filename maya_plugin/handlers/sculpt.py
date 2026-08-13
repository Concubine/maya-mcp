"""sculpt_ops: the golem-maker (§5.3). Ops apply in order; the first failure
aborts with a report of what landed (one undo chunk - maya_undo reverts all).

Three ops (soft_move, inflate_region, displace_noise) write vertices via
MFnMesh.setPoints, which Maya's undo queue does not track - maya_undo cannot
revert them. When any requested op is one of those, the call auto-checkpoints
first (before applying anything) so recovery stays honest: restore the
checkpoint instead of relying on undo."""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from ..dispatcher import HandlerError
from . import naming, sculpt_math

MAX_OPS = 20
FALLOFFS = ("smooth", "linear")
VERTEX_OPS = {"soft_move", "inflate_region", "displace_noise"}


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _om_mesh(mesh_long: str):
    import maya.api.OpenMaya as om  # noqa: PLC0415

    sel = om.MSelectionList()
    sel.add(mesh_long)
    dag = sel.getDagPath(0)
    return om, om.MFnMesh(dag)


def _num(op: Dict[str, Any], key: str, default=None, positive=False) -> float:
    value = op.get(key, default)
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HandlerError(
            "op %r needs numeric %r" % (op.get("op"), key),
            hint="e.g. %s=1.5" % key,
        )
    if positive and value <= 0:
        raise HandlerError("%r must be positive" % key, hint="got %r" % value)
    return float(value)


def _resolve_center(om, fn, op: Dict[str, Any]):
    if "vertex_id" in op:
        vid = op["vertex_id"]
        if not isinstance(vid, int) or not (0 <= vid < fn.numVertices):
            raise HandlerError(
                "vertex_id %r out of range (mesh has %d verts)" % (vid, fn.numVertices),
                hint="vertex ids are 0-indexed",
            )
        p = fn.getPoint(vid, om.MSpace.kWorld)
        return [p.x, p.y, p.z]
    center = op.get("center")
    if (
        not isinstance(center, (list, tuple)) or len(center) != 3
        or not all(isinstance(v, (int, float)) for v in center)
    ):
        raise HandlerError(
            "op %r needs center=[x,y,z] or vertex_id" % op.get("op"),
            hint="world-space coordinates",
        )
    return [float(v) for v in center]


def _weighted_offset(mesh_long: str, op: Dict[str, Any], along_normal: bool) -> None:
    om, fn = _om_mesh(mesh_long)
    center = _resolve_center(om, fn, op)
    radius = _num(op, "radius", positive=True)
    falloff = op.get("falloff", "smooth")
    if falloff not in FALLOFFS:
        raise HandlerError(
            "unknown falloff %r" % falloff, hint="valid: smooth, linear"
        )
    if along_normal:
        amount = _num(op, "amount")
        normals = fn.getVertexNormals(False, om.MSpace.kWorld)
    else:
        delta = op.get("delta")
        if not isinstance(delta, (list, tuple)) or len(delta) != 3:
            raise HandlerError(
                "soft_move needs delta=[dx,dy,dz]", hint="world-space offset"
            )
        delta = [float(v) for v in delta]
    points = fn.getPoints(om.MSpace.kWorld)
    out = om.MPointArray()
    c = om.MPoint(*center)
    for i in range(len(points)):
        p = points[i]
        w = sculpt_math.falloff_weight(p.distanceTo(c), radius, falloff)
        if along_normal:
            n = normals[i]
            out.append(om.MPoint(p.x + n.x * amount * w, p.y + n.y * amount * w,
                                 p.z + n.z * amount * w))
        else:
            out.append(om.MPoint(p.x + delta[0] * w, p.y + delta[1] * w,
                                 p.z + delta[2] * w))
    fn.setPoints(out, om.MSpace.kWorld)


def _op_soft_move(cmds, mesh_long: str, op: Dict[str, Any]) -> None:
    _weighted_offset(mesh_long, op, along_normal=False)


def _op_inflate_region(cmds, mesh_long: str, op: Dict[str, Any]) -> None:
    _weighted_offset(mesh_long, op, along_normal=True)


def _op_displace_noise(cmds, mesh_long: str, op: Dict[str, Any]) -> None:
    amp = _num(op, "amp", 0.05, positive=True)
    freq = _num(op, "freq", 2.6, positive=True)
    octaves = op.get("octaves", 2)
    if not isinstance(octaves, int) or not (1 <= octaves <= 6):
        raise HandlerError("octaves must be an integer 1..6", hint="2 matches the golem recipe")
    om, fn = _om_mesh(mesh_long)
    points = fn.getPoints(om.MSpace.kWorld)
    normals = fn.getVertexNormals(False, om.MSpace.kWorld)
    out = om.MPointArray()
    for i in range(len(points)):
        p = points[i]
        d = sculpt_math.fbm(p.x * freq, p.y * freq, p.z * freq, octaves) * amp
        n = normals[i]
        out.append(om.MPoint(p.x + n.x * d, p.y + n.y * d, p.z + n.z * d))
    fn.setPoints(out, om.MSpace.kWorld)
    soften = op.get("soften_angle")
    if soften is not None:
        cmds.polySoftEdge(mesh_long, angle=float(soften), constructionHistory=False)


def _components(mesh_long: str, spec: Any, kind: str, key: str) -> str:
    if not isinstance(spec, str) or not spec.startswith(kind + "["):
        raise HandlerError(
            "%s must be a component string like '%s[3:7]'" % (key, kind),
            hint="got %r" % (spec,),
        )
    return "%s.%s" % (mesh_long, spec)


def _op_smooth(cmds, mesh_long: str, op: Dict[str, Any]) -> None:
    divisions = op.get("divisions", 1)
    if not isinstance(divisions, int) or not (1 <= divisions <= 3):
        raise HandlerError("divisions must be 1..3", hint="each level quadruples polycount")
    cmds.polySmooth(mesh_long, divisions=divisions, constructionHistory=False)


def _op_extrude_faces(cmds, mesh_long: str, op: Dict[str, Any]) -> None:
    faces = _components(mesh_long, op.get("faces"), "f", "faces")
    cmds.polyExtrudeFacet(
        faces, localTranslateZ=_num(op, "distance"),
        keepFacesTogether=bool(op.get("keep_together", True)),
        constructionHistory=False,
    )


def _op_bevel_edges(cmds, mesh_long: str, op: Dict[str, Any]) -> None:
    edges = _components(mesh_long, op.get("edges"), "e", "edges")
    segments = op.get("segments", 1)
    if not isinstance(segments, int) or not (1 <= segments <= 10):
        raise HandlerError("segments must be 1..10", hint="got %r" % (segments,))
    cmds.polyBevel3(
        edges, offset=_num(op, "width", positive=True), segments=segments,
        chamfer=True, constructionHistory=False,
    )


def _op_crease_edges(cmds, mesh_long: str, op: Dict[str, Any]) -> None:
    edges = _components(mesh_long, op.get("edges"), "e", "edges")
    amount = _num(op, "amount")
    if not (0.0 <= amount <= 10.0):
        raise HandlerError("amount must be 0..10", hint="stone-plate joints read well near 2-4")
    cmds.polyCrease(edges, value=amount)


def _op_bridge(cmds, mesh_long: str, op: Dict[str, Any]) -> None:
    edges_a = _components(mesh_long, op.get("edges_a"), "e", "edges_a")
    edges_b = _components(mesh_long, op.get("edges_b"), "e", "edges_b")
    cmds.select(edges_a, edges_b, replace=True)
    try:
        cmds.polyBridgeEdge(constructionHistory=False)
    finally:
        cmds.select(clear=True)


_OPS: Dict[str, Callable] = {
    "soft_move": _op_soft_move,
    "inflate_region": _op_inflate_region,
    "displace_noise": _op_displace_noise,
    "smooth": _op_smooth,
    "extrude_faces": _op_extrude_faces,
    "bevel_edges": _op_bevel_edges,
    "crease_edges": _op_crease_edges,
    "bridge": _op_bridge,
}


def sculpt_ops(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    mesh_long, _ = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    ops = params.get("ops")
    if not isinstance(ops, list) or not ops or len(ops) > MAX_OPS:
        raise HandlerError(
            "ops must be a list of 1..%d operations" % MAX_OPS,
            hint='e.g. ops=[{"op": "displace_noise", "amp": 0.06, "freq": 2.6}]',
        )
    # Validate every op tag up front, before applying anything, so an
    # invalid list never burns an auto-checkpoint. Per-op param validation
    # (numbers, components, falloff names, ...) stays inside each op
    # function and still runs at apply time below.
    kinds: List[str] = []
    for index, op in enumerate(ops):
        kind = op.get("op") if isinstance(op, dict) else None
        if not isinstance(kind, str) or kind not in _OPS:
            raise HandlerError(
                "op %d: unknown op %r" % (index, kind),
                hint="valid ops: %s" % ", ".join(sorted(_OPS)),
            )
        kinds.append(kind)

    checkpoint_path = None
    if any(kind in VERTEX_OPS for kind in kinds):
        from . import session  # noqa: PLC0415

        checkpoint_path = session.auto_checkpoint("sculpt")

    applied: List[str] = []
    for index, op in enumerate(ops):
        kind = kinds[index]
        try:
            _OPS[kind](cmds, mesh_long, op)
        except HandlerError as exc:
            involves_vertex_op = kind in VERTEX_OPS or any(
                k in VERTEX_OPS for k in applied
            )
            if involves_vertex_op:
                revert = "restore the auto-checkpoint taken at the start of this call"
            else:
                revert = "maya_undo(1) reverts this whole call"
            raise HandlerError(
                "op %d (%s) failed: %s; ops %s were already applied"
                % (index, kind, exc, applied or "none"),
                hint=(exc.hint or "") + " — applied ops stay; " + revert,
            ) from None
        applied.append(kind)

    warnings: List[str] = []
    if checkpoint_path is not None:
        vertex_ops_applied = [kind for kind in applied if kind in VERTEX_OPS]
        warnings.append(
            "ops [%s] modify vertices via the Maya API and are NOT undoable "
            "with maya_undo; to revert this call, restore the auto-checkpoint"
            % ", ".join(vertex_ops_applied)
        )

    tris = cmds.polyEvaluate(mesh_long, triangle=True)
    return {
        "applied": len(applied),
        "ops": applied,
        "tris": tris,
        "warnings": warnings,
        "checkpoint": checkpoint_path,
    }
