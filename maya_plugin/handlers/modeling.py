"""Structured modeling (§5.3): reliability layer over maya.cmds.

Tools address objects by name only, never selection. Requested names that
collide get deterministic _NNN suffixes; canonical long names come back.
Transform-writing handlers record to the ledger and surface live-user edits
as warnings (#577 req 4c).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError, require_known_keys
from . import ledger, naming, plugwrite, uvmath

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

# Each kind's independently subdividable axes, in the order `subdivisions`
# takes them, with the smallest count Maya HONOURS on each.
#
# The minimum is not cosmetic and it is not 1. Measured on this Maya
# (evals/divisions_probe_669.py, claims 3 and 5): given a `subdivisionsAxis`
# below 3, polySphere/polyCylinder/polyCone/polyTorus do not clamp to 3 and do
# not raise - they silently substitute their own DEFAULT of 20. A caller who
# asks for a 2-sided tube gets a 20-sided one and is told nothing. The same is
# true of `subdivisionsHeight` on sphere and torus, whose "along" axis is a
# closed loop and needs three segments to exist at all. Cylinder and cone
# stack their rows between two caps, so one row is a real answer there.
#
# Torus's second axis is around the TUBE, not along a length - the names are
# what the refusals print, so they say what the number actually does.
SUBDIVISION_AXES: Dict[str, Tuple[Tuple[str, int], ...]] = {
    "cube": (("width", 1), ("height", 1), ("depth", 1)),
    # polyPlane lies in XZ: its "height" flag subdivides Z, not Y.
    "plane": (("width", 1), ("depth", 1)),
    "sphere": (("around", 3), ("along", 3)),
    "cylinder": (("around", 3), ("along", 1)),
    "cone": (("around", 3), ("along", 1)),
    "torus": (("ring", 3), ("tube", 3)),
    "prism": (("along", 1),),
    "pyramid": (("along", 1),),
    # polyPlatonicSolid takes radius and axis only - there is no subdivision
    # flag to spend, so these two kinds have no axes at all.
    "octahedron": (),
    "icosahedron": (),
}


def axes_for_divisions(kind: str, divisions: int) -> Tuple[int, ...]:
    """The per-axis counts the `divisions` multiplier means for `kind`.

    The single place the multiplier is defined. Everything else - the face
    projection, the builder, the reported result - reads per-axis counts, so
    `divisions` and `subdivisions` cannot drift apart.
    """
    d = divisions
    if kind in ("cube",):
        return (d, d, d)
    if kind in ("plane",):
        return (d, d)
    if kind in ("sphere", "torus"):
        return (20 * d, 20 * d)
    if kind in ("cylinder", "cone"):
        # The #669 coupling, stated in one line: 20 around per 1 along.
        return (20 * d, d)
    if kind in ("prism", "pyramid"):
        return (d,)
    if kind in ("octahedron", "icosahedron"):
        return ()
    raise HandlerError("unknown primitive kind %r" % kind)


def faces_for(kind: str, axes: Tuple[int, ...]) -> int:
    """Faces `kind` will have at these per-axis counts. Pure - no Maya needed.

    MEASURED against a real Maya for every kind, at several counts each
    (evals/divisions_probe_669.py claims 1 and 4, and the mayapy suite's
    TestPrimitiveFaceCounts, which builds each one and counts).

    The cylinder and cone rows are a CORRECTION: the old arithmetic charged
    `caps * subdivisionsAxis` for the end caps, as if Maya fanned them into
    triangles. It does not - `polyCylinder` closes each end with a single
    n-gon, so a default cylinder is 22 faces where this function used to
    predict 60. That over-count fed the shared face budget `assemble` spends
    across all its parts, so it refused builds that would have been fine.
    """
    if kind == "cube":
        w, h, d = axes
        return 2 * (w * h + h * d + w * d)
    if kind == "plane":
        return axes[0] * axes[1]
    if kind in ("sphere", "torus"):
        return axes[0] * axes[1]
    if kind in ("cylinder", "cone"):
        # side quads (cone: triangles into the apex) plus ONE n-gon per cap.
        caps = 2 if kind == "cylinder" else 1
        return axes[0] * axes[1] + caps
    if kind in ("octahedron", "icosahedron"):
        # Fixed counts measured live in mayapy (Maya's solidType: 1 =
        # icosahedron, 2 = octahedron in this Maya version).
        return 8 if kind == "octahedron" else 20
    if kind in ("prism", "pyramid"):
        # Measured with subdivisionsCaps=0 (each cap a single flat n-gon, not
        # Maya's optional fan-subdivided one): prism has TWO caps, pyramid has
        # ONE (the apex is a point with no cap of its own).
        ns = _PRISM_SIDES if kind == "prism" else _PYRAMID_SIDES
        caps = 2 if kind == "prism" else 1
        return ns * axes[0] + caps
    raise HandlerError("unknown primitive kind %r" % kind)


def projected_faces(kind: str, divisions: int) -> int:
    """Faces `kind` will have at `divisions`. Pure - unit-testable without Maya."""
    return faces_for(kind, axes_for_divisions(kind, divisions))


def max_divisions_for(kind: str) -> int:
    """Largest `divisions` for `kind` that stays inside MAX_PRIMITIVE_FACES."""
    allowed = 0
    for d in range(1, MAX_DIVISIONS + 1):
        if projected_faces(kind, d) > MAX_PRIMITIVE_FACES:
            break
        allowed = d
    return allowed


def _axis_list(kind: str) -> str:
    return ", ".join(name for name, _ in SUBDIVISION_AXES[kind])


def resolve_subdivisions(
    kind: str, params: Dict[str, Any], where: str = ""
) -> Tuple[int, ...]:
    """The per-axis subdivision counts this call asks for, validated.

    Two ways in, and they are different currencies, so passing both is refused
    rather than silently ranked:

    * `divisions` - the historical MULTIPLIER, unchanged. Convenient, but on
      cylinder and cone it buys 20 around per 1 along, so a long thin limb
      cannot resolve its LENGTH without an absurd circumference (#669: 16 rows
      along a cylinder costs 5122 faces this way against 194 with a
      circumference a limb actually needs - 26x).
    * `subdivisions` - LITERAL counts, one per axis of this kind, in
      SUBDIVISION_AXES order.

    Every refusal names the axes of the kind in hand, because the axis count
    and the minimums differ per kind and a bare "invalid" would send the
    caller guessing.
    """
    prefix = (where + " ") if where else ""
    axes_spec = SUBDIVISION_AXES[kind]
    subdivisions = params.get("subdivisions")
    divisions = params.get("divisions")
    if subdivisions is not None and divisions is not None:
        raise HandlerError(
            "%spass either divisions or subdivisions, not both" % prefix,
            hint="they are different currencies: `divisions` is a multiplier "
            "(a cylinder spends it 20 around per 1 along), `subdivisions` is "
            "the literal count per axis. Guessing which one you meant is "
            "exactly the silent substitution this refuses.",
        )

    if subdivisions is None:
        if divisions is None:
            divisions = 1
        if not isinstance(divisions, int) or isinstance(divisions, bool) or not (
            1 <= divisions <= MAX_DIVISIONS
        ):
            raise HandlerError(
                "%sdivisions must be an integer 1..%d" % (prefix, MAX_DIVISIONS),
                hint="1 = Maya defaults; higher multiplies subdivision counts. "
                "For per-axis control pass `subdivisions` instead"
                + (": [%s]" % _axis_list(kind) if axes_spec else ""),
            )
        return axes_for_divisions(kind, divisions)

    if not axes_spec:
        raise HandlerError(
            "%s%s has no subdivision axes, so `subdivisions` means nothing "
            "for it" % (prefix, kind),
            hint="polyPlatonicSolid takes radius and axis only - an "
            "octahedron is always 8 faces and an icosahedron always 20. "
            "Refine one with maya_sculpt_ops op 'smooth' instead.",
        )
    if (
        not isinstance(subdivisions, (list, tuple))
        or len(subdivisions) != len(axes_spec)
        or not all(isinstance(v, int) and not isinstance(v, bool)
                   for v in subdivisions)
    ):
        raise HandlerError(
            "%ssubdivisions for a %s must be %d integers, got %r"
            % (prefix, kind, len(axes_spec), subdivisions),
            hint="the axes of a %s are [%s]" % (kind, _axis_list(kind)),
        )
    for value, (axis_name, minimum) in zip(subdivisions, axes_spec):
        if value < minimum:
            if minimum > 1:
                hint = (
                    "MEASURED on this Maya: a subdivision count below the "
                    "minimum is neither clamped nor refused - Maya silently "
                    "substitutes its own DEFAULT of 20. Asking for %d would "
                    "build 20 and say nothing, so this refuses instead."
                    % value
                )
            else:
                hint = ("a %s needs at least %d on its %s axis"
                        % (kind, minimum, axis_name))
            raise HandlerError(
                "%ssubdivisions %s=%d is below the %d Maya honours on a %s"
                % (prefix, axis_name, value, minimum, kind),
                hint=hint,
            )
    return tuple(int(v) for v in subdivisions)


def check_face_budget(kind: str, axes: Tuple[int, ...], where: str = "") -> int:
    """Refuse a build that would hang Maya, and say what to turn down."""
    faces = faces_for(kind, axes)
    if faces > MAX_PRIMITIVE_FACES:
        prefix = (where + " ") if where else ""
        raise HandlerError(
            "%sthat would build a %s with about %d faces, over the %d-face "
            "limit" % (prefix, kind, faces, MAX_PRIMITIVE_FACES),
            hint="the highest `divisions` for a %s is %d, or pass "
            "`subdivisions` and spend the faces where the shape needs them "
            "([%s] for a %s). `divisions` is a multiplier and costs far more "
            "on some kinds than others - a sphere multiplies it by 20 on BOTH "
            "axes, a cube does not. Build it coarse and refine with "
            "maya_sculpt_ops op 'smooth'."
            % (kind, max_divisions_for(kind), _axis_list(kind) or "none", kind),
        )
    return faces


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


# Every top-level key create_primitive reads. Anything else is refused rather
# than ignored (#767): an unread key does not fail, it succeeds and does
# something else.
CREATE_PRIMITIVE_KEYS = (
    "kind", "name", "translate", "rotate", "scale", "divisions",
    "subdivisions",
)
# `type` is the generic word for a shape category where this repo says `kind`.
# `position` and `rotation` are the nouns the neighbouring tools use -
# set_camera takes `position`, pose_skeleton takes `rotations` - while the
# transform params here are spelled as verbs, and `pos` reaches no key for
# the prefix fallback to suggest. `size` is what a caller means when scaling
# a unit-box primitive, and `siz` never reaches `scale` either.
CREATE_PRIMITIVE_SYNONYMS = {
    "type": "kind", "position": "translate", "rotation": "rotate",
    "size": "scale",
}


def create_primitive(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, CREATE_PRIMITIVE_KEYS, "create_primitive",
                       CREATE_PRIMITIVE_SYNONYMS)
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
    axes = resolve_subdivisions(kind, params)
    faces = check_face_budget(kind, axes)
    cmds = _cmds()
    name = naming.unique_name(cmds, requested)
    long_name = _long(cmds, build_unit_primitive(cmds, kind, name, axes=axes))
    _apply_xform(
        cmds, long_name,
        _vec3(params, "translate"), _vec3(params, "rotate"), _vec3(params, "scale"),
        relative=False,
    )
    ledger.record(cmds, long_name)
    # The resolved counts come back because `divisions` is a multiplier whose
    # per-kind meaning is invisible from the call site: a caller who asked for
    # 4 has no way to know it bought 80 around and 4 along until it is told.
    return {
        "name": long_name,
        "subdivisions": list(axes),
        "faces": faces,
        "warnings": [],
    }


def build_unit_primitive(
    cmds, kind: str, name: str, divisions: int = 1,
    axes: Optional[Tuple[int, ...]] = None,
) -> str:
    """Create `kind` filling a 1-unit box, at the origin, and return its name.

    Split out of create_primitive so bulk builders (assemble) share ONE unit-box
    normalisation rather than re-deriving Maya's per-kind default sizes. Assumes
    `kind`, `name` and the subdivision counts are already validated.

    `axes` is the per-axis subdivision counts in SUBDIVISION_AXES order; the
    `divisions` multiplier is kept for callers that never needed per-axis
    control, and resolves through the same one place.
    """
    if axes is None:
        axes = axes_for_divisions(kind, divisions)
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
            subdivisionsWidth=axes[0], subdivisionsHeight=axes[1],
            subdivisionsDepth=axes[2],
        ),
        "plane": lambda: cmds.polyPlane(
            name=name, constructionHistory=False, width=1.0, height=1.0,
            subdivisionsWidth=axes[0], subdivisionsHeight=axes[1],
        ),
        "sphere": lambda: cmds.polySphere(
            name=name, constructionHistory=False, radius=0.5,
            subdivisionsAxis=axes[0], subdivisionsHeight=axes[1],
        ),
        "cylinder": lambda: cmds.polyCylinder(
            name=name, constructionHistory=False, radius=0.5, height=1.0,
            subdivisionsAxis=axes[0], subdivisionsHeight=axes[1],
        ),
        "cone": lambda: cmds.polyCone(
            name=name, constructionHistory=False, radius=0.5, height=1.0,
            subdivisionsAxis=axes[0], subdivisionsHeight=axes[1],
        ),
        # Outer diameter = 2 * (radius + sectionRadius); a third and a sixth
        # keep Maya's 2:1 ring-to-tube proportion inside a unit width.
        "torus": lambda: cmds.polyTorus(
            name=name, constructionHistory=False,
            radius=1.0 / 3.0, sectionRadius=1.0 / 6.0,
            subdivisionsAxis=axes[0], subdivisionsHeight=axes[1],
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
            numberOfSides=_PRISM_SIDES, subdivisionsHeight=axes[0],
            subdivisionsCaps=0,
        ),
        # A pyramid's height follows its side length, so a unit-wide pyramid is
        # half a unit tall. That is the shape, not a normalisation miss.
        "pyramid": lambda: cmds.polyPyramid(
            name=name, constructionHistory=False,
            sideLength=1.0 / _PYRAMID_WIDTH_AT_UNIT_SIDE,
            numberOfSides=_PYRAMID_SIDES, subdivisionsHeight=axes[0],
            subdivisionsCaps=0,
        ),
    }
    return creators[kind]()[0]


# Every top-level key duplicate reads. Anything else is refused rather
# than ignored (#767): an unread key does not fail, it succeeds and does
# something else.
DUPLICATE_KEYS = ("name", "new_name", "translate", "rotate", "scale")
# `source` is the generic word for the object being copied, and this handler
# even calls it that internally, but the key that names it is plainly `name`;
# `sou` matches nothing, so the prefix fallback stays silent. `position` and
# `rotation` are the nouns the camera and rigging tools use for the offsets
# this command spells as verbs.
DUPLICATE_SYNONYMS = {
    "source": "name", "position": "translate", "rotation": "rotate",
}


def duplicate(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, DUPLICATE_KEYS, "duplicate",
                       DUPLICATE_SYNONYMS)
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


# Every top-level key transform reads. Anything else is refused rather
# than ignored (#767): an unread key does not fail, it succeeds and does
# something else.
TRANSFORM_KEYS = ("names", "translate", "rotate", "scale", "relative", "pivot")
# `position` and `rotation` are the nouns the neighbouring tools reach for -
# set_camera takes `position`, pose_skeleton takes `rotations` - where this
# command names the same two things as verbs. `position` is the dangerous
# one: `pos` matches no key, so without this entry the refusal could not say
# what was meant.
TRANSFORM_SYNONYMS = {"position": "translate", "rotation": "rotate"}


def transform(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, TRANSFORM_KEYS, "transform",
                       TRANSFORM_SYNONYMS)
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
    # delete_objects promises all-or-nothing on exactly this shape of input
    # and says so in its own refusal; transform resolved every name up front
    # and then wrote object by object, so a plug the rig owns on the third
    # name left the first two moved and ledger-recorded (#802). Every plug
    # of every object is asked about before the first one is written.
    #
    # The COMPOUNDS are asked about, not the axes: `cmds.xform` does not
    # raise on a channel it cannot write, it writes the children it can and
    # silently skips the rest (measured, #802), so a locked translateY on
    # one object used to give that object a two-thirds move and the caller a
    # success report.
    channels = [c for c, v in (("translate", translate), ("rotate", rotate),
                               ("scale", scale), ("pivots", pivot))
                if v is not None]
    plugwrite.guard(
        cmds,
        [plug for name in resolved
         for plug in plugwrite.transform_plugs(name, channels)],
        "transform",
        consequence="nothing was moved - the transform is all-or-nothing "
                    "across every name in the call, as delete_objects is")

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


# Every top-level key group reads. Anything else is refused rather
# than ignored (#767): an unread key does not fail, it succeeds and does
# something else.
GROUP_KEYS = ("names", "group_name")
# `name` is what the RESULT calls the group that was made, so a caller who
# read one result reaches for it as the input - the #764 shape. Recording it
# is what makes the refusal useful here, because the prefix fallback would
# point at `names`, the list of CHILDREN, and send the caller further wrong.
# `objects` is the generic word for the things being gathered, and it is what
# transform's result calls the objects it touched.
GROUP_SYNONYMS = {"name": "group_name", "objects": "names"}


def group(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, GROUP_KEYS, "group", GROUP_SYNONYMS)
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


# Every top-level key parent reads. Anything else is refused rather
# than ignored (#767): an unread key does not fail, it succeeds and does
# something else.
PARENT_KEYS = ("child", "parent")
# `name` is what the result calls the reparented child, so a caller echoing a
# result back reaches for it. Neither `child` nor `parent` starts like it, so
# the prefix fallback has nothing to offer and the entry is the only way the
# refusal can say which of the two was meant.
PARENT_SYNONYMS = {"name": "child"}


def parent(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, PARENT_KEYS, "parent", PARENT_SYNONYMS)
    cmds = _cmds()
    child = naming.require_object(cmds, str(params.get("child") or ""))
    target = naming.require_object(cmds, str(params.get("parent") or ""))
    moved = cmds.parent(child, target)
    long_name = _long(cmds, moved[0])
    ledger.forget(child)  # its long name just changed
    ledger.record(cmds, long_name)
    return {"name": long_name, "warnings": []}


# Every top-level key rename reads. Anything else is refused rather
# than ignored (#767): an unread key does not fail, it succeeds and does
# something else.
RENAME_KEYS = ("name", "new_name")
# Because the destination key is `new_name`, the source key reads as
# `old_name` by symmetry, but here it is plainly `name`. `old` starts neither
# allowed key, so the prefix fallback would say nothing at all.
RENAME_SYNONYMS = {"old_name": "name"}


def rename(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, RENAME_KEYS, "rename", RENAME_SYNONYMS)
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


# Every top-level key delete_objects reads. Anything else is refused rather
# than ignored (#767): an unread key does not fail, it succeeds and does
# something else.
DELETE_OBJECTS_KEYS = ("names",)
# The command's own name ends in `objects` and transform's result calls the
# things it touched `objects`, so that is the word a caller reaches for; the
# key is `names`, which `obj` never reaches.
DELETE_OBJECTS_SYNONYMS = {"objects": "names"}


def delete_objects(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, DELETE_OBJECTS_KEYS, "delete_objects",
                       DELETE_OBJECTS_SYNONYMS)
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
# How far a local transform channel may sit from identity before the result is
# considered to be carrying a compensating transform that must be baked.
IDENTITY_TOL = 1e-6


def _uv_bounds(cmds, shape: str) -> Optional[List[float]]:
    """[u_min, v_min, u_max, v_max] over every UV on `shape`, or None if it has none."""
    flat = cmds.polyEditUV(shape + ".map[*]", query=True) or []
    if not flat:
        return None
    us, vs = flat[0::2], flat[1::2]
    return [min(us), min(vs), max(us), max(vs)]


def _fold_cutter_uvs(cmds, target: Optional[List[float]], b_shape: str) -> None:
    """Move the cutter's UVs into `target` BEFORE the boolean runs.

    polyCBoolOp keeps each operand's own UVs, so the faces the cutter
    contributes arrive carrying the CUTTER's layout. Measured on the #638
    repro: 22 of the result's 34 UVs sat in the chunk's atlas patch and the
    other 12 sat in the cutter's - the newly cut face sampling a different
    material, invisible until the texture goes on.

    Folding beforehand rather than repacking afterwards is deliberate. Once the
    two operands are merged there is no reliable way to tell whose UVs are
    whose: matching by value mangles any of the cutter's that happen to land
    inside the chunk's patch, and leaves the rest.
    """
    if target is None:
        return
    source = _uv_bounds(cmds, b_shape)
    if source is None:
        return
    fold = uvmath.fold_transform(source, target)
    if uvmath.is_identity_fold(fold):
        return
    pivot_u, pivot_v, scale_u, scale_v, delta_u, delta_v = fold
    cmds.polyEditUV(b_shape + ".map[*]", pivotU=pivot_u, pivotV=pivot_v,
                    scaleU=scale_u, scaleV=scale_v)
    cmds.polyEditUV(b_shape + ".map[*]", uValue=delta_u, vValue=delta_v)


def _carry_parent(
    cmds, out_long: str, parent: Optional[str], b_long: str, warnings: List[str]
) -> Tuple[str, bool]:
    """Put the result back under A's parent, BEFORE history is deleted.

    Order matters and is measured, not assumed: polyCBoolOp leaves the consumed
    operands in place as empty transforms, and it is `delete(constructionHistory
    =True)` that reaps them - taking A's parent group with them when A was its
    only child. Reparenting first leaves that group holding the result, so it
    survives.
    """
    if parent is None:
        return out_long, False
    if parent == b_long:
        warnings.append(
            "a's parent %s is the cutter itself, so it does not outlive this "
            "call; the result is at the scene root" % parent
        )
        return out_long, False
    if not cmds.objExists(parent):
        warnings.append(
            "a's parent %s no longer exists; the result is at the scene root" % parent
        )
        return out_long, False
    moved = cmds.parent(out_long, parent) or [out_long]
    return _long(cmds, moved[0]), True


def _bake_compensating_transform(cmds, node: str) -> bool:
    """Freeze a local transform the reparent introduced. True if anything moved.

    cmds.parent preserves world position, so dropping the result under a scaled
    or rotated group hands it the INVERSE of that group - the compensating
    transform #629 exists to stamp out, and the one the export gate refuses by
    name. The vertices already hold world-space geometry, so baking it costs
    nothing and leaves the node at identity.
    """
    channels = (
        ("translate", 0.0), ("rotate", 0.0), ("scale", 1.0),
    )
    for attr, neutral in channels:
        values = cmds.getAttr(node + "." + attr)[0]
        if any(abs(float(v) - neutral) > IDENTITY_TOL for v in values):
            cmds.makeIdentity(
                node, apply=True, translate=True, rotate=True, scale=True
            )
            return True
    return False


def _claim_name(cmds, node: str, requested: str) -> str:
    """Rename `node` to `requested` if that name is free by now; else leave it.

    Called after the history delete, which is the first moment a name belonging
    to a consumed operand becomes available. Before then Maya still holds it -
    polyCBoolOp leaves both operands as emptied transforms - so reserving the
    name up front produced `X_001` for the most natural request there is: cut a
    socket into X and have the result still be called X (#640).

    A name genuinely held by an unrelated object is left alone: the staged name
    stays, which is exactly what the caller got before this existed.
    """
    if node.split("|")[-1] == requested:
        return node
    if naming.unique_name(cmds, requested) != requested:
        return node
    return _long(cmds, cmds.rename(node, requested))


def _do_boolean(cmds, a_long: str, b_long: str, op: str, new_name: str) -> Dict[str, Any]:
    """Shared boolean core: polyCBoolOp + the golem-run cleanup discipline.

    `new_name` is the name the caller ASKED for, not a pre-uniquified one: it
    may be a's or b's own name, and honouring that needs the claim to happen at
    a specific point in this sequence. See _claim_name.

    Per-face shader assignment on boolean output silently no-ops and corrupts
    shading groups (redmine #577 req 1), so: delete history immediately, then
    collapse shading to one object-level SG (input A's material wins).

    polyCBoolOp builds a brand-new root object, and everything A carried that
    is not vertices is A's alone: its pivot, its place in the hierarchy, its
    atlas patch. #638 measured all three lost on one silent call. They are read
    off A here, before it is consumed, and put back on the result.
    """
    from . import meshcheck  # noqa: PLC0415 - keep module import cheap headless

    _, a_shape = naming.require_mesh(cmds, a_long)
    # Resolved rather than taken as given: etch_text passes the glyph by short
    # name, and _carry_parent below compares this against a long parent path.
    b_long, b_shape = naming.require_mesh(cmds, b_long)
    fallback_sg = meshcheck.first_sg(cmds, a_shape)

    a_parent = (cmds.listRelatives(a_long, parent=True, fullPath=True) or [None])[0]
    a_pivot = [
        float(v) for v in
        cmds.xform(a_long, query=True, worldSpace=True, rotatePivot=True)
    ]
    a_uv = _uv_bounds(cmds, a_shape)
    _fold_cutter_uvs(cmds, a_uv, b_shape)

    # Staged under a name that cannot collide with the operands Maya still
    # holds; the requested one is claimed after the history delete below.
    staged = naming.unique_name(cmds, new_name)
    result = cmds.polyCBoolOp(a_long, b_long, op=BOOLEAN_OPS[op], name=staged)
    out = cmds.rename(result[0], staged)
    out_long = _long(cmds, out)

    warnings: List[str] = []
    out_long, reparented = _carry_parent(cmds, out_long, a_parent, b_long, warnings)
    cmds.delete(out_long, constructionHistory=True)
    # The operands' emptied transforms are gone now, so a name that was theirs
    # is free. This is the only moment it can be taken.
    out_long = _claim_name(cmds, out_long, new_name)
    if out_long.split("|")[-1] != new_name:
        warnings.append(
            "the result is called %s, not the requested %r: that name is held by "
            "another object which this call did not consume"
            % (out_long.split("|")[-1], new_name)
        )

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

    # Freeze BEFORE placing the pivot: makeIdentity resets pivots to the origin,
    # so a pivot set first would be silently thrown away.
    if reparented and _bake_compensating_transform(cmds, out_long):
        warnings.append(
            "the result inherited a compensating transform from %s and it was "
            "frozen into the vertices; a non-identity node scale is what the "
            "export gate refuses (#629)" % a_parent
        )
    cmds.xform(out_long, worldSpace=True, pivots=tuple(a_pivot))
    pivot = [
        float(v) for v in
        cmds.xform(out_long, query=True, worldSpace=True, rotatePivot=True)
    ]
    if max((abs(p - q) for p, q in zip(pivot, a_pivot)), default=0.0) > 1e-4:
        warnings.append(
            "a's pivot %s could not be carried onto the result: it sits at %s"
            % ([round(v, 5) for v in a_pivot], [round(v, 5) for v in pivot])
        )

    uv_bounds = _uv_bounds(cmds, out_shape)
    if a_uv is not None and uv_bounds is not None and not uvmath.rect_contains(
        uv_bounds, a_uv
    ):
        warnings.append(
            "the result's UVs span %s, outside a's %s: the newly cut faces will "
            "sample a different part of the texture. Re-run maya_uv_atlas on "
            "this mesh."
            % ([round(v, 4) for v in uv_bounds], [round(v, 4) for v in a_uv])
        )

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
        "parent": (cmds.listRelatives(out_long, parent=True, fullPath=True)
                   or [None])[0],
        "pivot": [round(v, 6) for v in pivot],
        "uv_bounds": None if uv_bounds is None else [round(v, 6) for v in uv_bounds],
        "warnings": warnings,
    }


# Every top-level key boolean_op reads. Anything else is refused rather than
# ignored (#767): an unread key does not fail, it succeeds and does something
# else. Refusing here also spares the auto_checkpoint below - an invalid call
# must not burn a checkpoint slot.
BOOLEAN_OP_KEYS = ("a", "b", "op", "new_name")
# The result reports the surviving object as `name`, so a caller who read one
# result reaches for `name` when they mean to name the new one - the #764
# shape, and `nam` reaches no key for the prefix fallback to suggest.
BOOLEAN_OP_SYNONYMS = {"name": "new_name"}


def boolean_op(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, BOOLEAN_OP_KEYS, "boolean_op",
                       BOOLEAN_OP_SYNONYMS)
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
    # Raw, not uniquified: new_name may be a's or b's, and both are about to
    # stop existing. _do_boolean claims it at the only moment it is free (#640).
    return _do_boolean(cmds, a_long, b_long, op, requested.strip())


MIN_TARGET_POLYCOUNT = 100
MAX_TARGET_POLYCOUNT = 200000


# Every top-level key remesh_retopo reads. Anything else is refused rather
# than ignored (#767). `name` is the generic word for the single object this
# operates on; `polycount` and `faces` are what the budget is called
# everywhere except in this key, and none of the three reaches its target
# through the prefix fallback.
REMESH_RETOPO_KEYS = ("mesh", "target_polycount", "keep_original")
REMESH_RETOPO_SYNONYMS = {"name": "mesh", "polycount": "target_polycount",
                          "faces": "target_polycount"}


def remesh_retopo(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, REMESH_RETOPO_KEYS, "remesh_retopo",
                       REMESH_RETOPO_SYNONYMS)
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


# Every top-level key mesh_cleanup reads. Anything else is refused rather
# than ignored (#767). `name` is the generic word for the mesh; `threshold`
# is what the merge distance is called in conversation and in this handler's
# own local variable, while the key spells out which threshold it is.
MESH_CLEANUP_KEYS = ("mesh", "merge_verts_threshold", "conform_normals",
                     "freeze_transforms", "delete_history")
MESH_CLEANUP_SYNONYMS = {"name": "mesh",
                         "threshold": "merge_verts_threshold"}


def mesh_cleanup(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, MESH_CLEANUP_KEYS, "mesh_cleanup",
                       MESH_CLEANUP_SYNONYMS)
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
