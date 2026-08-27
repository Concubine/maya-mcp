"""create_curve_form: sweep/revolve/loft meshes from through-points (#768).

Curve-driven form authoring exists because sculpting has no eyes on it: an
agent cannot look at a viewport and correct a blob by hand, but it CAN name
the points a curve must pass through and let Maya's own curve/surface
machinery (EP curves, sweep, revolve, loft) build the mesh precisely. See
`docs/superpowers/plans/2026-08-26-modelling-vocabulary-gap.md` for why this
is the right primitive for authoring without eyes, and `curveform_math.py`
for the pure spec validation and "station" conformance math every number in
this module's result is judged against.

Three curve verbs, one handler:
  - sweep:   extrude a profile along a through-point path (a horn, a limb).
  - revolve: spin a (radius, height) profile around an axis (a vase, a bowl).
  - loft:    blend between through-point rings (a torso from cross-sections).

Whole-call validation (assemble-style) happens BEFORE any `cmds` import:
`curveform_math.validate_spec` and `predicted_faces` run on plain dicts, so a
bad call is refused without ever touching Maya, and a call that reaches Maya
either succeeds or cleans up every construction node it made along the way.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..dispatcher import HandlerError, require_known_keys
from . import curveform_math, ledger, meshcheck, naming
from .modeling import _apply_xform, _long, _vec3

CREATE_CURVE_FORM_KEYS = (
    "kind", "name", "path", "width", "twist", "profile_sides",
    "profile", "degrees", "axis", "sections",
    "resolution", "cap_ends", "translate", "rotate", "scale",
)
CREATE_CURVE_FORM_SYNONYMS = {
    "points": "path", "taper": "width", "curve": "path",
    "rings": "sections", "sides": "profile_sides", "cross_sections": "sections",
}
# Soft self-report threshold; the live gate (Task 6) MEASURES the real
# number and this constant is updated there - see the gate's Step 5.
DEVIATION_WARN = 0.05

# Measured by evals/curveform_probe_768.py - if the probe printed different
# names, THESE ARE WRONG: fix them here, in one place.
_SWEEP_CREATOR_TYPE = "sweepMeshCreator"
_SWEEP_PLUGIN = "sweep"
# taperCurve's per-stop interpolation enum, measured live: 1 = linear. The
# ramp already carries only two-decimal-precision stops (curveform_math's
# `parse_ramp`), so a smoother interpolation would invent shape the caller
# never asked for.
_TAPER_INTERP_LINEAR = 1

_AXIS_VECTORS = {
    "x": (1.0, 0.0, 0.0),
    "y": (0.0, 1.0, 0.0),
    "z": (0.0, 0.0, 1.0),
}


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _ensure_sweep_plugin(cmds) -> None:
    """Load the "sweep" plugin - `sweepMeshFromCurve` does not exist without it.

    Measured in Task 1's probe (evals/curveform_probe_768.py): the command is
    absent from `cmds`/MEL until `loadPlugin("sweep")` runs, after which both
    the command and the `sweepMeshCreator` node type are fully available.
    `loadPlugin` on an already-loaded plugin is normally a no-op, but this
    wraps it anyway so a Maya version that raises on a redundant load does
    not turn a healthy second call into a refusal.
    """
    try:
        cmds.loadPlugin(_SWEEP_PLUGIN, quiet=True)
    except RuntimeError:
        pass  # already loaded


def _curve_degree(point_count: int) -> int:
    return min(3, point_count - 1)


def _ep_curve(cmds, points: Sequence[Sequence[float]]) -> str:
    pts = [tuple(p) for p in points]
    return cmds.curve(ep=pts, degree=_curve_degree(len(pts)))


def _ring_curve(cmds, points: Sequence[Sequence[float]]) -> str:
    """A closed periodic curve through `points` - probe-verified flags.

    EP curve through the ring plus its own first point (closing the loop),
    then `closeCurve` with `replaceOriginal=True` folds it into a periodic
    (form=2) curve in place - the exact sequence Task 1's probe measured to
    produce a periodic curve loft/revolve can consume.
    """
    closed_pts = list(points) + [points[0]]
    curve = _ep_curve(cmds, closed_pts)
    result = cmds.closeCurve(
        curve, constructionHistory=False, preserveShape=0, replaceOriginal=True
    )
    return result[0]


def _nurbs_to_poly(cmds, surface: str, along: int, around: int) -> str:
    """Tessellate a NURBS surface to poly - u the along-count, v the around-count.

    Probe-measured (revolve: uNumber=24/vNumber=16 -> 345 = 23*15 faces): the
    conversion produces roughly (n-1) divisions per direction, and the
    controller ruling on Task 1's findings maps u to `along`, v to `around`
    for both revolve and loft. Face counts are not chased exactly here -
    station conformance (curveform_math.station_expectations) is the
    correctness measure, not a predicted face total.
    """
    result = cmds.nurbsToPoly(
        surface, constructionHistory=False, format=2, polygonType=1,
        uType=2, uNumber=along, vType=2, vNumber=around,
    )
    return result[0]


def _build_sweep(cmds, spec: Dict[str, Any], requested: str, temp_nodes: List[str]) -> str:
    _ensure_sweep_plugin(cmds)
    path_curve = _ep_curve(cmds, spec["path"])
    temp_nodes.append(path_curve)

    # sweepMeshFromCurve returns None (probe-measured) - the created mesh and
    # its creator node are found by diffing the scene before/after the call,
    # exactly as the controller ruling on Task 1 specifies.
    before_nodes = set(cmds.ls(long=True))
    before_creators = set(cmds.ls(type=_SWEEP_CREATOR_TYPE, long=True) or [])
    cmds.sweepMeshFromCurve(path_curve)
    after_nodes = set(cmds.ls(long=True))
    after_creators = set(cmds.ls(type=_SWEEP_CREATOR_TYPE, long=True) or [])

    new_meshes = [
        n for n in (after_nodes - before_nodes) if cmds.nodeType(n) == "mesh"
    ]
    new_creators = list(after_creators - before_creators)
    if len(new_meshes) != 1 or len(new_creators) != 1:
        raise HandlerError(
            "sweepMeshFromCurve produced %d mesh shape(s) and %d creator "
            "node(s), expected exactly one of each"
            % (len(new_meshes), len(new_creators)),
            hint="this is an internal error - the sweep plugin's output "
            "shape changed on this Maya version",
        )
    mesh_shape = new_meshes[0]
    creator = new_creators[0]
    mesh = (cmds.listRelatives(mesh_shape, parent=True, fullPath=True) or [mesh_shape])[0]

    # Width mapping (verified empirically in mayapy, see Task 3's report):
    # the default poly profile is a diameter-1 shape at scaleProfile*=1.0
    # (profilePolyInnerRadius defaults to 0.5), so scaling the profile by the
    # ramp's PEAK width gives the widest point its correct diameter, and the
    # taper ramp then carries every stop's width as a FRACTION of that peak.
    width = spec["width"]
    max_width = max(v for _, v in width)
    cmds.setAttr(creator + ".scaleProfileUniform", True)
    cmds.setAttr(creator + ".scaleProfileX", max_width)
    cmds.setAttr(creator + ".scaleProfileY", max_width)
    for i, (t, w) in enumerate(width):
        prefix = "%s.taperCurve[%d]" % (creator, i)
        cmds.setAttr(prefix + ".taperCurve_Position", t)
        cmds.setAttr(prefix + ".taperCurve_FloatValue", w / max_width)
        cmds.setAttr(prefix + ".taperCurve_Interp", _TAPER_INTERP_LINEAR)

    if spec["twist"] is not None:
        cmds.setAttr(creator + ".twist", spec["twist"])

    sides = spec["profile_sides"]
    if sides is None:
        # No explicit polygon requested - approximate a round tube with as
        # many sides as the "around" tessellation asks for.
        sides = spec["resolution"]["around"]
    cmds.setAttr(creator + ".profilePolySides", sides)
    cmds.setAttr(creator + ".interpolationSteps", spec["resolution"]["along"])
    cmds.setAttr(creator + ".capsEnable", spec["cap_ends"])

    # Bake: the creator node's history is what makes the attrs above take
    # effect on real geometry rather than staying a deferred recipe.
    cmds.delete(mesh, constructionHistory=True)
    return _long(cmds, cmds.rename(mesh, requested))


def _build_revolve(cmds, spec: Dict[str, Any], requested: str, temp_nodes: List[str]) -> str:
    axis = spec["axis"]
    # Same per-axis (radius, height) -> point mapping curveform_math uses for
    # its theta=0 revolve stations, reused rather than re-derived so the
    # authored profile and the measurement can never drift apart.
    pts3 = [
        curveform_math._revolve_point(r, h, 0.0, axis)
        for r, h in spec["profile"]
    ]
    profile_curve = _ep_curve(cmds, pts3)
    temp_nodes.append(profile_curve)

    revolved = cmds.revolve(
        profile_curve, constructionHistory=False, axis=_AXIS_VECTORS[axis],
        pivot=(0.0, 0.0, 0.0), degree=3, sections=spec["resolution"]["around"],
        startSweep=0.0, endSweep=spec["degrees"],
    )[0]
    temp_nodes.append(revolved)

    poly = _nurbs_to_poly(
        cmds, revolved, spec["resolution"]["along"], spec["resolution"]["around"]
    )
    return _long(cmds, cmds.rename(poly, requested))


def _build_loft(cmds, spec: Dict[str, Any], requested: str, temp_nodes: List[str]) -> str:
    curves = []
    for ring in spec["sections"]:
        curve = _ring_curve(cmds, ring)
        temp_nodes.append(curve)
        curves.append(curve)

    lofted = cmds.loft(
        *curves, constructionHistory=False, uniform=True, close=False,
        autoReverse=False, degree=3,
    )[0]
    temp_nodes.append(lofted)

    poly = _nurbs_to_poly(
        cmds, lofted, spec["resolution"]["along"], spec["resolution"]["around"]
    )
    return _long(cmds, cmds.rename(poly, requested))


_BUILDERS = {
    "sweep": _build_sweep,
    "revolve": _build_revolve,
    "loft": _build_loft,
}


def _station_deviation(distance: float, expected: Tuple[float, float]) -> float:
    lo, hi = expected
    if distance < lo:
        return lo - distance
    if distance > hi:
        return distance - hi
    return 0.0


def _measure_stations(
    cmds, mesh: str, stations: List[Dict[str, Any]], size: float
) -> Tuple[float, Optional[str]]:
    """Worst (normalized) station deviation and which station produced it.

    `space` is passed as a KEYWORD to `getClosestPoint` - the same
    positional-overload trap `maya-api-positional-overload-trap` documents
    for `MSpace` constants elsewhere in this codebase: they are plain ints,
    and a positional one silently binds the wrong overload.
    """
    import maya.api.OpenMaya as om  # noqa: PLC0415 - only importable inside Maya

    sel = om.MSelectionList()
    sel.add(mesh)
    dag = sel.getDagPath(0)
    try:
        dag.extendToShape()
    except RuntimeError:
        pass  # already a shape
    fn = om.MFnMesh(dag)

    measurements: List[Tuple[float, str]] = []
    for station in stations:
        point = om.MPoint(*station["point"])
        closest, _face = fn.getClosestPoint(point, space=om.MSpace.kWorld)
        distance = (closest - point).length()
        deviation = _station_deviation(distance, tuple(station["expected"]))
        normalized = deviation / size if size > 1e-9 else deviation
        measurements.append((normalized, station["label"]))

    if not measurements:
        return 0.0, None
    return max(measurements, key=lambda pair: pair[0])


def create_curve_form(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(
        params, CREATE_CURVE_FORM_KEYS, "create_curve_form", CREATE_CURVE_FORM_SYNONYMS
    )
    requested_name = params.get("name")
    if not isinstance(requested_name, str) or not requested_name.strip():
        raise HandlerError(
            "missing required param 'name'",
            hint="pass the object name to create, e.g. name='horn'",
        )

    # Pure validation - no Maya touched yet. A bad spec or an impossible
    # tessellation bill is refused here, before anything is built.
    spec = curveform_math.validate_spec(params)
    curveform_math.predicted_faces(spec)

    cmds = _cmds()
    requested = naming.unique_name(cmds, requested_name.strip())

    temp_nodes: List[str] = []
    try:
        mesh = _BUILDERS[spec["kind"]](cmds, spec, requested, temp_nodes)

        if spec["cap_ends"]:
            pre_stats = meshcheck.mesh_stats(mesh)
            if pre_stats["boundary_edges"] > 0:
                cmds.polyCloseBorder(mesh, constructionHistory=False)
    finally:
        # Every curve/surface this build made is scaffolding, not the
        # result - delete it on ANY exit, success or failure (assemble-style
        # whole-call discipline: a half-built form must not litter the scene).
        for node in temp_nodes:
            if cmds.objExists(node):
                cmds.delete(node)

    # Measure BEFORE placement: stations are authored in the form's own
    # local frame, and building at the origin keeps the measurement simple
    # and correct without transforming every expectation to match a
    # translate/rotate/scale applied first.
    stations = curveform_math.station_expectations(spec)
    size = curveform_math.form_size(spec)
    worst_deviation, worst_station = _measure_stations(cmds, mesh, stations, size)

    long_name = _long(cmds, mesh)
    _apply_xform(
        cmds, long_name,
        _vec3(params, "translate"), _vec3(params, "rotate"), _vec3(params, "scale"),
        relative=False,
    )
    ledger.record(cmds, long_name)

    stats = meshcheck.mesh_stats(long_name)
    warnings: List[str] = []
    if worst_deviation > DEVIATION_WARN:
        warnings.append(
            "worst station deviation %.4f of form size at %s - raise "
            "`resolution` or simplify the curve"
            % (worst_deviation, worst_station)
        )
    if spec["cap_ends"] and not stats["watertight"]:
        warnings.append(
            "cap_ends was requested but the mesh is not watertight (%d "
            "boundary, %d non-manifold edges)"
            % (stats["boundary_edges"], stats["nonmanifold_edges"])
        )

    return {
        "name": long_name,
        "faces": stats["faces"],
        "verts": stats["verts"],
        "watertight": stats["watertight"],
        "stations": len(stations),
        "worst_station_deviation": worst_deviation,
        "worst_station": worst_station,
        "form_size": size,
        "warnings": warnings,
    }
