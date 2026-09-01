"""sculpt_ops: the golem-maker (§5.3). Ops apply in order; the first failure
aborts with a report of what landed (one undo chunk for the nine cmds-based
ops - maya_undo reverts all of those).

Three ops (soft_move, inflate_region, displace_noise) write vertices via
MFnMesh.setPoints, which Maya's undo queue does not track - maya_undo cannot
revert them. When any requested op is one of those, the call auto-checkpoints
first (before applying anything) so recovery stays honest: restore the
checkpoint instead of relying on undo."""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from ..dispatcher import HandlerError, require_known_keys
from . import naming, sculpt_math, units

MAX_OPS = 20
FALLOFFS = ("smooth", "linear")
VERTEX_OPS = {"soft_move", "inflate_region", "displace_noise"}


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _om_mesh_dag(mesh_long: str):
    import maya.api.OpenMaya as om  # noqa: PLC0415

    sel = om.MSelectionList()
    sel.add(mesh_long)
    dag = sel.getDagPath(0)
    return om, dag


def _om_mesh(mesh_long: str):
    om, dag = _om_mesh_dag(mesh_long)
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
        # bool is a subclass of int, so the isinstance check alone accepts
        # center=[True, False, True] as coordinates - modeling._vec3 excludes
        # it explicitly and this must match.
        or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in center
        )
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
    # #636's sibling: a radius smaller than the distance to the nearest vertex
    # gives every vertex weight 0, and the op reported applied:1 having moved
    # nothing (chest girdle 2.2 wide, radius 0.9, nearest vertex 1.23 away).
    # Checked here, before setPoints, so the mesh is untouched when it fails.
    nearest = min((p.distanceTo(c) for p in points), default=0.0)
    if points and nearest >= radius:
        raise HandlerError(
            "radius %.6g does not reach the mesh: the nearest vertex is %.6g "
            "from the center, so every vertex weighs 0" % (radius, nearest),
            hint="use radius > %.6g, or move center onto the region you meant "
                 "(vertex_id picks a vertex directly)" % nearest,
        )
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


def _single_component_index(spec: Any, kind: str, key: str) -> int:
    """Parse a single-index component string ('e[12]') to its raw int index.

    insert_loop/extrude_edges/split all need a raw index, not a component
    string: polySplitRing and polySplit take rootEdge=/insertpoint=(idx, t)
    directly (Measured by evals/cage_probe_769.py - passing a component
    string straight to polySplitRing prints "Can't perform polySplitRing1 on
    selection" and silently changes nothing, no exception). Refusing a range
    or list here (rather than silently taking its first index) is what makes
    `len(edges)` in extrude_edges/split actually count edges - a range like
    'e[0:3]' would otherwise pass and undercount by a factor of the range
    size.
    """
    if not isinstance(spec, str) or not spec.startswith(kind + "["):
        raise HandlerError(
            "%s must be a single component like '%s[12]'" % (key, kind),
            hint="got %r" % (spec,),
        )
    inner = spec[len(kind) + 1:]
    if not inner.endswith("]"):
        raise HandlerError(
            "%s must look like '%s[12]'" % (key, kind), hint="got %r" % (spec,)
        )
    inner = inner[:-1]
    if not inner.isdigit():
        raise HandlerError(
            "%s must address exactly one %s (a single index), not a range "
            "or list" % (key, kind),
            hint="got %r; use e.g. '%s[12]', not '%s[0:3]'" % (spec, kind, kind),
        )
    return int(inner)


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
    # polyBridgeEdge has no component arguments - it only reads the active
    # selection - so this is the one op that cannot address geometry by name.
    # It must therefore put the user's selection back: clearing it (what this
    # did before) silently throws away whatever an artist had selected in the
    # live session, which breaks the module contract that tools never disturb
    # selection state (soft_move deliberately uses OpenMaya offsets rather
    # than softSelect for exactly this reason).
    previous = cmds.ls(selection=True, long=True) or []
    cmds.select(edges_a, edges_b, replace=True)
    try:
        cmds.polyBridgeEdge(constructionHistory=False)
    finally:
        if previous:
            cmds.select(previous, replace=True)
        else:
            cmds.select(clear=True)


INSERT_LOOP_KEYS = {"op", "edge", "count", "position"}


def _op_insert_loop(cmds, mesh_long: str, op: Dict[str, Any]) -> Dict[str, Any]:
    """Wraps polySplitRing - how a subdivision cage keeps its silhouette under
    `smooth`: an unsupported flat span collapses toward its neighbours'
    average when smoothed, and a loop near the edge gives smooth something to
    hold onto.

    Measured by evals/cage_probe_769.py:
    - the edge must be selected via polySelect(edgeRing=idx) BEFORE
      polySplitRing runs; passing a component string straight to
      polySplitRing prints a Maya warning and silently changes nothing (no
      exception - this is why `edge` is resolved to a raw index here, never
      forwarded as a string).
    - `count`==1 uses splitType=1 with weight=`position`, landing the loop at
      exactly that fraction of the edge's own span (weight 0.25/0.5/0.75 all
      measured exact).
    - `count`>1 uses splitType=2 with divisions=`count`, which distributes N
      loops evenly across (0,1) and IGNORES weight/`position` entirely - this
      is the only reliable multi-loop path measured: repeated single calls at
      the same edge do NOT distribute evenly (the index renumbers to the
      lower remaining sub-segment after each split, nesting toward one end).
      `count`>1 with `position` given is refused outright (2026-08-29
      fix-review): silently ignoring a param the caller set is the #764
      failure mode.
    - per-loop yield on an N-around ring is +N vertices, +2N edges, +N faces.
    - a changed-nothing result (edge count unchanged after the call) is
      refused (2026-08-29 fix-review): polySplitRing on un-probed topology
      (a ring interrupted by a triangle, or a boundary edge with no ring to
      walk) prints a warning and silently changes nothing - no exception.
    """
    require_known_keys(op, INSERT_LOOP_KEYS, "insert_loop")
    idx = _single_component_index(op.get("edge"), "e", "edge")
    count = op.get("count", 1)
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise HandlerError(
            "insert_loop needs count >= 1", hint="got %r" % (count,)
        )
    if count > 1 and "position" in op:
        # Measured (evals/cage_probe_769.py): count>1 uses splitType=2,
        # which distributes loops evenly across (0,1) and IGNORES
        # weight/position entirely - so a caller passing both is asking for
        # something Maya silently will not do. #764 doctrine: refuse the
        # combination rather than accept it and do something else.
        raise HandlerError(
            "insert_loop needs position to be omitted when count > 1",
            hint="splitType=2 (count>1) distributes loops evenly across "
                 "(0,1) and measured to ignore weight/position entirely; "
                 "position only applies when count=1 - drop 'position' or "
                 "set count=1",
        )
    position = op.get("position", 0.5)
    if (
        not isinstance(position, (int, float)) or isinstance(position, bool)
        or not (0.0 <= position <= 1.0)
    ):
        raise HandlerError(
            "insert_loop needs position in 0..1", hint="got %r" % (position,)
        )
    edges_before = cmds.polyEvaluate(mesh_long, edge=True)
    faces_before = cmds.polyEvaluate(mesh_long, face=True)
    cmds.polySelect(mesh_long, edgeRing=idx)
    if count == 1:
        cmds.polySplitRing(
            rootEdge=idx, splitType=1, weight=float(position),
            constructionHistory=False,
        )
    else:
        cmds.polySplitRing(
            rootEdge=idx, splitType=2, divisions=count,
            constructionHistory=False,
        )
    edges_after = cmds.polyEvaluate(mesh_long, edge=True)
    faces_after = cmds.polyEvaluate(mesh_long, face=True)
    if edges_after == edges_before:
        # Measured (evals/cage_probe_769.py): polySplitRing on un-probed
        # topology (a ring interrupted by a triangle, or a boundary edge
        # that has no ring to walk) prints a Maya warning and silently
        # changes nothing - no exception. Reporting "success" with an
        # unchanged mesh is exactly the "reported success, changed less
        # than asked" failure this codebase has been burned by before
        # (#636) - refuse it here instead.
        raise HandlerError(
            "insert_loop reported success but changed nothing: edge count "
            "stayed at %d (faces stayed at %d) - Maya declined the "
            "polySplitRing silently" % (edges_before, faces_before),
            hint="the ring may be interrupted by a triangle or a mesh "
                 "boundary, or edge %d may not support this split; try a "
                 "different edge" % idx,
        )
    return {
        "loops_inserted": count,
        "edges_before": edges_before, "edges_after": edges_after,
        "faces_before": faces_before, "faces_after": faces_after,
    }


EXTRUDE_EDGES_KEYS = {"op", "edges", "translate", "divisions"}


def _op_extrude_edges(cmds, mesh_long: str, op: Dict[str, Any]) -> Dict[str, Any]:
    """Wraps polyExtrudeEdge. Measured by evals/cage_probe_769.py:
    `translate` is a literal WORLD-SPACE offset (an edge at y=0 with
    translate=(0,2,0) lands its new vertices at exactly y=2, not a
    normal-relative offset), and new-face yield is EXACTLY
    `len(edges) * divisions` for every combination tested (1/3 edges x
    1/2 divisions, border and interior edges alike) - checked below and
    raised on any mismatch, because a silent short count on a cage op is
    exactly the kind of "reported success, changed less than asked"
    failure this codebase has been burned by before (#636).
    """
    require_known_keys(op, EXTRUDE_EDGES_KEYS, "extrude_edges")
    spec = op.get("edges")
    if not isinstance(spec, list) or not spec:
        raise HandlerError(
            "extrude_edges needs a non-empty edges list",
            hint="e.g. edges=['e[3]', 'e[5]']",
        )
    indices = [
        _single_component_index(item, "e", "edges[%d]" % i)
        for i, item in enumerate(spec)
    ]
    edge_strs = ["%s.e[%d]" % (mesh_long, idx) for idx in indices]
    translate = op.get("translate")
    if (
        not isinstance(translate, (list, tuple)) or len(translate) != 3
        or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool)
            for v in translate
        )
    ):
        raise HandlerError(
            "extrude_edges needs translate=[dx,dy,dz]",
            hint="a world-space offset; required because an extrude that "
                 "moves nothing is a no-op nobody wants silently",
        )
    translate = [float(v) for v in translate]
    if all(v == 0.0 for v in translate):
        raise HandlerError(
            "translate must not be [0,0,0]",
            hint="an extrude that moves nothing is a no-op nobody wants silently",
        )
    divisions = op.get("divisions", 1)
    if not isinstance(divisions, int) or isinstance(divisions, bool) or divisions < 1:
        raise HandlerError(
            "extrude_edges needs divisions >= 1", hint="got %r" % (divisions,)
        )
    faces_before = cmds.polyEvaluate(mesh_long, face=True)
    cmds.polyExtrudeEdge(
        edge_strs, translate=translate, divisions=divisions,
        constructionHistory=False,
    )
    faces_after = cmds.polyEvaluate(mesh_long, face=True)
    new_faces = faces_after - faces_before
    expected = len(edge_strs) * divisions
    if new_faces != expected:
        raise HandlerError(
            "extrude_edges expected %d new faces (%d edges x %d divisions) "
            "but Maya reported %d" % (expected, len(edge_strs), divisions, new_faces),
            hint="the mesh already applied - inspect it before retrying; "
                 "this invariant held in every configuration probed "
                 "(evals/cage_probe_769.py), so a mismatch means something "
                 "about this mesh's topology diverges from what was measured",
        )
    return {
        "faces_before": faces_before, "faces_after": faces_after,
        "new_faces": new_faces,
    }


# axis: polyMirrorFace's `axis` is the plane's NORMAL, fixed at world origin -
# Measured by evals/cage_probe_769.py: moving the mesh's own pivot/transform,
# or passing `worldSpace`, has zero effect on where the plane sits; only the
# unexposed `mirrorPlaneCenter` flag overrides world origin (YAGNI here - a
# mesh living away from the origin gets the measured-gap refusal below,
# which is an honest answer: move it to the plane, or pass allow_unmerged).
_MIRROR_AXIS = {"x": 0, "y": 1, "z": 2}
# polyMirrorFace's own `direction` flag is NOT exposed here (2026-08-29
# review, #764 doctrine: a measured-inert param is refused, not kept on
# speculation). Measured by evals/cage_probe_769.py: direction in
# {0, 1, -1, 2} produced byte-identical results in every whole-object
# invocation tested - the op's surface is axis-only about the world-origin
# plane, and the side that gets duplicated is whatever the probe recorded
# for that axis (for axis="x" on a half-cube spanning x in [-2,0], the
# duplicate always lands on the positive side, giving a closed box spanning
# [-2,2] - see docs/superpowers/specs/2026-08-29-cage-ops-design.md's
# mirror_topology bullet for the dated note). `direction` is refused by
# require_known_keys like any other unread key, listing the valid params.
# mergeThresholdType 1 (2 was byte-identical in the probed 40-cell grid, so
# either works - 1 is picked arbitrarily). Under mergeMode=1 + this type,
# Measured: merge succeeds iff `2 * offset < mergeThreshold` (strict), where
# `offset` is a border vertex's own one-sided distance from the plane (the
# actual cross-plane gap to its mirrored counterpart is `2 * offset`). Every
# successful merge in the grid snapped the border exactly onto the plane -
# there is no partial/averaged case.
_MIRROR_THRESHOLD_TYPE = 1
# merge_threshold default: 0.001 scene units (mm-scale in a metre-native
# scene). Derivation from the probed grid: our `merge_threshold` is the
# one-sided offset the caller tolerates, so Maya's mergeThreshold is set to
# 2x it; a seam within floating-point noise of the plane (offset ~1e-6, the
# case a boolean-delete-cap-face construction actually produces) merges
# under any positive value, while a deliberate 0.02-unit gap - the smallest
# "off" case in the probed grid - refuses: 2*0.02=0.04 is not < 2*0.001=0.002.
DEFAULT_MERGE_THRESHOLD = 0.001

MIRROR_TOPOLOGY_KEYS = {"op", "axis", "merge_threshold", "allow_unmerged"}


def _min_border_plane_gap(mesh_long: str, axis_idx: int) -> float:
    """Minimum distance from an open-border vertex to the mirror plane
    (world origin along `axis_idx` - see _MIRROR_AXIS above). +inf if the
    mesh has no open border (already closed)."""
    om, dag = _om_mesh_dag(mesh_long)
    fn = om.MFnMesh(dag)
    border_vert_ids = set()
    edge_it = om.MItMeshEdge(dag)
    while not edge_it.isDone():
        if edge_it.numConnectedFaces() == 1:
            border_vert_ids.add(edge_it.vertexId(0))
            border_vert_ids.add(edge_it.vertexId(1))
        edge_it.next()
    if not border_vert_ids:
        return float("inf")
    best = float("inf")
    for vid in border_vert_ids:
        p = fn.getPoint(vid, om.MSpace.kWorld)
        best = min(best, abs((p.x, p.y, p.z)[axis_idx]))
    return best


def _op_mirror_topology(cmds, mesh_long: str, op: Dict[str, Any]) -> Dict[str, Any]:
    """Wraps polyMirrorFace. REFUSES an unmerged result: after the op, shell
    count is measured, and anything other than exactly one shell fails with
    the pre-op minimum border-to-plane gap in the message, unless
    `allow_unmerged=true` was passed. See _MIRROR_AXIS/_MIRROR_THRESHOLD_TYPE/
    DEFAULT_MERGE_THRESHOLD above for what was measured and why.
    """
    require_known_keys(op, MIRROR_TOPOLOGY_KEYS, "mirror_topology")
    axis = op.get("axis")
    if axis not in _MIRROR_AXIS:
        raise HandlerError(
            "mirror_topology needs axis in 'x'/'y'/'z'", hint="got %r" % (axis,)
        )
    merge_threshold = op.get("merge_threshold", DEFAULT_MERGE_THRESHOLD)
    if (
        not isinstance(merge_threshold, (int, float))
        or isinstance(merge_threshold, bool) or merge_threshold < 0
    ):
        raise HandlerError(
            "mirror_topology needs merge_threshold >= 0",
            hint="got %r; it is the max distance a border vertex may sit "
                 "from the mirror plane and still merge (default %.6g)"
                 % (merge_threshold, DEFAULT_MERGE_THRESHOLD),
        )
    allow_unmerged = bool(op.get("allow_unmerged", False))
    axis_idx = _MIRROR_AXIS[axis]

    pre_gap = _min_border_plane_gap(mesh_long, axis_idx)
    vertices_before = cmds.polyEvaluate(mesh_long, vertex=True)
    cmds.polyMirrorFace(
        mesh_long, axis=axis_idx,
        mergeMode=1, mergeThreshold=2.0 * float(merge_threshold),
        mergeThresholdType=_MIRROR_THRESHOLD_TYPE, constructionHistory=False,
    )
    vertices_after = cmds.polyEvaluate(mesh_long, vertex=True)
    shells = cmds.polyEvaluate(mesh_long, shell=True)
    merged_vertices = max(0, 2 * vertices_before - vertices_after)

    if shells != 1 and not allow_unmerged:
        raise HandlerError(
            "mirror_topology produced %d shells, not 1: the open border did "
            "not merge (measured minimum border-to-plane gap before the op: "
            "%.6g, merge_threshold was %.6g)" % (shells, pre_gap, merge_threshold),
            hint="raise merge_threshold above %.6g, move the open border "
                 "onto the mirror plane, or pass allow_unmerged=true to keep "
                 "the unmerged result" % pre_gap,
        )
    return {
        "shells": shells, "merged_vertices": merged_vertices,
        "vertices_before": vertices_before, "vertices_after": vertices_after,
    }


SPLIT_KEYS = {"op", "points"}


def _op_split(cmds, mesh_long: str, op: Dict[str, Any]) -> Dict[str, Any]:
    """Wraps polySplit. Measured by evals/cage_probe_769.py: insertpoint takes
    plain (edgeIndex, t) tuples - raw indices, no component-string prefix,
    unlike every other op here - and a SINGLE insertpoint is a silent no-op
    (returns success, changes nothing); the >=2-entry requirement below is
    load-bearing, not just tidiness.

    A changed-nothing result (edge count unchanged after the call) is
    refused too (2026-08-29 fix-review): polySplit can silently no-op on an
    invalid path (points on the same edge with an equal or degenerate `t`,
    or a path Maya cannot triangulate) even with >=2 entries, printing a
    warning rather than raising.
    """
    require_known_keys(op, SPLIT_KEYS, "split")
    points = op.get("points")
    if not isinstance(points, list) or len(points) < 2:
        raise HandlerError(
            "split needs points=[[edge, t], ...] with at least 2 entries",
            hint="a single insertpoint is a silent no-op in Maya (measured); "
                 "e.g. points=[['e[0]', 0.5], ['e[2]', 0.5]]",
        )
    insertpoints = []
    for i, pair in enumerate(points):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise HandlerError(
                "split needs points[%d] to be [edge, t]" % i, hint="got %r" % (pair,)
            )
        edge_spec, t = pair
        idx = _single_component_index(edge_spec, "e", "points[%d][0]" % i)
        if not isinstance(t, (int, float)) or isinstance(t, bool) or not (0.0 <= t <= 1.0):
            raise HandlerError(
                "split needs points[%d][1] (t) in 0..1" % i, hint="got %r" % (t,)
            )
        insertpoints.append((idx, float(t)))
    edges_before = cmds.polyEvaluate(mesh_long, edge=True)
    faces_before = cmds.polyEvaluate(mesh_long, face=True)
    cmds.polySplit(mesh_long, insertpoint=insertpoints, constructionHistory=False)
    edges_after = cmds.polyEvaluate(mesh_long, edge=True)
    faces_after = cmds.polyEvaluate(mesh_long, face=True)
    if edges_after == edges_before:
        raise HandlerError(
            "split reported success but changed nothing: edge count stayed "
            "at %d (faces stayed at %d) - Maya declined the polySplit "
            "silently" % (edges_before, faces_before),
            hint="the split path may be invalid for this topology (e.g. "
                 "points landing on the same spot, or a path Maya cannot "
                 "triangulate); try different points",
        )
    return {
        "edges_before": edges_before, "edges_after": edges_after,
        "faces_before": faces_before, "faces_after": faces_after,
    }


_OPS: Dict[str, Callable] = {
    "soft_move": _op_soft_move,
    "inflate_region": _op_inflate_region,
    "displace_noise": _op_displace_noise,
    "smooth": _op_smooth,
    "extrude_faces": _op_extrude_faces,
    "bevel_edges": _op_bevel_edges,
    "crease_edges": _op_crease_edges,
    "bridge": _op_bridge,
    "insert_loop": _op_insert_loop,
    "extrude_edges": _op_extrude_edges,
    "mirror_topology": _op_mirror_topology,
    "split": _op_split,
}


# Every top-level key sculpt_ops reads (#767). Per-op dicts are validated
# separately (INSERT_LOOP_KEYS and friends) - that is a different question
# from what arrived at the top level.
SCULPT_OPS_KEYS = ("mesh", "ops")
SCULPT_OPS_SYNONYMS = {"operations": "ops"}


def sculpt_ops(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, SCULPT_OPS_KEYS, "sculpt_ops",
                       SCULPT_OPS_SYNONYMS)
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

    checkpoint_info = None
    if any(kind in VERTEX_OPS for kind in kinds):
        from . import session  # noqa: PLC0415

        checkpoint_info = session.auto_checkpoint("sculpt")

    applied: List[str] = []
    op_results: List[Dict[str, Any]] = []
    for index, op in enumerate(ops):
        kind = kinds[index]
        try:
            result = _OPS[kind](cmds, mesh_long, op)
        except HandlerError as exc:
            involves_vertex_op = kind in VERTEX_OPS or any(
                k in VERTEX_OPS for k in applied
            )
            if involves_vertex_op:
                revert = (
                    "restore the auto-checkpoint taken at the start of this call "
                    "(checkpoint_id=%r) via maya_restore_checkpoint"
                    % checkpoint_info["checkpoint_id"]
                )
            else:
                revert = "maya_undo(1) reverts this whole call"
            raise HandlerError(
                "op %d (%s) failed: %s; ops %s were already applied"
                % (index, kind, exc, applied or "none"),
                hint=(exc.hint or "") + " — applied ops stay; " + revert,
            ) from None
        applied.append(kind)
        if result:
            op_results.append(dict(result, op=kind))

    warnings: List[str] = []
    if checkpoint_info is not None:
        vertex_ops_applied = [kind for kind in applied if kind in VERTEX_OPS]
        warnings.append(
            "ops [%s] modify vertices via the Maya API and are NOT undoable "
            "with maya_undo; to revert this call, pass checkpoint_id=%r to "
            "maya_restore_checkpoint"
            % (", ".join(vertex_ops_applied), checkpoint_info["checkpoint_id"])
        )

    tris = cmds.polyEvaluate(mesh_long, triangle=True)
    return {
        "applied": len(applied),
        "ops": applied,
        "tris": tris,
        "warnings": warnings,
        "checkpoint_id": checkpoint_info["checkpoint_id"] if checkpoint_info else None,
        # Per-op measured results (before/after counts, mirror's
        # shells/merged_vertices, ...) for the four cage ops; the eight
        # original ops return None and contribute nothing here. Declared on
        # SculptResult (schemas.py) as Optional[List[Dict]], so it reaches
        # real MCP callers too, not just direct sculpt_ops() callers.
        "op_results": op_results,
    }


# cmds.nonLinear's six types. sculpt and lattice are separate commands with
# separate return shapes and are handled on their own branches below.
NONLINEAR_TYPES = frozenset({"bend", "flare", "sine", "squash", "twist", "wave"})

DEFORMER_WHITELIST = {
    "bend": {"curvature", "lowBound", "highBound", "rotate", "translate"},
    "squash": {"factor", "lowBound", "highBound", "rotate", "translate"},
    "twist": {"startAngle", "endAngle", "lowBound", "highBound", "rotate", "translate"},
    # The taper. Without this, "a limb thick at the shoulder and thin at the
    # wrist" is not expressible and every limb is a uniform tube.
    "flare": {"curve", "startFlareX", "startFlareZ", "endFlareX", "endFlareZ",
              "lowBound", "highBound", "rotate", "translate"},
    "sine": {"amplitude", "wavelength", "offset", "dropoff",
             "lowBound", "highBound", "rotate", "translate"},
    # wave is bounded RADIALLY in the XZ plane, not along an axis - it has no
    # lowBound/highBound at all. The whitelist is per-type precisely so this
    # asymmetry is enforced rather than merely documented.
    "wave": {"amplitude", "wavelength", "offset", "dropoff",
             "minRadius", "maxRadius", "rotate", "translate"},
    "sculpt": {"maxDisplacement", "dropoffDistance", "translate", "rotate"},
    "lattice": {"divisions", "translate", "rotate"},
}

# Below this fraction of the mesh's own bounding-box diagonal, a deformation is
# not something anyone asked for on purpose - it is the "reported success,
# moved nothing" failure (#636) and must be reported as such. 1% separates the
# two cases by an order of magnitude at both ends: the golem's inert bend moved
# 0.07% and a 45-degree bend on a test cylinder moves 14%. The measured number
# always ships in max_displacement, so deliberately subtle work can read it and
# ignore the line.
NOOP_DISPLACEMENT_RATIO = 1e-2

# Why a deformer of each type can end up inert, in the order worth checking.
# bend leads with the unit because that IS #636: curvature is an ANGLE, so
# `curvature: 0.35` asks for a third of a degree and gets exactly that.
_INERT_HINTS = {
    "bend": "curvature is an ANGLE IN DEGREES (0.35 = a third of a degree, "
            "not a bend) - a visible hunch is 20-60",
    "twist": "startAngle/endAngle are DEGREES - a visible twist is 30+",
    "squash": "factor is a ratio around 0 (-0.5 squashes, 0.5 stretches); 0 is "
              "the identity",
    "flare": "startFlare*/endFlare* are multipliers around 1.0; 1.0 is the "
             "identity",
    "sine": "amplitude is in scene units, not a ratio, and wavelength must be "
            "smaller than the mesh for a wave to be visible",
    "wave": "amplitude is in scene units, and minRadius/maxRadius bound the "
            "wave radially in XZ - not along an axis",
    "sculpt": "maxDisplacement is in scene units and the sculpt sphere must "
              "overlap the mesh",
    "lattice": "a lattice deforms nothing until its points are moved - this "
               "call only builds it",
}


def vertex_positions(cmds, mesh_long: str) -> List[float]:
    """World-space vertex positions, flat [x,y,z,x,y,z,...].

    Deliberately not exactWorldBoundingBox: that transforms the object-space
    box and over-reports any rotated mesh. Vertices are the ground truth.
    """
    flat = cmds.xform(
        mesh_long + ".vtx[*]", query=True, worldSpace=True, translation=True
    )
    return list(flat or [])


def _set_deformer_attr(cmds, node: str, attr: str, value: Any) -> None:
    """setAttr, converting degrees into whatever angle unit this scene uses.

    Angle-typed attributes (bend.curvature, twist.startAngle/endAngle) are read
    by setAttr in the current UI angular unit. Every other attribute is unitless
    or linear and passes straight through.
    """
    plug = "%s.%s" % (node, attr)
    if cmds.getAttr(plug, type=True) == "doubleAngle":
        value = units.degrees_to_ui(cmds, value)
    cmds.setAttr(plug, value)


# Every top-level key deform reads (#767). The nested `params` dict is
# already refused per deformer type against DEFORMER_WHITELIST below.
# `type` is the generic word for `deformer`; `bake`/`baked` are what a
# caller reaches for when they mean delete_history_after, and none of the
# three shares a 3-char prefix with the key it means.
DEFORM_KEYS = ("mesh", "deformer", "params", "delete_history_after")
DEFORM_SYNONYMS = {"type": "deformer", "bake": "delete_history_after",
                   "baked": "delete_history_after"}


def deform(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, DEFORM_KEYS, "deform", DEFORM_SYNONYMS)
    cmds = _cmds()
    mesh_long, _ = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    deformer = params.get("deformer")
    if deformer not in DEFORMER_WHITELIST:
        raise HandlerError(
            "unknown deformer %r" % deformer,
            hint="valid: %s" % ", ".join(sorted(DEFORMER_WHITELIST)),
        )
    # Copy before popping so we never mutate the caller's params dict.
    dparams = dict(params.get("params") or {})
    unknown = set(dparams) - DEFORMER_WHITELIST[deformer]
    if unknown:
        raise HandlerError(
            "unknown params for %s: %s" % (deformer, ", ".join(sorted(unknown))),
            hint="valid params: %s" % ", ".join(sorted(DEFORMER_WHITELIST[deformer])),
        )
    handle_xform = {k: dparams.pop(k) for k in ("translate", "rotate") if k in dparams}
    # Measured before anything is built, compared at the very end - after the
    # attributes, after the handle placement, after any bake. #636 shipped a
    # bend that reported success and moved the mesh by 0.1% of its own height;
    # nothing short of the vertices could have caught that.
    before = vertex_positions(cmds, mesh_long)
    if deformer == "lattice":
        divisions = dparams.get("divisions", [2, 5, 2])
        # cmds.lattice returns [ffd, lattice, base]. Deformation is driven by
        # the *relative offset* between the lattice and its base, so nodes[1]
        # (the lattice itself) is the movable handle; nodes[2] (the base) is
        # a fixed reference frame — moving it instead would be a no-op/wrong.
        # Verified live in mayapy (see task-9-report.md fix addendum).
        nodes = cmds.lattice(
            mesh_long, divisions=divisions, objectCentered=True
        )
    elif deformer == "sculpt":
        # cmds.sculpt is a distinct command from cmds.nonLinear (nonLinear
        # only supports bend|flare|sine|squash|twist|wave — there is no
        # "sculpt" nonlinear type). It returns
        # [deformer, sculptOrigin, stretchOrigin]; moving nodes[1] (the
        # origin locator) pushes/pulls the mesh, matching the shared
        # nodes[1]-is-the-handle convention below. Verified live in mayapy.
        nodes = cmds.sculpt(mesh_long, **dparams)
    elif deformer in NONLINEAR_TYPES:
        # Create bare, then set each param as an ATTRIBUTE. Passing them as
        # creation flags works for some names and not others, and which is
        # which is not documented anywhere - that ambiguity is what made
        # adding new types risky. Every param in the whitelist above is an
        # attribute on the resulting deform* node under exactly this name, so
        # one path serves all six types and the question stops existing.
        nodes = cmds.nonLinear(mesh_long, type=deformer)
        for attr, value in dparams.items():
            _set_deformer_attr(cmds, nodes[0], attr, value)
    else:
        # Reached only if a type is added to DEFORMER_WHITELIST without also
        # adding it to NONLINEAR_TYPES (or wiring a lattice/sculpt-style
        # branch for it) - fail loudly rather than silently falling into the
        # nonLinear path with an unrecognised type name.
        raise HandlerError(
            "deformer %r is whitelisted but not wired to a dispatch branch" % deformer,
            hint="valid nonLinear types: %s; sculpt and lattice are separate "
            "commands with their own branches" % ", ".join(sorted(NONLINEAR_TYPES)),
        )
    # nodes[1] is the movable handle for every branch: nonLinear returns
    # [deformer, handle] (2 elements, so nodes[1] == nodes[-1]); lattice and
    # sculpt both return 3-element lists where nodes[1] is the deforming
    # node and nodes[2] is a fixed reference (base / stretch origin).
    handle = nodes[1]
    if "translate" in handle_xform:
        cmds.xform(handle, translation=handle_xform["translate"], worldSpace=True)
    if "rotate" in handle_xform:
        cmds.xform(handle, rotation=handle_xform["rotate"], worldSpace=True)
    moved = sculpt_math.max_displacement(before, vertex_positions(cmds, mesh_long))
    warnings = _inert_warnings(deformer, moved, sculpt_math.bbox_extent(before))
    if params.get("delete_history_after"):
        cmds.delete(mesh_long, constructionHistory=True)
        # constructionHistory delete only removes the deformer DG node, not
        # the handle transforms the deformer command created (ffd1Lattice/
        # ffd1Base for lattice, bendHandle/twistHandle for nonLinear, the
        # sculpt origin + stretch origin for sculpt) - nodes[1:] is exactly
        # that set (nodes[0] is the deformer node history already removed).
        # They are visible, get framed by viewFit, and render into captures
        # if left behind, so sweep them here rather than reporting baked=True
        # with orphans still in the scene.
        for handle in nodes[1:]:
            if cmds.objExists(handle):
                cmds.delete(handle)
        return {"deformer_nodes": [], "baked": True, "warnings": warnings,
                "max_displacement": moved}
    long_nodes = [(cmds.ls(n, long=True) or [n])[0] for n in nodes]
    return {"deformer_nodes": long_nodes, "baked": False, "warnings": warnings,
            "max_displacement": moved}


def _inert_warnings(deformer: str, moved: float, extent: float) -> List[str]:
    """One warning when the mesh did not visibly move. The measured number goes
    out either way, in max_displacement - the warning is for the case an agent
    would otherwise read `baked: true` as "the shape changed".

    lattice is exempt: a freshly built lattice deforms nothing until its points
    are moved, so warning on it would fire on every correct call and teach
    readers to skip the one warning that matters.
    """
    threshold = extent * NOOP_DISPLACEMENT_RATIO if extent > 0 else 1e-9
    if deformer == "lattice" or moved > threshold:
        return []
    return [
        "%s moved the mesh by %.6g (mesh extent %.6g) - that is not a visible "
        "deformation. %s" % (deformer, moved, extent, _INERT_HINTS[deformer])
    ]
