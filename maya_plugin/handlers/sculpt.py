"""sculpt_ops: the golem-maker (§5.3). Ops apply in order; the first failure
aborts with a report of what landed (one undo chunk for the five cmds-based
ops - maya_undo reverts all of those).

Three ops (soft_move, inflate_region, displace_noise) write vertices via
MFnMesh.setPoints, which Maya's undo queue does not track - maya_undo cannot
revert them. When any requested op is one of those, the call auto-checkpoints
first (before applying anything) so recovery stays honest: restore the
checkpoint instead of relying on undo."""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from ..dispatcher import HandlerError
from . import naming, sculpt_math, units

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

    checkpoint_info = None
    if any(kind in VERTEX_OPS for kind in kinds):
        from . import session  # noqa: PLC0415

        checkpoint_info = session.auto_checkpoint("sculpt")

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


def deform(params: Dict[str, Any]) -> Dict[str, Any]:
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
