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

from typing import Any, Dict, List, Optional

from ..dispatcher import HandlerError, require_known_keys
from . import meshcheck, naming, session

PIVOT_MODES = ("center", "origin", "keep")

# The note `keep` earns on a UNITED result, as a named constant so a bulk
# builder can recognise its own copies EXACTLY rather than by substring. One
# line per result is right for combine (one call, one result); assemble unites
# a chunk at a time - 2,034 of them in the delivery this repo was written for -
# so it drops these and states the count once instead.
KEEP_PIVOT_NOTE = (
    "pivot='keep' on a combined result keeps the pivot polyUnite gives it, "
    "which is the world ORIGIN (measured) - the same place pivot='origin' "
    "writes. Nothing of the inputs' pivots survives the unite; use 'center' "
    "for the bounding-box centre, or place it yourself afterwards."
)


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


def _place_pivot(cmds, node: str, mode: str,
                 warnings: Optional[List[str]] = None) -> List[float]:
    if mode == "keep":
        # Not refused - the value is legal, and assemble's single-part branch
        # keeps a pivot a primitive genuinely built. But on a UNITED result
        # there is no prior pivot to keep: MEASURED on a live probe
        # (2026-09-03, pid 33088) a fresh polyUnite transform answers
        # rotatePivot, scalePivot AND translate as (0, 0, 0) whatever `ch`
        # says, so `keep` keeps the ORIGIN and is `origin` under another
        # name. A caller asking for keep is asking to preserve something,
        # and nothing said there was nothing to preserve.
        if warnings is not None:
            warnings.append(KEEP_PIVOT_NOTE)
        return list(cmds.xform(node, query=True, worldSpace=True, rotatePivot=True))
    if mode == "origin":
        target = [0.0, 0.0, 0.0]
    else:
        bb = cmds.exactWorldBoundingBox(node)
        target = [(bb[i] + bb[i + 3]) / 2.0 for i in range(3)]
    cmds.xform(node, worldSpace=True, pivots=tuple(target))
    return target


# Every top-level key combine reads. Anything else is refused rather than
# ignored (#767): an unread key does not fail, it succeeds and does something
# else.
COMBINE_KEYS = ("names", "name", "pivot", "freeze")
# `new_name` is this repo's own word for the output name everywhere a command
# consumes its inputs and hands back one node - boolean_op, etch_text, rename
# and duplicate all spell it that way - so a caller arriving from any of them
# reaches for it here, where the merged object is named by plain `name`.
COMBINE_SYNONYMS = {"new_name": "name"}


def combine(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, COMBINE_KEYS, "combine", COMBINE_SYNONYMS)
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

    session.auto_checkpoint("combine")
    return unite(cmds, longs, requested, pivot_mode, freeze)


def unite(
    cmds, longs: List[str], requested: str, pivot_mode: str = "center",
    freeze: bool = True,
) -> Dict[str, Any]:
    """polyUnite + pivot + freeze + shading collapse, and MEASURE the result.

    Split out of combine() with no checkpoint of its own, so a bulk builder
    (assemble) can take one checkpoint for a whole run instead of one per
    object - two thousand checkpoints would evict the ring twenty times over
    and turn the safety net into a delay. Inputs are assumed resolved.
    """
    # Record which shaders went in, so a caller can tell whether the collapse
    # below threw away a distinction they meant to keep.
    shaders_in = []
    for transform in longs:
        for sg in cmds.listSets(object=_require_mesh(cmds, transform), type=1) or []:
            if sg not in shaders_in:
                shaders_in.append(sg)

    # Where the inputs sat, read BEFORE the unite consumes them (#867).
    # polyUnite lands its result at the world root whatever its inputs'
    # parents were: twelve armour plates under |kethran came back as |armor
    # at the root, outside the group that moves the animal, with a plain
    # success - and the deliverable would have shipped that way. names[0]'s
    # parent is carried, the way boolean_op carries a's.
    parents = [
        (cmds.listRelatives(t, parent=True, fullPath=True) or [None])[0]
        for t in longs
    ]

    # Ask for the name the caller WANTS, not a pre-uniquified one. polyUnite
    # consumes its inputs, so an input's own name is free by the time the
    # result needs it - but only after the unite. Uniquifying first, while
    # Maya still held the input, turned `combine(body, arm, name="body")`
    # into body_001 (#803 - the #640 defect boolean_op fixed with
    # _claim_name). MEASURED (evals/combine_pivot_probe_803.py): Maya
    # answers body1 for that request, and body is free to rename to
    # afterwards.
    # History ON, deleted two steps below - the order boolean_op measured
    # (#640) and this gate re-measured for polyUnite (#867, 2026-09-06):
    # with ch=False Maya reaps the consumed inputs AND a parent left with
    # no other child in the same stroke, so a group holding only the inputs
    # was gone by the time the result could be put under it. With history
    # on the inputs stay as empty transforms until the delete, the parent
    # still exists, the result goes under it, and the delete then reaps the
    # inputs while the parent survives because it holds the result.
    result = cmds.polyUnite(longs, ch=True, name=requested)
    node = _long(cmds, result[0] if isinstance(result, (list, tuple)) else result)

    warnings: List[str] = []
    # Before the history delete (see above), and before the pivot and the
    # freeze: cmds.parent preserves world position by handing the node the
    # inverse of its new parent's transform, and the freeze below bakes that
    # away - the same order boolean_op uses.
    node = _carry_parent(cmds, node, parents, warnings)
    cmds.delete(node, constructionHistory=True)

    # Maya renames on collision. Match by SHORT NAME and claim the name now
    # that the inputs are gone - the history delete is the first moment an
    # input's own name is free (#803); only a name some UNRELATED object
    # holds forces the suffix, and then the caller is told.
    if _short(node) != requested:
        node = _long(cmds, cmds.rename(node, naming.unique_name(cmds, requested)))
        if _short(node) != requested:
            warnings.append(
                "name %r is held by another object; the result is %s"
                % (requested, _short(node)))

    _place_pivot(cmds, node, pivot_mode, warnings)
    if freeze:
        cmds.makeIdentity(node, apply=True, translate=True, rotate=True, scale=True)
    # Report where Maya HAS the pivot, never the value that was written.
    # MEASURED (#803): makeIdentity leaves the pivot where it was placed -
    # the belief that a freeze resets it to the origin was a plan-doc
    # sentence, never a reading - but the query is the honest report
    # whatever a future Maya does with it, and it is what assemble does.
    pivot = list(cmds.xform(node, query=True, worldSpace=True, rotatePivot=True))

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
        # Read back, never assumed: where Maya HAS the result (#867).
        "parent": (cmds.listRelatives(node, parent=True, fullPath=True) or [None])[0],
        "pivot": [round(q, 6) for q in pivot],
        "pivot_mode": pivot_mode,
        "frozen": bool(freeze),
        "shading": shading,
        "warnings": warnings,
        **stats,
    }


def _carry_parent(cmds, node: str, parents: List[Optional[str]],
                  warnings: List[str]) -> str:
    """Put the united result under names[0]'s parent, and say when the
    inputs did not agree on one (#867).

    None in `parents` is the root. The first entry is carried; every other
    distinct parent is named in a warning, because a caller who combined
    pieces from two groups gets ONE answer and deserves to know which.
    A parent that no longer exists (a group the unite emptied and something
    else swept) is named too, and the result stays at the root rather
    than failing a unite that already happened.
    """
    carried = parents[0]
    others: List[Optional[str]] = []
    for other in parents[1:]:
        if other != carried and other not in others:
            others.append(other)
    if others:
        warnings.append(
            "inputs sat under %d different parents (%s); the result is under "
            "%s, names[0]'s - maya_parent it elsewhere if another was meant"
            % (len(others) + 1,
               ", ".join(p or "the root" for p in [carried] + others),
               carried or "the root"))
    if carried is None:
        return node
    if not cmds.objExists(carried):
        warnings.append(
            "names[0]'s parent %s no longer exists; the result is at the "
            "root" % carried)
        return node
    moved = cmds.parent(node, carried) or [node]
    return _long(cmds, moved[0])
