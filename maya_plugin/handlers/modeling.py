"""Structured modeling (§5.3): reliability layer over maya.cmds.

Tools address objects by name only, never selection. Requested names that
collide get deterministic _NNN suffixes; canonical long names come back.
Transform-writing handlers record to the ledger and surface live-user edits
as warnings (#577 req 4c).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..dispatcher import HandlerError
from . import ledger, naming

PRIMITIVE_KINDS = (
    "cube", "sphere", "cylinder", "plane", "torus", "cone",
    "octahedron", "icosahedron", "prism", "pyramid",
)
# prism/pyramid always build with this fixed side count and a flat (single
# n-gon) cap - divisions maps only to subdivisionsHeight - so a low-poly gem
# form stays faceted instead of Maya's optional fan-subdivided cap.
_PRISM_SIDES = 3
_PYRAMID_SIDES = 4

# Widths Maya produces at its default size argument, measured in mayapy on this
# Maya (see create_primitive's unit-box comment). Their reciprocals are the
# arguments that give a 1-unit-wide result. Radius-based kinds are not listed:
# for those the argument is simply half the width.
_ICOSAHEDRON_WIDTH_AT_UNIT_RADIUS = 1.7013
_PYRAMID_WIDTH_AT_UNIT_SIDE = 1.4142  # square base across the diagonal
MAX_DIVISIONS = 200
# `divisions` is a multiplier, not a face count, and the multiplier differs
# wildly per kind: cube spends it linearly per axis (6*d^2 faces) while sphere
# and torus multiply it by 20 on BOTH axes (400*d^2). Bounding `divisions`
# alone therefore bounds nothing useful - at the shared ceiling of 200 a cube
# is a harmless 240k faces but a sphere is 4000x4000 = 16 MILLION, which hangs
# or OOMs Maya. That is not a recoverable state: cmds run on Maya's main
# thread, so a wedged build also freezes the GUI event loop and the only exit
# is killing the process. Bound the RESULT instead, and tell the caller the
# highest `divisions` their chosen kind actually allows.
MAX_PRIMITIVE_FACES = 1_000_000


def projected_faces(kind: str, divisions: int) -> int:
    """Faces `kind` will have at `divisions`. Pure - unit-testable without Maya.

    Mirrors the creator lambdas below exactly; keep the two in step.
    """
    d = divisions
    if kind == "cube":
        return 6 * d * d
    if kind == "plane":
        return d * d
    if kind in ("sphere", "torus"):
        return (20 * d) * (20 * d)
    if kind in ("cylinder", "cone"):
        # side quads plus the cap fan(s): cylinder caps both ends, cone one.
        caps = 2 if kind == "cylinder" else 1
        return (20 * d) * d + caps * (20 * d)
    if kind in ("octahedron", "icosahedron"):
        # polyPlatonicSolid has no subdivision flags at all (radius/axis only)
        # - divisions has NO effect on face count for these two kinds. Fixed
        # counts measured live in mayapy (Maya's solidType: 1=icosahedron,
        # 2=octahedron in this Maya version).
        return 8 if kind == "octahedron" else 20
    if kind in ("prism", "pyramid"):
        # Measured live in mayapy with subdivisionsCaps=0 (each cap a single
        # flat n-gon face, not Maya's optional fan-subdivided one): sides =
        # ns*sh either way; prism has TWO caps, pyramid has ONE (apex is a
        # point with no cap of its own).
        ns = _PRISM_SIDES if kind == "prism" else _PYRAMID_SIDES
        caps = 2 if kind == "prism" else 1
        return ns * d + caps
    raise HandlerError("unknown primitive kind %r" % kind)


def max_divisions_for(kind: str) -> int:
    """Largest `divisions` for `kind` that stays inside MAX_PRIMITIVE_FACES."""
    allowed = 0
    for d in range(1, MAX_DIVISIONS + 1):
        if projected_faces(kind, d) > MAX_PRIMITIVE_FACES:
            break
        allowed = d
    return allowed


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _vec3(params: Dict[str, Any], key: str) -> Optional[List[float]]:
    value = params.get(key)
    if value is None:
        return None
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
        or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
    ):
        raise HandlerError(
            "%s must be a list of 3 numbers, got %r" % (key, value),
            hint="e.g. %s=[0, 1.5, 0]" % key,
        )
    return [float(v) for v in value]


def _apply_xform(cmds, name: str, translate, rotate, scale, relative: bool) -> None:
    kwargs: Dict[str, Any] = {"relative": True} if relative else {"worldSpace": True, "absolute": True}
    if translate is not None:
        cmds.xform(name, translation=translate, **kwargs)
    if rotate is not None:
        cmds.xform(name, rotation=rotate, **kwargs)
    if scale is not None:
        if relative:
            cmds.xform(name, scale=scale, relative=True)
        else:
            cmds.xform(name, scale=scale)


def _long(cmds, name: str) -> str:
    matches = cmds.ls(name, long=True) or [name]
    return matches[0]


def create_primitive(params: Dict[str, Any]) -> Dict[str, Any]:
    kind = params.get("kind")
    if kind not in PRIMITIVE_KINDS:
        raise HandlerError(
            "unknown primitive kind %r" % kind,
            hint="valid kinds: %s" % ", ".join(PRIMITIVE_KINDS),
        )
    requested = params.get("name")
    if not isinstance(requested, str) or not requested.strip():
        raise HandlerError(
            "missing required param 'name'",
            hint="pass the object name to create, e.g. name='golem_torso'",
        )
    divisions = params.get("divisions", 1)
    if not isinstance(divisions, int) or isinstance(divisions, bool) or not (
        1 <= divisions <= MAX_DIVISIONS
    ):
        raise HandlerError(
            "divisions must be an integer 1..%d" % MAX_DIVISIONS,
            hint="1 = Maya defaults; higher multiplies subdivision counts",
        )
    faces = projected_faces(kind, divisions)
    if faces > MAX_PRIMITIVE_FACES:
        raise HandlerError(
            "divisions=%d would build a %s with about %d faces, over the "
            "%d-face limit" % (divisions, kind, faces, MAX_PRIMITIVE_FACES),
            hint="the highest divisions for a %s is %d; `divisions` is a "
            "multiplier and costs far more on some kinds than others "
            "(a sphere multiplies it by 20 on both axes, a cube does not). "
            "Build it coarse and refine with maya_sculpt_ops op 'smooth'."
            % (kind, max_divisions_for(kind)),
        )
    cmds = _cmds()
    name = naming.unique_name(cmds, requested)
    long_name = _long(cmds, build_unit_primitive(cmds, kind, name, divisions))
    _apply_xform(
        cmds, long_name,
        _vec3(params, "translate"), _vec3(params, "rotate"), _vec3(params, "scale"),
        relative=False,
    )
    ledger.record(cmds, long_name)
    return {"name": long_name, "warnings": []}


def build_unit_primitive(cmds, kind: str, name: str, divisions: int = 1) -> str:
    """Create `kind` filling a 1-unit box, at the origin, and return its name.

    Split out of create_primitive so bulk builders (assemble) share ONE unit-box
    normalisation rather than re-deriving Maya's per-kind default sizes. Assumes
    `kind`, `divisions` and `name` are already validated.
    """
    # Every kind is built to fill a 1-unit box - largest dimension exactly 1 -
    # so `scale` means the same thing whichever kind you pick. Maya's own
    # defaults do not agree: measured in mayapy, cube 1.0 across,
    # sphere/cone/cylinder/octahedron 2.0, icosahedron 1.701, prism 0.866,
    # pyramid 1.414, torus 3.0. Swapping `kind` at a fixed scale therefore
    # silently resized the object, and the gem-brute run built solids at twice
    # the size it asked for (redmine #584).
    #
    # The box, not the width: a triangular prism and a square pyramid have
    # non-square footprints, so "same width" and "same size" are different
    # promises and only the box is keepable for every kind.
    #
    # EVERY size is passed EXPLICITLY, including the ones that look like Maya's
    # defaults. A size FLAG is interpreted in the scene's current linear unit; an
    # OMITTED one falls back to Maya's internal unit. Measured live with the
    # scene in metres: polyCube() builds a 0.01 m cube while polyCube(w=1,h=1,
    # d=1) builds a 1 m one - so cube and plane, the only two kinds that relied
    # on defaults, came out ONE HUNDRED TIMES smaller than every other kind at
    # the same scale, breaking the unit-box promise this comment makes. Caught
    # by evals/tool_gaps_live.py; no headless fake could see it.
    creators = {
        "cube": lambda: cmds.polyCube(
            name=name, constructionHistory=False,
            width=1.0, height=1.0, depth=1.0,
            subdivisionsWidth=divisions, subdivisionsHeight=divisions,
            subdivisionsDepth=divisions,
        ),
        "plane": lambda: cmds.polyPlane(
            name=name, constructionHistory=False, width=1.0, height=1.0,
            subdivisionsWidth=divisions, subdivisionsHeight=divisions,
        ),
        "sphere": lambda: cmds.polySphere(
            name=name, constructionHistory=False, radius=0.5,
            subdivisionsAxis=20 * divisions, subdivisionsHeight=20 * divisions,
        ),
        "cylinder": lambda: cmds.polyCylinder(
            name=name, constructionHistory=False, radius=0.5, height=1.0,
            subdivisionsAxis=20 * divisions, subdivisionsHeight=divisions,
        ),
        "cone": lambda: cmds.polyCone(
            name=name, constructionHistory=False, radius=0.5, height=1.0,
            subdivisionsAxis=20 * divisions, subdivisionsHeight=divisions,
        ),
        # Outer diameter = 2 * (radius + sectionRadius); a third and a sixth
        # keep Maya's 2:1 ring-to-tube proportion inside a unit width.
        "torus": lambda: cmds.polyTorus(
            name=name, constructionHistory=False,
            radius=1.0 / 3.0, sectionRadius=1.0 / 6.0,
            subdivisionsAxis=20 * divisions, subdivisionsHeight=20 * divisions,
        ),
        # solidType: 1=icosahedron, 2=octahedron (this Maya version) - no
        # subdivision flags exist, so divisions is accepted but has no effect.
        "octahedron": lambda: cmds.polyPlatonicSolid(
            name=name, constructionHistory=False, solidType=2, radius=0.5,
        ),
        "icosahedron": lambda: cmds.polyPlatonicSolid(
            name=name, constructionHistory=False, solidType=1,
            radius=1.0 / _ICOSAHEDRON_WIDTH_AT_UNIT_RADIUS,
        ),
        # A triangular footprint is not square: at sideLength 1 the prism spans
        # 1.0 across a corner and 0.866 across the flats, so it already fills
        # the unit box and only its height needs normalising.
        "prism": lambda: cmds.polyPrism(
            name=name, constructionHistory=False,
            sideLength=1.0, length=1.0,
            numberOfSides=_PRISM_SIDES, subdivisionsHeight=divisions,
            subdivisionsCaps=0,
        ),
        # A pyramid's height follows its side length, so a unit-wide pyramid is
        # half a unit tall. That is the shape, not a normalisation miss.
        "pyramid": lambda: cmds.polyPyramid(
            name=name, constructionHistory=False,
            sideLength=1.0 / _PYRAMID_WIDTH_AT_UNIT_SIDE,
            numberOfSides=_PYRAMID_SIDES, subdivisionsHeight=divisions,
            subdivisionsCaps=0,
        ),
    }
    return creators[kind]()[0]


def duplicate(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    source = naming.require_object(cmds, str(params.get("name") or ""))
    requested = params.get("new_name")
    if not isinstance(requested, str) or not requested.strip():
        raise HandlerError(
            "missing required param 'new_name'",
            hint="pass the name for the copy, e.g. new_name='golem_arm_L'",
        )
    warnings = [w for w in [ledger.check(cmds, source)] if w]
    new_name = naming.unique_name(cmds, requested)
    copy = cmds.duplicate(source, name=new_name, returnRootsOnly=True)[0]
    long_name = _long(cmds, copy)
    _apply_xform(
        cmds, long_name,
        _vec3(params, "translate"), _vec3(params, "rotate"), _vec3(params, "scale"),
        relative=True,
    )
    ledger.record(cmds, long_name)
    return {"name": long_name, "warnings": warnings}


def transform(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    names = params.get("names")
    if not isinstance(names, list) or not names:
        raise HandlerError(
            "names must be a non-empty list of object names",
            hint='e.g. names=["|golem|torso"]',
        )
    translate = _vec3(params, "translate")
    rotate = _vec3(params, "rotate")
    scale = _vec3(params, "scale")
    pivot = _vec3(params, "pivot")
    if translate is None and rotate is None and scale is None and pivot is None:
        raise HandlerError(
            "nothing to do",
            hint="pass at least one of translate, rotate, scale, pivot",
        )
    relative = params.get("relative", True) is not False
    resolved = [naming.require_object(cmds, str(n)) for n in names]

    warnings: List[str] = []
    objects: List[Dict[str, Any]] = []
    for name in resolved:
        moved = ledger.check(cmds, name)
        if moved:
            warnings.append(moved)
        # Pivot FIRST: a relative rotation in the same call must turn about the
        # new pivot, not the old one. `pivots` moves the pivot without moving
        # the geometry, which is the whole point - a rig is pivots.
        if pivot is not None:
            cmds.xform(name, worldSpace=True, pivots=tuple(pivot))
        _apply_xform(cmds, name, translate, rotate, scale, relative)
        ledger.record(cmds, name)
        objects.append(
            {
                "name": name,
                "translate": cmds.xform(name, query=True, worldSpace=True, translation=True),
                "rotate": cmds.xform(name, query=True, worldSpace=True, rotation=True),
                "scale": cmds.xform(name, query=True, worldSpace=True, scale=True),
                "pivot": cmds.xform(name, query=True, worldSpace=True, rotatePivot=True),
            }
        )
    return {"objects": objects, "warnings": warnings}


def group(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    names = params.get("names")
    if not isinstance(names, list) or not names:
        raise HandlerError(
            "names must be a non-empty list", hint='e.g. names=["|a", "|b"]'
        )
    resolved = [naming.require_object(cmds, str(n)) for n in names]
    requested = params.get("group_name")
    if not isinstance(requested, str) or not requested.strip():
        raise HandlerError(
            "missing required param 'group_name'", hint="e.g. group_name='golem'"
        )
    grp = cmds.group(*resolved, name=naming.unique_name(cmds, requested))
    group_long = _long(cmds, grp)

    # Re-key ledger entries: each child's long name has changed due to reparenting.
    # Query Maya's actual post-group paths rather than assuming a naming scheme
    # (Maya may auto-rename a child on collision).
    actual_children = (
        cmds.listRelatives(group_long, children=True, fullPath=True) or []
    )
    for old_long in resolved:
        ledger.forget(old_long)
        old_short = old_long.split("|")[-1]
        new_long = next(
            (c for c in actual_children if c.split("|")[-1] == old_short), None
        )
        if new_long is not None:
            ledger.record(cmds, new_long)

    return {"name": group_long, "warnings": []}


def parent(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    child = naming.require_object(cmds, str(params.get("child") or ""))
    target = naming.require_object(cmds, str(params.get("parent") or ""))
    moved = cmds.parent(child, target)
    long_name = _long(cmds, moved[0])
    ledger.forget(child)  # its long name just changed
    ledger.record(cmds, long_name)
    return {"name": long_name, "warnings": []}


def rename(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    old = naming.require_object(cmds, str(params.get("name") or ""))
    requested = params.get("new_name")
    if not isinstance(requested, str) or not requested.strip():
        raise HandlerError(
            "missing required param 'new_name'", hint="pass the new object name"
        )
    new = cmds.rename(old, naming.unique_name(cmds, requested))
    ledger.forget(old)
    long_name = _long(cmds, new)
    ledger.record(cmds, long_name)
    return {"name": long_name, "warnings": []}


def delete_objects(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    names = params.get("names")
    if not isinstance(names, list) or not names:
        raise HandlerError(
            "names must be a non-empty list", hint='e.g. names=["|scrap"]'
        )
    missing = [str(n) for n in names if not cmds.objExists(str(n))]
    if missing:
        raise HandlerError(
            "objects not found: %s (nothing was deleted)" % ", ".join(missing),
            hint="call maya_get_scene_graph to list objects; the delete is "
            "all-or-nothing",
        )
    resolved = [naming.require_object(cmds, str(n)) for n in names]
    cmds.delete(*resolved)
    for name in resolved:
        ledger.forget(name)
    return {"deleted": resolved, "warnings": []}


BOOLEAN_OPS = {"union": 1, "difference": 2, "intersection": 3}


def _do_boolean(cmds, a_long: str, b_long: str, op: str, new_name: str) -> Dict[str, Any]:
    """Shared boolean core: polyCBoolOp + the golem-run cleanup discipline.

    Per-face shader assignment on boolean output silently no-ops and corrupts
    shading groups (redmine #577 req 1), so: delete history immediately, then
    collapse shading to one object-level SG (input A's material wins).
    """
    from . import meshcheck  # noqa: PLC0415 - keep module import cheap headless

    _, a_shape = naming.require_mesh(cmds, a_long)
    fallback_sg = meshcheck.first_sg(cmds, a_shape)

    result = cmds.polyCBoolOp(a_long, b_long, op=BOOLEAN_OPS[op], name=new_name)
    out = cmds.rename(result[0], new_name)
    out_long = _long(cmds, out)
    cmds.delete(out_long, constructionHistory=True)

    warnings: List[str] = []
    _, out_shape = naming.require_mesh(cmds, out_long)
    # polyCBoolOp leaves groupId nodes wired into the shape's (comp)InstObjGroups
    # to carry each operand's original per-face material group across the
    # boolean; constructionHistory=True does not remove them because they are
    # still "in use" by that group tracking. They are exactly the per-face
    # machinery that silently corrupts shading on this Maya version (module
    # docstring), and object-level collapse below makes them dead weight
    # regardless, so clear them before collapsing shading.
    stale_group_ids = set(cmds.listConnections(out_shape, type="groupId") or [])
    if stale_group_ids:
        cmds.delete(list(stale_group_ids))
    shading = meshcheck.ensure_object_shading(cmds, out_shape, fallback_sg)
    if shading["repaired"]:
        warnings.append(
            "shading collapsed to object-level %s (per-face assignment is "
            "unreliable on boolean output)" % shading["sg"]
        )
    stats = meshcheck.mesh_stats(out_long)
    if not stats["watertight"]:
        warnings.append(
            "result is not watertight (%d boundary, %d non-manifold edges); "
            "run maya_mesh_cleanup" % (stats["boundary_edges"], stats["nonmanifold_edges"])
        )
    ledger.forget(a_long)
    ledger.forget(b_long)
    ledger.record(cmds, out_long)
    return {
        "name": out_long,
        "tris": stats["tris"],
        "watertight": stats["watertight"],
        "warnings": warnings,
    }


def boolean_op(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    op = params.get("op")
    if op not in BOOLEAN_OPS:
        raise HandlerError(
            "unknown boolean op %r" % op,
            hint="valid ops: union, difference, intersection",
        )
    a_long = naming.require_mesh(cmds, str(params.get("a") or ""))[0]
    b_long = naming.require_mesh(cmds, str(params.get("b") or ""))[0]
    if a_long == b_long:
        raise HandlerError(
            "a and b are the same object", hint="pass two different meshes"
        )
    requested = params.get("new_name")
    if not isinstance(requested, str) or not requested.strip():
        raise HandlerError(
            "missing required param 'new_name'", hint="name for the result mesh"
        )
    from . import session  # noqa: PLC0415

    session.auto_checkpoint("boolean")
    return _do_boolean(cmds, a_long, b_long, op, naming.unique_name(cmds, requested))


MIN_TARGET_POLYCOUNT = 100
MAX_TARGET_POLYCOUNT = 200000


def remesh_retopo(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    mesh_long, _ = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    target = params.get("target_polycount")
    if (
        not isinstance(target, int) or isinstance(target, bool)
        or not (MIN_TARGET_POLYCOUNT <= target <= MAX_TARGET_POLYCOUNT)
    ):
        raise HandlerError(
            "target_polycount must be an integer %d..%d"
            % (MIN_TARGET_POLYCOUNT, MAX_TARGET_POLYCOUNT),
            hint="got %r" % (target,),
        )
    # Validate everything before spending the auto-checkpoint (same discipline
    # as sculpt_ops: an invalid call must never burn one).
    keep_original = params.get("keep_original", True) is not False

    from . import session  # noqa: PLC0415

    session.auto_checkpoint("remesh")

    original: Optional[str] = None
    if keep_original:
        orig_name = naming.unique_name(cmds, mesh_long.split("|")[-1] + "_orig")
        dup = cmds.duplicate(mesh_long, name=orig_name, returnRootsOnly=True)[0]
        dup_long = _long(cmds, dup)
        cmds.setAttr(dup_long + ".visibility", False)
        original = dup_long

    # Feature-detect in order, degrading with a reported fallback rather than
    # failing outright (§6 compatibility) - Maya versions vary in which of
    # these commands exist / behave on a given mesh.
    warnings: List[str] = []
    method: Optional[str] = None
    if hasattr(cmds, "polyRetopo"):
        try:
            cmds.polyRetopo(mesh_long, targetFaceCount=target)
            method = "polyRetopo"
        except Exception:
            warnings.append("polyRetopo raised at runtime; fell back to polyRemesh")
    else:
        warnings.append("polyRetopo is not available in this Maya; fell back to polyRemesh")

    if method is None:
        if hasattr(cmds, "polyRemesh"):
            try:
                cmds.polyRemesh(mesh_long)
                method = "polyRemesh"
            except Exception:
                warnings.append("polyRemesh raised at runtime; fell back to polyReduce")
        else:
            warnings.append("polyRemesh is not available in this Maya; fell back to polyReduce")

    if method is None:
        current_faces = cmds.polyEvaluate(mesh_long, face=True)
        # polyReduce's -percentage is the amount of reduction to *perform*
        # (100 = maximal reduction, 0 = no-op), not the fraction of faces to
        # keep. target/current is the keep-fraction, so the reduction amount
        # is its complement.
        percentage = 0.0
        if not isinstance(current_faces, int):
            # A query failure, not "nothing to reduce" - keep the two cases
            # from ever sharing one warning message (the old message claimed
            # target_polycount >= current face count here too, which is a lie
            # when the count was never obtained).
            warnings.append(
                "polyEvaluate(face=True) on %s returned %r instead of an int "
                "face count; skipped polyReduce" % (mesh_long, current_faces)
            )
        elif current_faces > target > 0:
            percentage = max(1.0, min(100.0, (1.0 - target / float(current_faces)) * 100.0))
        if percentage > 0.0:
            cmds.polyReduce(mesh_long, percentage=percentage, constructionHistory=False)
        elif isinstance(current_faces, int):
            warnings.append(
                "target_polycount %d >= current face count %d; nothing to reduce"
                % (target, current_faces)
            )
        method = "polyReduce"

    cmds.delete(mesh_long, constructionHistory=True)
    tris = cmds.polyEvaluate(mesh_long, triangle=True)
    return {
        "name": mesh_long, "tris": tris, "method": method, "warnings": warnings,
        "original": original,
    }


def mesh_cleanup(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    from . import meshcheck  # noqa: PLC0415 - keep module import cheap headless

    mesh_long, _ = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    threshold = params.get("merge_verts_threshold", 0.001)
    if (
        not isinstance(threshold, (int, float)) or isinstance(threshold, bool)
        or not (0 < threshold <= 1.0)
    ):
        raise HandlerError(
            "merge_verts_threshold must be a number in (0, 1.0]",
            hint="got %r; default is 0.001" % (threshold,),
        )

    before = meshcheck.mesh_stats(mesh_long)
    cmds.polyMergeVertex(mesh_long, distance=threshold)
    if params.get("conform_normals", True):
        cmds.polyNormal(mesh_long, normalMode=2, constructionHistory=False)
    if params.get("freeze_transforms", True):
        cmds.makeIdentity(mesh_long, apply=True, translate=True, rotate=True, scale=True)
        ledger.record(cmds, mesh_long)  # frozen transform is a tool write
    if params.get("delete_history", True):
        cmds.delete(mesh_long, constructionHistory=True)
    after = meshcheck.mesh_stats(mesh_long)
    return {"name": mesh_long, "before": before, "after": after, "warnings": []}
