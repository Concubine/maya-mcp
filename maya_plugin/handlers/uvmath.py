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


def fit_transform(rect: Sequence[float]) -> Tuple[float, float, float, float]:
    """(scale_u, scale_v, offset_u, offset_v) mapping the unit square onto rect.

    Applied as u' = u * scale_u + offset_u, which is exactly a polyEditUV scale
    about pivot (0, 0) followed by a relative move - so the caller can hand
    these four numbers straight to Maya.
    """
    u0, v0, u1, v1 = (float(q) for q in rect)
    return (u1 - u0, v1 - v0, u0, v0)
