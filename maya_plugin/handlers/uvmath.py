"""Atlas patch arithmetic. No Maya import: every number here is testable headless.

An atlas is a cols x rows grid over the 0..1 UV square. A patch is one cell of
that grid, optionally inset by a margin so bilinear filtering cannot drag a
neighbouring patch's pixels across the seam - the classic atlas bleed, which
shows up as a thin wrong-coloured line along an edge and is invisible until
something is far away.

INDEX CONVENTION: patches are numbered row-major FROM THE TOP-LEFT, the way the
atlas PNG reads in an image viewer. UV v increases upward, so index 0 is the
patch with the highest v. Getting this backwards mirrors the whole atlas
vertically, which is why it is stated here and tested.
"""

from __future__ import annotations

from typing import Any, Sequence, Tuple

from ..dispatcher import HandlerError

Rect = Tuple[float, float, float, float]


def _grid(cols: Any, rows: Any) -> Tuple[int, int]:
    for label, value in (("cols", cols), ("rows", rows)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise HandlerError(
                "%s must be a positive integer, got %r" % (label, value),
                hint="a 4x4 atlas is cols=4, rows=4",
            )
    return int(cols), int(rows)


def patch_rect(cols: Any, rows: Any, col: Any, row: Any, margin: float = 0.0) -> Rect:
    """The UV rectangle of one atlas patch, as (u_min, v_min, u_max, v_max)."""
    cols, rows = _grid(cols, rows)
    for label, value, limit in (("col", col, cols), ("row", row, rows)):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < limit:
            raise HandlerError(
                "%s must be an integer in 0..%d, got %r" % (label, limit - 1, value),
                hint="the grid is %dx%d" % (cols, rows),
            )
    if isinstance(margin, bool) or not isinstance(margin, (int, float)):
        raise HandlerError("margin must be a number, got %r" % (margin,))
    if not 0.0 <= float(margin) < 0.5:
        raise HandlerError(
            "margin must be in 0.0..0.5 (exclusive), got %r" % (margin,),
            hint="margin is a FRACTION of the patch, so 0.5 would erase it; "
                 "0.02-0.05 is enough to stop filtering bleed",
        )

    w, h = 1.0 / cols, 1.0 / rows
    inset_u, inset_v = w * float(margin), h * float(margin)
    u0 = col * w + inset_u
    # row 0 is the TOP row, so it occupies the highest v band.
    v0 = (rows - 1 - row) * h + inset_v
    return (u0, v0, u0 + w - 2 * inset_u, v0 + h - 2 * inset_v)


def resolve_cell(patch: Any, cols: Any, rows: Any) -> Tuple[int, int]:
    """Accept either a flat index or an explicit [col, row]; return (col, row)."""
    cols, rows = _grid(cols, rows)
    if isinstance(patch, (list, tuple)):
        if len(patch) != 2:
            raise HandlerError(
                "patch as a pair must be [col, row], got %r" % (patch,),
                hint="or pass a single integer index counted from the top-left",
            )
        col, row = patch
        if any(isinstance(v, bool) or not isinstance(v, int) for v in (col, row)):
            raise HandlerError("patch [col, row] must be integers, got %r" % (patch,))
        if not (0 <= col < cols and 0 <= row < rows):
            raise HandlerError(
                "patch %r is outside the %dx%d grid" % (patch, cols, rows)
            )
        return int(col), int(row)
    if isinstance(patch, bool) or not isinstance(patch, int):
        raise HandlerError(
            "patch must be an integer index or [col, row], got %r" % (patch,),
            hint="index 0 is the TOP-LEFT patch and counts along the row first",
        )
    if not 0 <= patch < cols * rows:
        raise HandlerError(
            "patch index %d is outside a %dx%d atlas (0..%d)"
            % (patch, cols, rows, cols * rows - 1)
        )
    return int(patch % cols), int(patch // cols)


def centre_in_rect(
    bounds: Sequence[float], rect: Sequence[float]
) -> Tuple[float, float, float, float]:
    """(pivot_u, pivot_v, delta_u, delta_v) to centre `bounds` inside `rect`.

    Used by world-scale packing, where the scale factor is decided by real-world
    size rather than by making the object fill the patch. Scale about the
    object's own UV centre with the returned pivot, then move by the returned
    delta, and the object sits centred in its patch at whatever density the
    caller asked for.
    """
    u0, v0, u1, v1 = (float(q) for q in bounds)
    centre_u, centre_v = (u0 + u1) / 2.0, (v0 + v1) / 2.0
    rect_u = (float(rect[0]) + float(rect[2])) / 2.0
    rect_v = (float(rect[1]) + float(rect[3])) / 2.0
    return (centre_u, centre_v, rect_u - centre_u, rect_v - centre_v)


def fits_in_rect(bounds: Sequence[float], rect: Sequence[float], scale: float) -> bool:
    """Would `bounds`, scaled by `scale` about its centre, stay inside `rect`?

    False means the piece is physically too big for the density asked of it, and
    its UVs would spill into a neighbouring atlas patch - which reads as another
    material's pixels appearing on the piece.
    """
    u0, v0, u1, v1 = (float(q) for q in bounds)
    half_u = (u1 - u0) * float(scale) / 2.0
    half_v = (v1 - v0) * float(scale) / 2.0
    rect_half_u = (float(rect[2]) - float(rect[0])) / 2.0
    rect_half_v = (float(rect[3]) - float(rect[1])) / 2.0
    tol = 1e-6
    return half_u <= rect_half_u + tol and half_v <= rect_half_v + tol


def fold_transform(
    src: Sequence[float], dst: Sequence[float]
) -> Tuple[float, float, float, float, float, float]:
    """(pivot_u, pivot_v, scale_u, scale_v, delta_u, delta_v) mapping box `src`
    onto box `dst` - scale about `src`'s minimum corner, then move.

    Unlike fit_transform this takes an arbitrary source box rather than the unit
    square, which is what a boolean cutter needs: its UVs are wherever the
    caller left them, and they have to end up inside the chunk's atlas patch
    (#638). The two triples are exactly one polyEditUV scale followed by one
    relative move.

    A degenerate source axis (every UV on one line) cannot be scaled onto a
    range, so it is CENTRED in the destination instead of collapsing to its
    corner - the same pixel either way, but the one a reader would predict.
    """
    su0, sv0, su1, sv1 = (float(q) for q in src)
    du0, dv0, du1, dv1 = (float(q) for q in dst)
    tol = 1e-12
    scale_u = (du1 - du0) / (su1 - su0) if abs(su1 - su0) > tol else 1.0
    scale_v = (dv1 - dv0) / (sv1 - sv0) if abs(sv1 - sv0) > tol else 1.0
    delta_u = (du0 if abs(su1 - su0) > tol else (du0 + du1) / 2.0) - su0
    delta_v = (dv0 if abs(sv1 - sv0) > tol else (dv0 + dv1) / 2.0) - sv0
    return (su0, sv0, scale_u, scale_v, delta_u, delta_v)


def is_identity_fold(
    fold: Sequence[float], tol: float = 1e-6
) -> bool:
    """Would applying `fold` leave every UV where it is (within `tol`)?

    Worth asking before touching a mesh: a no-op polyEditUV still dirties the
    scene and still costs a full UV rewrite on a dense mesh.
    """
    _, _, scale_u, scale_v, delta_u, delta_v = (float(q) for q in fold)
    return (
        abs(scale_u - 1.0) <= tol and abs(scale_v - 1.0) <= tol
        and abs(delta_u) <= tol and abs(delta_v) <= tol
    )


def rect_contains(
    inner: Sequence[float], outer: Sequence[float], tol: float = 1e-4
) -> bool:
    """Does `outer` contain `inner`, allowing `tol` of slop on every side?"""
    iu0, iv0, iu1, iv1 = (float(q) for q in inner)
    ou0, ov0, ou1, ov1 = (float(q) for q in outer)
    return (
        iu0 >= ou0 - tol and iv0 >= ov0 - tol
        and iu1 <= ou1 + tol and iv1 <= ov1 + tol
    )


def fit_transform(rect: Sequence[float]) -> Tuple[float, float, float, float]:
    """(scale_u, scale_v, offset_u, offset_v) mapping the unit square onto rect.

    Applied as u' = u * scale_u + offset_u, which is exactly a polyEditUV scale
    about pivot (0, 0) followed by a relative move - so the caller can hand
    these four numbers straight to Maya.
    """
    u0, v0, u1, v1 = (float(q) for q in rect)
    return (u1 - u0, v1 - v0, u0, v0)
