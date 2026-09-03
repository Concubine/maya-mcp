"""Pure placement math for maya_array. No Maya, by design.

Every number an array produces - where copy 7 of a 12-tooth gear sits, how much
smaller rib 5 is than rib 4, whether a mirrored mesh ended up inside-out - is
computed here and can be checked without a running Maya. The handler that calls
this module is responsible only for driving cmds correctly.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence, Tuple

from ..dispatcher import HandlerError, refuse_inert

MODES = ("mirror", "radial", "linear")
AXES = ("x", "y", "z")

# What each mode actually READS, taken from array.py's own source: `_mirror`
# reads axis and pivot, `_radial` reads count/axis/center/angle, `_linear`
# reads count/offset/step_rotate/step_scale. Everything else in ARRAY_KEYS
# (name, mode, name_prefix, group_name) is common to all three and never
# mode-specific.
MODE_PARAMS = {
    "mirror": ("axis", "pivot"),
    "radial": ("angle", "axis", "center", "count"),
    "linear": ("count", "offset", "step_rotate", "step_scale"),
}

# The union: every key that belongs to SOME mode and therefore can be
# foreign to another. Sorted so the offender named is deterministic - two
# foreign params must not refuse differently run to run under dict order.
_MODE_ONLY_PARAMS = sorted({k for keys in MODE_PARAMS.values() for k in keys})

# Why the mode drops it, in terms of what the mode does. #797's probe found
# NOTHING on the wrong mode was even validated: `center=[1, 2]` (two
# numbers), `angle=720` and `offset="garbage"` all passed through a mirror
# call untouched, because `_mirror` never looks at any of them.
_MODE_DOES = {
    "mirror": "a mirror is exactly one reflected image, and the reflection is "
              "fully determined by the plane - there is nothing here to count, "
              "space or step",
    "radial": "a ring is placed by rotation alone: the source's existing "
              "distance from `center` IS the radius, and every copy is that "
              "same source turned about the axis",
    "linear": "a run is placed by repeating one offset, so it has no axis to "
              "turn about and no centre to turn around",
}

# Every copy is a real duplicated mesh on Maya's main thread. Unbounded counts
# wedge the GUI event loop with no way out but killing the process, the same
# hazard modeling.MAX_PRIMITIVE_FACES exists for.
MAX_COUNT = 200

# Below this, a requested arc is treated as a full closed ring rather than an
# arc that happens to end where it started.
_FULL_CIRCLE_EPS = 1e-6


def axis_index(axis: Any) -> int:
    """0/1/2 for 'x'/'y'/'z'."""
    if not isinstance(axis, str) or axis.lower() not in AXES:
        raise HandlerError(
            "axis must be one of %s, got %r" % (", ".join(AXES), axis),
            hint="axis='y' for a ring lying flat in the XZ plane",
        )
    return AXES.index(axis.lower())


def refuse_foreign_params(mode: str, params: Dict[str, Any]) -> None:
    """Refuse a placement param `mode` never reads (#797 rows 2-4). Pure.

    "Passed" is `is not None`: the MCP wrapper sends every key on every call,
    so a present-and-None key is the caller having said nothing, and reading
    presence alone would refuse every call there is.

    One refusal is enough - the caller fixes the call, not the list - but it
    names the first offender in sorted order so the same call always refuses
    the same way.
    """
    read = MODE_PARAMS[mode]
    offenders = [
        key for key in _MODE_ONLY_PARAMS
        if key not in read and params.get(key) is not None
    ]
    if not offenders:
        return
    param = offenders[0]
    readers = [m for m in MODES if param in MODE_PARAMS[m]]
    refuse_inert(
        "array", param, "in %s mode" % mode, _MODE_DOES[mode],
        hint="%s mode reads %s only; %r is read by %s. Drop it, or switch mode."
        % (mode, ", ".join(read), param,
           " and ".join("mode=%r" % m for m in readers)),
    )


def _clean_vec3(value: Any) -> List[float] | None:
    """`value` as three floats, or None if it is not a clean 3-vector.

    None means "do not judge this here": `resolve_vec3` owns the message for a
    malformed vector, and a second validator guessing at one only reports the
    wrong param.
    """
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value):
        return None
    return [float(v) for v in value]


def refuse_zero_linear_offset(params: Dict[str, Any]) -> None:
    """Refuse a linear array whose copies cannot be told apart (#797 row 5).

    Pure. The caller owns the mode guard - this fires only for `mode="linear"`,
    which is why the message names that mode.

    The value-level twin of `radial_angles`' angle=0 refusal below: with a zero
    offset every copy lands exactly on the source. The result reports N names,
    the viewport shows one object, and the coincident duplicates stacked inside
    it cannot be told apart or picked without an outliner.

    But offset is not the only thing that varies per copy. `linear_steps`
    ACCUMULATES `step_rotate` and COMPOUNDS `step_scale`, so a zero offset with
    either of those builds something real and unreachable any other way -
    concentric nested shells, or a stack turning about a shared origin. Those
    copies genuinely differ, so the refusal's reason does not hold and the call
    proceeds. Only the case where nothing at all distinguishes copy i from the
    source is refused; the identity steps ([0,0,0] and [1,1,1], which are what
    `linear_steps` defaults to) distinguish nothing and do not rescue it.

    An ABSENT offset is left alone - `resolve_vec3` refuses that as missing,
    which is a different mistake with a different fix.
    """
    offset = _clean_vec3(params.get("offset"))
    if offset is None or any(v != 0.0 for v in offset):
        return

    step_rotate = params.get("step_rotate")
    if step_rotate is not None:
        rotate = _clean_vec3(step_rotate)
        if rotate is None or any(v != 0.0 for v in rotate):
            return
    step_scale = params.get("step_scale")
    if step_scale is not None:
        scale = _clean_vec3(step_scale)
        if scale is None or any(v != 1.0 for v in scale):
            return

    refuse_inert(
        "array", "offset", "in linear mode at [0, 0, 0]",
        "with no step_rotate and no step_scale, a zero step places every copy "
        "exactly on the source - coincident geometry that looks identical to "
        "the array never having run (radial refuses angle=0 for the same "
        "reason)",
        hint="offset is the world displacement BETWEEN consecutive copies, "
        "e.g. offset=[0, 2, 0] to stack a run 2 units apart. A zero offset IS "
        "meaningful alongside a step_scale (concentric shells) or a "
        "step_rotate (a turning stack) - it is only this call, where nothing "
        "varies per copy, that has no result to show.",
    )


def resolve_count(count: Any) -> int:
    """Total elements in the finished array, INCLUDING the source."""
    if count is None:
        # #797: the wrapper defaults count to None now, so None means the
        # caller never named one. "must be a whole number, got None" sent
        # them hunting for a type error in a value they never wrote.
        raise HandlerError(
            "missing required param 'count'",
            hint="radial and linear need a count - the TOTAL number of "
            "elements including the source, e.g. count=12. mirror takes none: "
            "it makes exactly one copy.",
        )
    if isinstance(count, bool) or not isinstance(count, int):
        raise HandlerError(
            "count must be a whole number, got %r" % (count,),
            hint="count is the total number of elements including the source, e.g. 12",
        )
    if count < 2:
        raise HandlerError(
            "count must be at least 2, got %d" % count,
            hint=(
                "count includes the source, so count=2 makes one copy; "
                "count=1 would create nothing"
            ),
        )
    if count > MAX_COUNT:
        raise HandlerError(
            "count %d exceeds the maximum of %d" % (count, MAX_COUNT),
            hint="each element is a real duplicated mesh; build in stages if you need more",
        )
    return count


def resolve_vec3(value: Any, name: str, default: Sequence[float] | None = None) -> List[float]:
    """A 3-float list, or `default` when absent. Rejects bools and wrong lengths."""
    if value is None:
        if default is None:
            raise HandlerError(
                "missing required param %r" % name,
                hint="%s takes three numbers, e.g. %s=[0, 1, 0]" % (name, name),
            )
        return [float(v) for v in default]
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
        or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value)
    ):
        raise HandlerError(
            "%s must be three numbers, got %r" % (name, value),
            hint="e.g. %s=[0, 1, 0]" % name,
        )
    return [float(v) for v in value]


def radial_angles(count: int, angle: float = 360.0) -> List[float]:
    """Rotation in degrees for copies 1..count-1 of a radial array.

    A full ring divides by count, because the seam is where the source already
    sits and a copy there would be coincident geometry. Any other arc divides by
    count-1, so the first and last elements land on the arc's endpoints. Both
    readings are right for their case and wrong for the other, so the rule is
    explicit here and directly tested.
    """
    count = resolve_count(count)
    if float(angle) == 0.0:
        raise HandlerError(
            "angle must not be 0 - every copy would land exactly on the source",
            hint="use angle=360 for a full ring, or a nonzero arc for a partial one",
        )
    closed = abs(abs(float(angle)) - 360.0) < _FULL_CIRCLE_EPS
    step = float(angle) / (count if closed else (count - 1))
    return [step * i for i in range(1, count)]


def rotate_point(
    point: Sequence[float], axis: str, degrees: float, center: Sequence[float]
) -> List[float]:
    """`point` rotated about `axis` through `center`, right-hand rule."""
    idx = axis_index(axis)
    rad = math.radians(float(degrees))
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    px, py, pz = (float(point[i]) - float(center[i]) for i in range(3))
    if idx == 0:
        rx, ry, rz = px, py * cos_a - pz * sin_a, py * sin_a + pz * cos_a
    elif idx == 1:
        rx, ry, rz = px * cos_a + pz * sin_a, py, -px * sin_a + pz * cos_a
    else:
        rx, ry, rz = px * cos_a - py * sin_a, px * sin_a + py * cos_a, pz
    return [rx + float(center[0]), ry + float(center[1]), rz + float(center[2])]


def linear_steps(
    count: int,
    offset: Sequence[float],
    step_rotate: Sequence[float],
    step_scale: Sequence[float],
) -> List[Dict[str, List[float]]]:
    """Per-copy deltas for copies 1..count-1 of a linear array.

    Translation and rotation accumulate; scale COMPOUNDS. Compounding gives a
    geometric progression, which is what a tapering run of ribs actually looks
    like - accumulating instead reaches zero partway down the run and then
    inverts, producing a mesh turned inside out rather than a small one.
    """
    count = resolve_count(count)
    offset = resolve_vec3(offset, "offset")
    step_rotate = resolve_vec3(step_rotate, "step_rotate", [0.0, 0.0, 0.0])
    step_scale = resolve_vec3(step_scale, "step_scale", [1.0, 1.0, 1.0])
    if any(s <= 0.0 for s in step_scale):
        raise HandlerError(
            "step_scale must be positive, got %r" % (step_scale,),
            hint="step_scale is a per-copy multiplier: 0.9 shrinks, 1.1 grows, 1.0 holds",
        )
    steps: List[Dict[str, List[float]]] = []
    for i in range(1, count):
        steps.append(
            {
                "translate": [offset[a] * i for a in range(3)],
                "rotate": [step_rotate[a] * i for a in range(3)],
                "scale": [step_scale[a] ** i for a in range(3)],
            }
        )
    return steps


def mirror_bbox(
    bbox_min: Sequence[float],
    bbox_max: Sequence[float],
    axis: str,
    pivot: Sequence[float],
) -> Tuple[List[float], List[float]]:
    """The world bounding box a mirrored copy should occupy.

    Reflection negates the axis, which SWAPS min and max on it. This is the
    prediction the live gate checks Maya against, and it is bbox-based on
    purpose: a bounding box is rotation-agnostic, so it tests the reflection
    itself rather than any particular decomposition of it.
    """
    idx = axis_index(axis)
    out_min = [float(v) for v in bbox_min]
    out_max = [float(v) for v in bbox_max]
    p = float(pivot[idx])
    out_min[idx], out_max[idx] = 2.0 * p - float(bbox_max[idx]), 2.0 * p - float(bbox_min[idx])
    return out_min, out_max


def signed_volume(points: Sequence[Sequence[float]], triangles: Sequence[Sequence[int]]) -> float:
    """Signed volume of a closed triangulated mesh.

    Positive for consistent outward winding, negative when the winding is
    inverted, and the magnitude is the real volume. This is the instrument for
    the mirror trap: negative scale flips face winding, which renders as a black
    or hollow object that looks exactly like a lighting failure and is not one.
    """
    total = 0.0
    for tri in triangles:
        a, b, c = (points[i] for i in tri)
        cross = (
            b[1] * c[2] - b[2] * c[1],
            b[2] * c[0] - b[0] * c[2],
            b[0] * c[1] - b[1] * c[0],
        )
        total += a[0] * cross[0] + a[1] * cross[1] + a[2] * cross[2]
    return total / 6.0
