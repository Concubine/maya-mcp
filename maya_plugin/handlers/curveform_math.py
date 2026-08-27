"""Pure spec validation and station math for `create_curve_form` (#768).

Curve-driven form authoring (sweep/revolve/loft) has no eyes on it - the
caller cannot look at a viewport and see whether a swept horn came out fat or
thin, or whether a revolve's profile ended up mirrored. The only way to make
those claims checkable is to compute, in isolation from Maya, what the
result SHOULD measure: a predicted face count and a set of "station"
expectations - points the finished mesh's surface must pass through (or near)
within a known tolerance band. The handler that drives `maya.cmds` (Task 3)
builds the geometry; every number it gets judged against comes from here.

Three curve verbs, one spec shape. `validate_spec` normalizes whatever a
caller sends (defaults filled in, ramps parsed, cross-kind mistakes refused)
into the shape documented on each per-kind validator below, and every other
function in this module consumes that normalized shape - never raw params.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..dispatcher import HandlerError
from .modeling import MAX_PRIMITIVE_FACES

KINDS = ("sweep", "revolve", "loft")
AXES = ("x", "y", "z")

# Keys unique to one curve kind - anything outside this plus _COMMON is
# either unknown (the handler-level require_known_keys catches that) or a
# genuine cross-kind mistake (a known param, wrong verb) that only this
# module can name, because only this module knows which verb is which.
_SWEEP_ONLY = {"path", "width", "twist", "profile_sides"}
_REVOLVE_ONLY = {"profile", "degrees", "axis"}
_LOFT_ONLY = {"sections"}
_COMMON = {"kind", "name", "cap_ends", "resolution"}
_ONLY_BY_KIND = {"sweep": _SWEEP_ONLY, "revolve": _REVOLVE_ONLY, "loft": _LOFT_ONLY}

# A path/profile/section point list past this size is very likely a mistake
# (a mocap trajectory dumped in wholesale, say) rather than an authored curve -
# the same reasoning as arraymath.MAX_COUNT and modeling.MAX_PRIMITIVE_FACES:
# bound the input so a bad call fails fast instead of building something huge.
MAX_PATH_POINTS = 64
MAX_PROFILE_POINTS = 64
MAX_SECTIONS = 16
MAX_RING_POINTS = 64
MIN_RING_POINTS = 3

# Resolution ceilings. Deliberately far below the point where along*around
# alone would exceed MAX_PRIMITIVE_FACES (512*256 = 131072, well under
# 1,000,000) - these bound how fine a SINGLE authored curve can be tessellated,
# a separate concern from the total face budget predicted_faces enforces.
MAX_ALONG = 512
MAX_AROUND = 256

# Matches the MCP surface's declared `profile_sides` ceiling (le=64 in
# src/maya_mcp/server.py) - the handler owns this limit too (#764's lesson:
# a param validated only at the wire's edge is not validated), so the two
# numbers must be kept in agreement by hand if either one ever changes.
MAX_PROFILE_SIDES = 64

_SWEEP_DEFAULT_RESOLUTION = {"along": 32, "around": 16}
_REVOLVE_LOFT_DEFAULT_RESOLUTION = {"along": 24, "around": 24}

# Below this, two consecutive path/section points are treated as the same
# point (a zero-length segment has no direction to sweep along, and chord_params
# would divide by zero on it).
_DUP_POINT_EPS = 1e-9

# Station sampling for a revolve: 4 angles per profile point, evenly spaced
# starting at 0 (not including `degrees` itself) so a full 360-degree revolve
# does not resample its own seam.
_REVOLVE_STATION_ANGLES = 4


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_point3(point: Any, what: str) -> List[float]:
    if (
        not isinstance(point, (list, tuple))
        or len(point) != 3
        or any(not _is_number(v) for v in point)
    ):
        raise HandlerError(
            "%s must be three numbers, got %r" % (what, point),
            hint="e.g. %s=[0, 1, 0]" % what,
        )
    return [float(v) for v in point]


def _refuse_consecutive_duplicates(
    points: Sequence[Sequence[float]], what: str, wrap: bool = False
) -> None:
    """Refuse two consecutive points that are the same point.

    Applies uniformly to every point list a spec carries - `path`, `profile`,
    and each loft `sections` ring - because a zero-length segment has no
    direction anywhere it appears, not just on a sweep's path. `wrap=True`
    additionally refuses a ring whose last point repeats its first: a ring
    closes itself implicitly, so an explicit closing point is the same
    "repeated point" mistake, not a legitimately different one.
    """
    for i in range(1, len(points)):
        if math.dist(points[i - 1], points[i]) < _DUP_POINT_EPS:
            raise HandlerError(
                "%s has consecutive duplicate points at index %d" % (what, i),
                hint="remove the repeated point - a zero-length segment has no direction",
            )
    if wrap and len(points) >= 2 and math.dist(points[-1], points[0]) < _DUP_POINT_EPS:
        raise HandlerError(
            "%s closes itself - its last point repeats its first" % what,
            hint="a ring closes itself automatically - don't repeat the first point as the last",
        )


def _validate_cap_ends(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raise HandlerError(
        "cap_ends must be true or false, got %r" % (value,),
        hint="cap_ends=True closes the open ends with n-gon caps",
    )


def _validate_axis(value: Any) -> str:
    if not isinstance(value, str) or value.lower() not in AXES:
        raise HandlerError(
            "axis must be one of %s, got %r" % (", ".join(AXES), value),
            hint="axis='y' revolves around the vertical, Maya's default up axis",
        )
    return value.lower()


def _validate_resolution(value: Any, default: Dict[str, int]) -> Dict[str, int]:
    if value is None:
        return dict(default)
    if not isinstance(value, dict):
        raise HandlerError(
            "resolution must be a dict with 'along'/'around', got %r" % (value,),
            hint="e.g. resolution={'along': %d, 'around': %d}"
            % (default["along"], default["around"]),
        )
    unknown = sorted(set(value) - {"along", "around"})
    if unknown:
        raise HandlerError(
            "resolution does not take %s" % ", ".join(repr(k) for k in unknown),
            hint="resolution takes only 'along' and 'around'",
        )
    along = value.get("along", default["along"])
    around = value.get("around", default["around"])
    if isinstance(along, bool) or not isinstance(along, int) or along < 1:
        raise HandlerError(
            "resolution.along must be a positive whole number, got %r" % (along,),
            hint="e.g. resolution={'along': %d, 'around': %d}"
            % (default["along"], default["around"]),
        )
    if isinstance(around, bool) or not isinstance(around, int) or around < 1:
        raise HandlerError(
            "resolution.around must be a positive whole number, got %r" % (around,),
            hint="e.g. resolution={'along': %d, 'around': %d}"
            % (default["along"], default["around"]),
        )
    if along > MAX_ALONG:
        raise HandlerError(
            "resolution.along %d exceeds the maximum of %d" % (along, MAX_ALONG),
            hint="MAX_ALONG=%d bounds tessellation fineness - lower resolution" % MAX_ALONG,
        )
    if around > MAX_AROUND:
        raise HandlerError(
            "resolution.around %d exceeds the maximum of %d" % (around, MAX_AROUND),
            hint="MAX_AROUND=%d bounds tessellation fineness - lower resolution" % MAX_AROUND,
        )
    return {"along": along, "around": around}


def _refuse_foreign_keys(params: Dict[str, Any], kind: str) -> None:
    """Refuse a param that belongs to a DIFFERENT curve kind, by name.

    A key the handler-level require_known_keys would accept (it is a real
    param of *some* command) but this kind never reads is a different mistake
    than a typo - the caller reached for the wrong verb's vocabulary, most
    likely `profile` on a sweep when they meant a revolve. Name the kind that
    actually takes it rather than just refusing.
    """
    other_owner: Dict[str, str] = {}
    for other_kind, keys in _ONLY_BY_KIND.items():
        if other_kind == kind:
            continue
        for key in keys:
            other_owner[key] = other_kind
    present = sorted(set(params) & set(other_owner))
    if present:
        key = present[0]
        raise HandlerError(
            "%s does not take %r - that's a %s param" % (kind, key, other_owner[key]),
            hint="valid %s params: %s" % (kind, ", ".join(sorted(_COMMON | _ONLY_BY_KIND[kind]))),
        )


def parse_ramp(value: Any, what: str) -> List[Tuple[float, float]]:
    """A number or a list of `[t, v]` stops, normalized to sorted `(t, v)` pairs.

    A bare number becomes a flat ramp spanning the whole curve - the common
    case (uniform width) should not need two-point boilerplate. Stops must
    have `t` in `[0, 1]`, strictly increasing (a repeated or backwards `t` has
    no unambiguous interpolation), and `v > 0` (a zero or negative width/value
    collapses or inverts the swept surface).
    """
    if _is_number(value):
        v = float(value)
        if v <= 0.0:
            raise HandlerError(
                "%s must be positive, got %r" % (what, value),
                hint="%s is a size, not a signed offset - use a positive number" % what,
            )
        return [(0.0, v), (1.0, v)]
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise HandlerError(
            "%s ramp needs at least two [t, value] stops, got %r" % (what, value),
            hint="e.g. %s=[[0.0, 1.0], [1.0, 0.5]], or a bare number for a flat ramp" % what,
        )
    stops: List[Tuple[float, float]] = []
    prev_t: Optional[float] = None
    for entry in value:
        if (
            not isinstance(entry, (list, tuple))
            or len(entry) != 2
            or any(not _is_number(v) for v in entry)
        ):
            raise HandlerError(
                "%s ramp stop must be [t, value], got %r" % (what, entry),
                hint="e.g. [0.5, 1.0]",
            )
        t, v = float(entry[0]), float(entry[1])
        if not (0.0 <= t <= 1.0):
            raise HandlerError(
                "%s ramp t must be within [0, 1], got %r" % (what, t),
                hint="t is a fraction of the curve's length, 0 at the start, 1 at the end",
            )
        if v <= 0.0:
            raise HandlerError(
                "%s value must be positive, got %r" % (what, v),
                hint="%s is a size, not a signed offset - use a positive number" % what,
            )
        if prev_t is not None and t <= prev_t:
            raise HandlerError(
                "%s ramp stops must have strictly increasing t, got %r after %r"
                % (what, t, prev_t),
                hint="sort the stops by t, and give each a distinct t",
            )
        stops.append((t, v))
        prev_t = t
    return stops


def ramp_value(ramp: Sequence[Tuple[float, float]], t: float) -> float:
    """Linear interpolation along `ramp`, clamped to its first/last stop."""
    if t <= ramp[0][0]:
        return ramp[0][1]
    if t >= ramp[-1][0]:
        return ramp[-1][1]
    for (t0, v0), (t1, v1) in zip(ramp, ramp[1:]):
        if t0 <= t <= t1:
            frac = (t - t0) / (t1 - t0)
            return v0 + (v1 - v0) * frac
    return ramp[-1][1]  # unreachable given the clamps above


def chord_params(points: Sequence[Sequence[float]]) -> List[float]:
    """Cumulative chord-length fraction at each point, `[0.0, ..., 1.0]`.

    Index-based parameterization ("point i is at t = i/(n-1)") is wrong the
    moment segment lengths differ - a long first segment and a short second
    one would place their shared point at the same t either way, which is
    exactly backwards from where a ramp sampled by ARC LENGTH would put it.
    """
    if len(points) == 1:
        return [0.0]
    cum = [0.0]
    total = 0.0
    for i in range(1, len(points)):
        total += math.dist(points[i - 1], points[i])
        cum.append(total)
    if total <= 0.0:
        n = len(points)
        return [i / (n - 1) for i in range(n)]
    return [d / total for d in cum]


def _validate_path(path: Any) -> List[List[float]]:
    if not isinstance(path, (list, tuple)) or len(path) < 2:
        raise HandlerError(
            "path needs at least 2 points, got %r" % (path,),
            hint="e.g. path=[[0, 0, 0], [0, 1, 0]]",
        )
    if len(path) > MAX_PATH_POINTS:
        raise HandlerError(
            "path has %d points, over the %d-point limit" % (len(path), MAX_PATH_POINTS),
            hint="thin the path, or build the form in multiple sweeps",
        )
    points = [_validate_point3(p, "path point") for p in path]
    _refuse_consecutive_duplicates(points, "path")
    return points


def _validate_profile(profile: Any) -> List[List[float]]:
    if not isinstance(profile, (list, tuple)) or len(profile) < 2:
        raise HandlerError(
            "revolve profile needs at least 2 [radius, height] points, got %r" % (profile,),
            hint="e.g. profile=[[0.5, 0], [0.3, 1]]",
        )
    if len(profile) > MAX_PROFILE_POINTS:
        raise HandlerError(
            "profile has %d points, over the %d-point limit"
            % (len(profile), MAX_PROFILE_POINTS),
            hint="thin the profile",
        )
    points: List[List[float]] = []
    for i, p in enumerate(profile):
        if (
            not isinstance(p, (list, tuple))
            or len(p) != 2
            or any(not _is_number(v) for v in p)
        ):
            raise HandlerError(
                "profile point %d must be [radius, height], got %r" % (i, p),
                hint="e.g. profile=[[0.5, 0], [0.3, 1]]",
            )
        r, h = float(p[0]), float(p[1])
        if r < 0.0:
            raise HandlerError(
                "profile radius must not be negative, got %r at point %d" % (r, i),
                hint="radius is a distance from the axis - use 0 for a point ON the axis",
            )
        points.append([r, h])
    _refuse_consecutive_duplicates(points, "profile")
    return points


def _validate_sections(sections: Any) -> List[List[List[float]]]:
    if not isinstance(sections, (list, tuple)) or len(sections) < 2:
        raise HandlerError(
            "loft needs at least 2 sections, got %r" % (sections,),
            hint="a loft needs a start and end ring, e.g. "
            "sections=[[[1,0,0],[0,0,1],[-1,0,0]], [[1,2,0],[0,2,1],[-1,2,0]]]",
        )
    if len(sections) > MAX_SECTIONS:
        raise HandlerError(
            "loft has %d sections, over the %d-section limit" % (len(sections), MAX_SECTIONS),
            hint="thin the section list",
        )
    rings: List[List[List[float]]] = []
    first_len: Optional[int] = None
    for si, ring in enumerate(sections):
        if not isinstance(ring, (list, tuple)) or not (
            MIN_RING_POINTS <= len(ring) <= MAX_RING_POINTS
        ):
            raise HandlerError(
                "section %d has %d ring points, need between %d and %d"
                % (si, len(ring) if isinstance(ring, (list, tuple)) else 0,
                   MIN_RING_POINTS, MAX_RING_POINTS),
                hint="each section is a closed ring of points, e.g. a triangle needs 3",
            )
        points = [_validate_point3(p, "section %d point" % si) for p in ring]
        _refuse_consecutive_duplicates(points, "section %d" % si, wrap=True)
        if first_len is None:
            first_len = len(points)
        elif len(points) != first_len:
            raise HandlerError(
                "section %d has %d ring points, section 0 has %d - every ring "
                "needs the same point count" % (si, len(points), first_len),
                hint="loft interpolates ring point i to ring point i across sections",
            )
        rings.append(points)
    return rings


def _validate_sweep(params: Dict[str, Any]) -> Dict[str, Any]:
    _refuse_foreign_keys(params, "sweep")
    if "path" not in params:
        raise HandlerError(
            "sweep requires 'path'",
            hint="e.g. path=[[0, 0, 0], [0, 1, 0], [0, 2, 0.5]]",
        )
    path = _validate_path(params["path"])
    width = parse_ramp(params.get("width", 1.0), "width")

    twist = params.get("twist")
    if twist is not None:
        if not _is_number(twist):
            raise HandlerError(
                "twist must be a number of degrees, got %r" % (twist,),
                hint="twist is a single scalar - Maya's sweep node has no twist "
                "ramp - e.g. twist=90",
            )
        twist = float(twist)

    profile_sides = params.get("profile_sides")
    if profile_sides is not None:
        if (
            isinstance(profile_sides, bool)
            or not isinstance(profile_sides, int)
            or profile_sides < 3
        ):
            raise HandlerError(
                "profile_sides must be a whole number of at least 3, got %r" % (profile_sides,),
                hint="omit profile_sides for a circular cross-section, or use e.g. 4 for a square tube",
            )
        # #768 review IMPORTANT 3: the MCP surface caps this at 64 (le=64 in
        # the tool schema), but a handler must not depend on the surface for
        # its own limits (#764's lesson - a param validated only at the
        # edge is not validated). MAX_PROFILE_SIDES matches that surface
        # limit exactly - the two are meant to agree, not merely coincide.
        if profile_sides > MAX_PROFILE_SIDES:
            raise HandlerError(
                "profile_sides %d exceeds the maximum of %d"
                % (profile_sides, MAX_PROFILE_SIDES),
                hint="MAX_PROFILE_SIDES=%d bounds a sweep's cross-section - lower profile_sides"
                % MAX_PROFILE_SIDES,
            )

    spec: Dict[str, Any] = {
        "kind": "sweep",
        "cap_ends": _validate_cap_ends(params.get("cap_ends", True)),
        "resolution": _validate_resolution(params.get("resolution"), _SWEEP_DEFAULT_RESOLUTION),
        "path": path,
        "width": width,
        "twist": twist,
        "profile_sides": profile_sides,
    }
    if "name" in params:
        spec["name"] = params["name"]
    return spec


def _validate_revolve(params: Dict[str, Any]) -> Dict[str, Any]:
    _refuse_foreign_keys(params, "revolve")
    if "profile" not in params:
        raise HandlerError(
            "revolve requires 'profile'",
            hint="e.g. profile=[[0.5, 0], [0.3, 1]]",
        )
    profile = _validate_profile(params["profile"])

    degrees = params.get("degrees", 360.0)
    if not _is_number(degrees) or not (0.0 < float(degrees) <= 360.0):
        raise HandlerError(
            "degrees must be a number in (0, 360], got %r" % (degrees,),
            hint="degrees=360 for a full revolve, or a smaller arc for a partial one",
        )

    spec: Dict[str, Any] = {
        "kind": "revolve",
        "cap_ends": _validate_cap_ends(params.get("cap_ends", True)),
        "resolution": _validate_resolution(
            params.get("resolution"), _REVOLVE_LOFT_DEFAULT_RESOLUTION
        ),
        "profile": profile,
        "degrees": float(degrees),
        "axis": _validate_axis(params.get("axis", "y")),
    }
    if "name" in params:
        spec["name"] = params["name"]
    return spec


def _validate_loft(params: Dict[str, Any]) -> Dict[str, Any]:
    _refuse_foreign_keys(params, "loft")
    if "sections" not in params:
        raise HandlerError(
            "loft requires 'sections'",
            hint="e.g. sections=[[[1,0,0],...ring...], [[1,2,0],...ring...]]",
        )
    spec: Dict[str, Any] = {
        "kind": "loft",
        "cap_ends": _validate_cap_ends(params.get("cap_ends", True)),
        "resolution": _validate_resolution(
            params.get("resolution"), _REVOLVE_LOFT_DEFAULT_RESOLUTION
        ),
        "sections": _validate_sections(params["sections"]),
    }
    if "name" in params:
        spec["name"] = params["name"]
    return spec


def validate_spec(params: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a `create_curve_form` call into the shape every other
    function in this module (and Task 3's handler) relies on.

    `None`-valued keys are dropped FIRST: the MCP server sends every declared
    param on every call, `None` for whichever ones the caller left unset, and
    `None` must read as "absent" so defaults apply - never as an explicit
    request for a null path or a zero-stop ramp.
    """
    params = {k: v for k, v in params.items() if v is not None}
    kind = params.get("kind")
    if kind not in KINDS:
        raise HandlerError(
            "kind must be one of %s, got %r" % (", ".join(repr(k) for k in KINDS), kind),
            hint="sweep extrudes a profile along a path; revolve spins a profile "
            "around an axis; loft blends between sections",
        )
    if kind == "sweep":
        return _validate_sweep(params)
    if kind == "revolve":
        return _validate_revolve(params)
    return _validate_loft(params)


def predicted_faces(spec: Dict[str, Any]) -> int:
    """Face count the tessellation in `spec["resolution"]` will produce.

    `along * around` quad faces plus 2 n-gon caps when `cap_ends` is set,
    for revolve and loft. Refused over MAX_PRIMITIVE_FACES for the same
    reason modeling.py bounds `divisions`: a wedged Maya main thread has no
    exit but killing the process.

    A sweep bills differently (#768 review IMPORTANT 3): its cross-section
    is `profile_sides` when given (an explicit n-gon profile), not
    `resolution["around"]` - `_build_sweep` only falls back to `around` when
    `profile_sides` is omitted (see its docstring). Billing a sweep by
    `around` alone would silently under-count whenever a caller asks for a
    fine profile (`profile_sides` up to MAX_PROFILE_SIDES=64) on a coarse
    `around` resolution, so the ring width used here is
    `max(around, profile_sides or 0)`.

    For a spec that came from `validate_spec`, this branch is unreachable:
    `MAX_ALONG * max(MAX_AROUND, MAX_PROFILE_SIDES) + 2 = 131,074`, far under
    MAX_PRIMITIVE_FACES (1,000,000), because `_validate_resolution` and the
    profile_sides cap already bound every factor here. It stays as a guard
    for any spec built by a future caller that skips `validate_spec` and
    hands a resolution straight in.
    """
    resolution = spec["resolution"]
    along = resolution["along"]
    around = resolution["around"]
    if spec.get("kind") == "sweep":
        around = max(around, spec.get("profile_sides") or 0)
    faces = along * around + (2 if spec.get("cap_ends") else 0)
    if faces > MAX_PRIMITIVE_FACES:
        raise HandlerError(
            "resolution %dx%d would build about %d faces, over the %d-face limit"
            % (along, around, faces, MAX_PRIMITIVE_FACES),
            hint="lower `resolution` - along x around is the face bill",
        )
    return faces


def _point_extent(points: Sequence[Sequence[float]]) -> float:
    """Widest single-axis span across a flat list of `[x, y, z]` points."""
    if not points:
        return 0.0
    spans = (
        max(p[i] for p in points) - min(p[i] for p in points) for i in range(3)
    )
    return max(spans)


def form_size(spec: Dict[str, Any]) -> float:
    """Largest authored extent - the scale a deviation gets judged against.

    "The wobble is 0.02" means nothing on its own; "0.02 against a 4-unit
    form" does. For a sweep the swept surface can be WIDER than the spine's
    own bounding box (a fat tube along a short path), so the max ramp width
    is a candidate for the largest extent too, not just the path.
    """
    kind = spec["kind"]
    if kind == "sweep":
        extent = _point_extent(spec["path"])
        max_width = max(v for _, v in spec["width"])
        return max(extent, max_width)
    if kind == "revolve":
        profile = spec["profile"]
        max_radius = max(r for r, _ in profile)
        heights = [h for _, h in profile]
        height_span = max(heights) - min(heights)
        return max(2.0 * max_radius, height_span)
    points = [p for ring in spec["sections"] for p in ring]
    return _point_extent(points)


def _revolve_point(r: float, h: float, theta: float, axis: str) -> List[float]:
    c, s = math.cos(theta), math.sin(theta)
    if axis == "x":
        return [h, r * c, r * s]
    if axis == "z":
        return [r * c, r * s, h]
    return [r * c, h, r * s]  # axis == "y"


def _stations_revolve(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    degrees, axis = spec["degrees"], spec["axis"]
    stations = []
    for pi, (r, h) in enumerate(spec["profile"]):
        for i in range(_REVOLVE_STATION_ANGLES):
            theta_deg = degrees * i / _REVOLVE_STATION_ANGLES
            point = _revolve_point(r, h, math.radians(theta_deg), axis)
            stations.append({
                "label": "revolve profile[%d]@%.1fdeg" % (pi, theta_deg),
                "point": point,
                "expected": [0.0, 0.0],
            })
    return stations


def _stations_loft(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    stations = []
    for si, ring in enumerate(spec["sections"]):
        for ri, point in enumerate(ring):
            stations.append({
                "label": "loft section[%d] ring[%d]" % (si, ri),
                "point": list(point),
                "expected": [0.0, 0.0],
            })
    return stations


def _stations_sweep(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    path = spec["path"]
    width = spec["width"]
    sides = spec.get("profile_sides")
    cap_ends = spec["cap_ends"]
    t_params = chord_params(path)
    last = len(path) - 1
    stations = []
    for i, point in enumerate(path):
        # The cap plane passes through the end points themselves, so their
        # closest-point-to-surface distance is ~0 regardless of width - a
        # false failure, not a real one. Skip them when there IS a cap.
        if cap_ends and (i == 0 or i == last):
            continue
        w = ramp_value(width, t_params[i])
        half = w / 2.0
        if sides:
            lo, hi = half * math.cos(math.pi / sides), half
        else:
            lo = hi = half
        stations.append({
            "label": "sweep path[%d]" % i,
            "point": list(point),
            "expected": [lo, hi],
        })
    return stations


def station_expectations(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Points the finished mesh's surface must pass within `expected` of.

    See each `_stations_*` helper's rule; the shared shape is
    `{"label": str, "point": [x, y, z], "expected": [lo, hi]}` so Task 3 can
    measure the same way regardless of which curve kind authored the form.
    """
    kind = spec["kind"]
    if kind == "sweep":
        return _stations_sweep(spec)
    if kind == "revolve":
        return _stations_revolve(spec)
    return _stations_loft(spec)
