"""maya_combine: merge several meshes into one object, keeping them as shells.

Why this exists as its own command rather than boolean_op(op="union"): a union
WELDS topology. It recomputes intersections, collapses coincident faces, and
costs time proportional to the geometry - and #577 records it corrupting
shading-group membership on its output. None of that is wanted when the pieces
are deliberately separate solids that simply need to travel as one object,
which is the normal case for a kit piece or a chunk assembled from primitives.

polyUnite does exactly that and nothing more: N transforms in, one transform
out, each input surviving as its own closed shell.

Two behaviours are inherited from hard-won lessons elsewhere in this codebase:

  * the result is re-resolved by SHORT NAME, because Maya renames on collision
    and trusting the requested name silently operates on the wrong node
    (modeling.py carries the same note for grouping);
  * shading is collapsed to ONE OBJECT-LEVEL shading group, because uniting
    meshes with different shaders leaves per-face SG membership, which #577
    found to be the state that makes later per-face work silently no-op.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..dispatcher import HandlerError
from . import meshcheck, naming, session

PIVOT_MODES = ("center", "origin", "keep")


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _short(name: str) -> str:
    return name.split("|")[-1]


def _long(cmds, name: str) -> str:
    return (cmds.ls(name, long=True) or [name])[0]


def _require_mesh(cmds, transform: str) -> str:
    shapes = cmds.listRelatives(
        transform, shapes=True, fullPath=True, noIntermediate=True
    ) or []
    mesh = next((s for s in shapes if cmds.nodeType(s) == "mesh"), None)
    if mesh is None:
        raise HandlerError(
            "%s is not a polygon mesh" % _short(transform),
            hint="combine merges meshes only; group non-mesh nodes instead",
        )
    return mesh


def _resolve_inputs(cmds, params: Dict[str, Any]) -> List[str]:
    names = params.get("names")
    if not isinstance(names, list) or len(names) < 2:
        raise HandlerError(
            "names must be a list of at least two objects, got %r" % (names,),
            hint="combining one mesh is a no-op; pass every piece of the part",
        )
    longs: List[str] = []
    for name in names:
        if not isinstance(name, str) or not name:
            raise HandlerError("every entry in names must be a non-empty string")
        resolved = naming.require_object(cmds, name)
        if resolved in longs:
            raise HandlerError(
                "%s appears more than once in names" % _short(resolved),
                hint="polyUnite consumes its inputs; the same mesh cannot be "
                     "merged into itself",
            )
        longs.append(resolved)
    for transform in longs:
        _require_mesh(cmds, transform)
    return longs


def _place_pivot(cmds, node: str, mode: str) -> List[float]:
    if mode == "keep":
        return list(cmds.xform(node, query=True, worldSpace=True, rotatePivot=True))
    if mode == "origin":
        target = [0.0, 0.0, 0.0]
    else:
        bb = cmds.exactWorldBoundingBox(node)
        target = [(bb[i] + bb[i + 3]) / 2.0 for i in range(3)]
    cmds.xform(node, worldSpace=True, pivots=tuple(target))
    return target


def combine(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    longs = _resolve_inputs(cmds, params)

    pivot_mode = params.get("pivot") or "center"
    if pivot_mode not in PIVOT_MODES:
        raise HandlerError(
            "pivot must be one of %s, got %r" % (", ".join(PIVOT_MODES), pivot_mode)
        )
    freeze = params.get("freeze", True)
    if not isinstance(freeze, bool):
        raise HandlerError("freeze must be true or false, got %r" % (freeze,))

    requested = params.get("name") or _short(longs[0]) + "_combined"
    if not isinstance(requested, str) or not requested:
        raise HandlerError("name must be a non-empty string")

    # Record which shaders went in, so a caller can tell whether the collapse
    # below threw away a distinction they meant to keep.
    shaders_in = []
    for transform in longs:
        for sg in cmds.listSets(object=_require_mesh(cmds, transform), type=1) or []:
            if sg not in shaders_in:
                shaders_in.append(sg)

    session.auto_checkpoint("combine")

    target_name = naming.unique_name(cmds, requested)
    result = cmds.polyUnite(longs, ch=False, name=target_name)
    node = _long(cmds, result[0] if isinstance(result, (list, tuple)) else result)

    # Maya renames on collision. Match by SHORT NAME and correct it, rather
    # than believing the name we asked for.
    if _short(node) != target_name:
        node = _long(cmds, cmds.rename(node, target_name))

    pivot = _place_pivot(cmds, node, pivot_mode)
    if freeze:
        cmds.makeIdentity(node, apply=True, translate=True, rotate=True, scale=True)

    shape = _require_mesh(cmds, node)
    shading = meshcheck.ensure_object_shading(
        cmds, shape, shaders_in[0] if shaders_in else None
    )

    stats = {
        "tris": cmds.polyEvaluate(shape, triangle=True),
        "verts": cmds.polyEvaluate(shape, vertex=True),
        "faces": cmds.polyEvaluate(shape, face=True),
        "shells": cmds.polyEvaluate(shape, shell=True),
    }

    warnings: List[str] = []
    if len(shaders_in) > 1:
        warnings.append(
            "inputs carried %d different shading groups; the result is one "
            "object-level assignment to %s. Per-face shading on united meshes "
            "is the state #577 found unreliable - split the part if the "
            "materials must differ."
            % (len(shaders_in), shading.get("sg"))
        )

    return {
        "name": node,
        "inputs": len(longs),
        "pivot": [round(q, 6) for q in pivot],
        "pivot_mode": pivot_mode,
        "frozen": bool(freeze),
        "shading": shading,
        "warnings": warnings,
        **stats,
    }
