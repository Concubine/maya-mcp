"""maya_array: mirror, radial and linear copies of an existing object.

The source is never moved and never reparented - it is element 0 of the
finished array and stays exactly where the caller put it. Copies are real
duplicates rather than instances: instances share a shape node, which breaks
per-copy booleans, per-copy material assignment, and the move ledger's
per-object identity.

Placement arithmetic lives in arraymath.py, which has no Maya import and is
tested exhaustively headless. This module only drives cmds.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError
from . import arraymath, ledger, naming


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _long(cmds, name: str) -> str:
    return (cmds.ls(name, long=True) or [name])[0]


def _short(name: str) -> str:
    return name.split("|")[-1]


def _duplicate(cmds, source: str, prefix: str, index: int) -> str:
    new_name = naming.unique_name(cmds, "%s_%d" % (prefix, index))
    copy = cmds.duplicate(source, name=new_name, returnRootsOnly=True)[0]
    return _long(cmds, copy)


def _radial(cmds, source: str, prefix: str, params: Dict[str, Any]) -> List[str]:
    count = arraymath.resolve_count(params.get("count"))
    axis = params.get("axis") or "y"
    idx = arraymath.axis_index(axis)
    center = arraymath.resolve_vec3(params.get("center"), "center", [0.0, 0.0, 0.0])
    angle = params.get("angle", 360.0)
    if isinstance(angle, bool) or not isinstance(angle, (int, float)):
        raise HandlerError(
            "angle must be a number of degrees, got %r" % (angle,),
            hint="angle=360 for a full ring (the default); angle=180 for a half arc",
        )
    names: List[str] = []
    for i, degrees in enumerate(arraymath.radial_angles(count, float(angle)), start=1):
        copy = _duplicate(cmds, source, prefix, i)
        rotation = [0.0, 0.0, 0.0]
        rotation[idx] = degrees
        cmds.rotate(
            rotation[0], rotation[1], rotation[2], copy,
            pivot=tuple(center), relative=True, worldSpace=True,
        )
        names.append(copy)
    return names


def _linear(cmds, source: str, prefix: str, params: Dict[str, Any]) -> List[str]:
    steps = arraymath.linear_steps(
        params.get("count"),
        params.get("offset"),
        params.get("step_rotate"),
        params.get("step_scale"),
    )
    names: List[str] = []
    for i, step in enumerate(steps, start=1):
        copy = _duplicate(cmds, source, prefix, i)
        cmds.xform(copy, relative=True, worldSpace=True, translation=step["translate"])
        if any(step["rotate"]):
            cmds.xform(copy, relative=True, rotation=step["rotate"])
        if any(s != 1.0 for s in step["scale"]):
            cmds.xform(copy, relative=True, scale=step["scale"])
        names.append(copy)
    return names


def array(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    source = naming.require_object(cmds, str(params.get("name") or ""))
    mode = params.get("mode")
    if mode not in arraymath.MODES:
        raise HandlerError(
            "unknown mode %r" % (mode,),
            hint="valid modes: %s" % ", ".join(arraymath.MODES),
        )
    warnings = [w for w in [ledger.check(cmds, source)] if w]

    requested_prefix = params.get("name_prefix")
    if requested_prefix is not None and (
        not isinstance(requested_prefix, str) or not requested_prefix.strip()
    ):
        raise HandlerError(
            "name_prefix must be a non-empty string",
            hint="omit it to name copies after the source, or pass e.g. name_prefix='cog'",
        )
    prefix = (requested_prefix or _short(source)).strip()

    signed: Optional[float] = None
    if mode == "radial":
        names = _radial(cmds, source, prefix, params)
    elif mode == "linear":
        names = _linear(cmds, source, prefix, params)
    else:
        names, signed, mirror_warnings = _mirror(cmds, source, prefix, params)
        warnings.extend(mirror_warnings)

    group_name = params.get("group_name")
    group: Optional[str] = None
    if group_name is not None:
        if not isinstance(group_name, str) or not group_name.strip():
            raise HandlerError(
                "group_name must be a non-empty string",
                hint="omit it to leave the copies unparented, or pass e.g. group_name='gear'",
            )
        # Only the copies. Sweeping the caller's own object into a group we
        # invented would move it in the hierarchy behind their back.
        grp = cmds.group(*names, name=naming.unique_name(cmds, group_name.strip()))
        group = _long(cmds, grp)

        # cmds.group() reparents every copy, changing its long name. Query
        # Maya's actual post-group paths rather than trusting listRelatives'
        # ordering to match `names` positionally - Maya may auto-rename a
        # child on collision, same trap modeling.group() solves the same way.
        children = cmds.listRelatives(group, children=True, fullPath=True) or []
        resolved: List[str] = []
        for old_long in names:
            old_short = _short(old_long)
            new_long = next((c for c in children if _short(c) == old_short), None)
            if new_long is None:
                raise HandlerError(
                    "copy %r vanished while grouping into %r" % (old_long, group),
                    hint=(
                        "Maya may have renamed it on a name collision; call "
                        "maya_get_scene_graph to find its current name"
                    ),
                )
            resolved.append(new_long)
        names = resolved

    for name in names:
        ledger.record(cmds, name)

    return {
        "names": names,
        "mode": mode,
        "group": group,
        "signed_volume": signed,
        "warnings": warnings,
    }


def _mesh_signed_volume(cmds, transform: str) -> Optional[float]:
    """Signed volume of `transform`'s mesh in world space, or None if unmeasurable.

    Positive means outward winding. Negative means the faces point inward,
    which under Arnold renders black or hollow and reads as a lighting failure.

    `cmds` is unused here - it exists only so this function's signature
    matches what the tests monkeypatch it with (`lambda cmds, name: ...`).
    """
    try:
        import maya.api.OpenMaya as om  # noqa: PLC0415
    except ImportError:
        # Not running inside Maya - an environment fact, not a mesh
        # property. Caught on its own so it can't mask a real bug below.
        return None

    # Only the OpenMaya calls that can legitimately fail on a valid mesh -
    # e.g. one with no shape, an ambiguous shape, or otherwise non-standard
    # topology - are caught here. A typo or API misuse in the surrounding
    # Python (the list comprehensions below) is a genuine programming error
    # and must surface, not collapse into the same "unmeasurable" result as
    # a legitimately-untriangulable mesh.
    try:
        sel = om.MSelectionList()
        sel.add(transform)
        dag = sel.getDagPath(0)
        dag.extendToShape()
        mesh = om.MFnMesh(dag)
        raw_points = mesh.getPoints(om.MSpace.kWorld)
        _counts, indices = mesh.getTriangles()
    except Exception:
        return None

    points = [(p.x, p.y, p.z) for p in raw_points]
    triangles = [
        (indices[i], indices[i + 1], indices[i + 2])
        for i in range(0, len(indices), 3)
    ]
    if not triangles:
        return None
    return arraymath.signed_volume(points, triangles)


def _mirror(
    cmds, source: str, prefix: str, params: Dict[str, Any]
) -> Tuple[List[str], Optional[float], List[str]]:
    """One copy, reflected across the world plane perpendicular to `axis`.

    Two traps, both encoded here.

    The reflection goes on a temporary PARENT GROUP rather than on the copy's
    own scale. Negating a channel on the object composes as T*R*S*M, but a true
    reflection is M*T*R*S; those agree only when the object's rotation commutes
    with the mirror. An arm rotated outward, mirrored the naive way, lands in
    the wrong orientation - subtly, and invisibly at thumbnail scale.

    Then the freeze inverts face winding, because any negative scale does. The
    normals are reversed after the freeze (never before - doing it first just
    gets undone), and the result is MEASURED rather than assumed.

    `count` is ignored: a mirror produces exactly one image, so there is
    nothing for it to control.

    Requires a single-shape polygon mesh: `cmds.polyNormal` below and the
    signed-volume winding check both assume one mesh shape, and radial/linear
    legitimately accept groups or curves that `_mirror` cannot make sense of.
    """
    idx = arraymath.axis_index(params.get("axis") or "x")
    pivot = arraymath.resolve_vec3(params.get("pivot"), "pivot", [0.0, 0.0, 0.0])
    try:
        naming.require_mesh(cmds, source)
    except HandlerError as exc:
        raise HandlerError(
            str(exc),
            hint="mirror needs a single polygon mesh; mirror each chunk and group the results",
        ) from exc

    copy = _duplicate(cmds, source, prefix, 1)
    grp = cmds.group(copy, world=True, name=naming.unique_name(cmds, "%s_mirrorGrp" % prefix))
    grp = _long(cmds, grp)
    cmds.xform(grp, worldSpace=True, pivots=tuple(pivot))
    cmds.setAttr("%s.scale%s" % (grp, "XYZ"[idx]), -1.0)
    cmds.makeIdentity(grp, apply=True, translate=True, rotate=True, scale=True, normal=0)

    # cmds.group() above reparented `copy` under `grp`, so the path we are
    # still holding (e.g. "|tooth_1") no longer resolves to anything -
    # Maya raises rather than returning falsy. Re-resolve the child from the
    # group first; that is robust to Maya renaming the node on reparent,
    # which string concatenation is not.
    child = (cmds.listRelatives(grp, children=True, fullPath=True) or [copy])[0]
    unparented = cmds.parent(child, world=True) or [child]
    copy = _long(cmds, unparented[0])
    cmds.delete(grp)

    cmds.polyNormal(copy, normalMode=0, constructionHistory=False)
    cmds.delete(copy, constructionHistory=True)

    signed = _mesh_signed_volume(cmds, copy)
    warnings: List[str] = []
    if signed is None:
        # Absence of evidence is not evidence of absence: a genuinely
        # black, inward-facing mesh must not come back with a clean
        # warnings list just because the measurement itself never ran.
        warnings.append(
            "signed volume could not be measured on %s: the mirrored "
            "copy's face orientation is UNVERIFIED - check it renders "
            "solid rather than black." % copy
        )
    elif signed == 0.0:
        # Exactly zero means an open or degenerate mesh, not inverted
        # winding - the two are different failures with different fixes.
        warnings.append(
            "%s has signed volume 0.0: the mesh is open or degenerate, so "
            "orientation can't be judged from a zero volume - check it "
            "renders solid rather than black." % copy
        )
    elif signed < 0.0:
        warnings.append(
            "%s has signed volume %.4f: its winding is inverted, faces point "
            "INWARD. It will render black or hollow, which looks like a "
            "lighting failure and is not one. The mirror's normal reversal "
            "did not take." % (copy, signed)
        )
    return [copy], signed, warnings
