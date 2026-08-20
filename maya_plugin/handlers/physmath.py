"""Pure physics-body geometry for #676 author_physics.

Deterministic math over plain point/triangle lists - no Maya, no OpenMaya -
so the headless suite carries every fitting and conversion rule. The
handler (physics.py) is orchestration only.

Volume and COM are tetra-weighted over the closed surface (the
arraymath.signed_volume algorithm, extended with the centroid
accumulation): the COM that ships is the SCULPT's centre of mass,
tessellation-invariant, which a vertex average is not. Collider fitting
happens in the mesh's own principal frame (Jacobi eigen of the vertex
covariance) because the delivered golem's fits are rotated; honesty
(volume_ratio, max_escape) is measured over the actual vertices, never
assumed from the fit.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

# --- classification constants ------------------------------------------------
# Kind selection runs: capsule (elongated, round cross-section, NOT
# box-filling) first, then box-by-fill, then sphere, else box. The fill
# landmarks are geometric, not tuned: a solid box fills 1.0 of its
# principal box, an axis-aligned cylinder pi/4 ~ 0.785, a ball pi/6 ~
# 0.524. BOX_FILL_MIN sits between ball and cylinder. CAPSULE_FILL_MAX
# gates the capsule branch separately, just above the plain-cylinder
# landmark (a real capsule's rounded caps can only fill LESS than a
# flat-ended cylinder, so nothing genuinely capsule-shaped clears ~0.785)
# - #676 Task 6's live gate measured a shape that clears BOTH landmarks on
# golem_C_chest_girdle: a/b=1.69, b/c=1.30 pass the old capsule test, but
# fill=0.934 is a box wearing a capsule's aspect ratio; forcing the
# capsule fit anyway gave volume_ratio 1.13 vs the delivered box's 1.07 -
# worse on both axes. CAPSULE_FILL_MAX=0.85 keeps every real cylinder (the
# unit-test fixture measures fill=0.781, just under the 0.785 landmark)
# while rejecting chest_girdle's 0.934.
#
# CAPSULE_MIN_ELONG measured the same way: the old 1.6 misclassified
# golem_L/R_thigh (a/b 1.38-1.39) and golem_L/R_shin (a/b 1.32) as spheres
# (their a/c 1.32-1.39 sits just under SPHERE_MAX_ANISO), wasting
# volume_ratio 2.9-3.3x where the delivered capsule sits near parity
# (~0.95-1.04x, confirmed by force-fitting a capsule to the same vertices).
# 1.1 sits with comfortable margin below every genuine sphere in the
# delivery (golem_C_head a/b=1.024, golem_L/R_shoulder a/b=1.026) and at
# or below every genuine capsule (thigh/shin above, plus
# golem_C_belly/golem_C_pelvis at 1.19-1.32, both already capsule-shaped
# by fill and roundness) - verified against all 33 delivered chunks, see
# docs/superpowers/plans task-6 report.
SPHERE_MAX_ANISO = 1.4      # a/c at most this to read as "round all over"
CAPSULE_MIN_ELONG = 1.1     # a/b at least this to read as "long"
CAPSULE_MAX_ROUND = 1.5     # b/c at most this to read as "round section"
CAPSULE_FILL_MAX = 0.85     # |mesh| / principal-box volume, capsule ceiling
BOX_FILL_MIN = 0.72         # |mesh| / principal-box volume


def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


def _length(v):
    return math.sqrt(_dot(v, v))


def _unit(v) -> Optional[List[float]]:
    n = _length(v)
    if n < 1e-12:
        return None
    return [c / n for c in v]


def solid_com(points: Sequence[Sequence[float]],
              triangles: Sequence[Sequence[int]],
              eps: float = 1e-12) -> Tuple[float, Optional[List[float]]]:
    """(signed volume, solid centre of mass) of a closed triangulated mesh.

    One pass of origin-tetra accumulation: each triangle spans a tetra with
    the origin, volume dot(a, cross(b, c)) / 6, centroid (0+a+b+c)/4. The
    COM is the volume-weighted centroid sum - the "sculpt's centre of
    mass" the handoff contract ships, NOT a vertex average (which drifts
    with tessellation density) and NOT a bbox centre (#640). When |volume|
    is below eps the division is meaningless and the COM is None - the
    caller decides the fallback and says so.
    """
    total = 0.0
    acc = [0.0, 0.0, 0.0]
    for tri in triangles:
        a, b, c = (points[i] for i in tri)
        v = _dot(a, _cross(b, c)) / 6.0
        total += v
        for k in range(3):
            acc[k] += v * (a[k] + b[k] + c[k]) / 4.0
    if abs(total) < eps:
        return total, None
    return total, [acc[k] / total for k in range(3)]


def open_edge_count(triangles: Sequence[Sequence[int]]) -> int:
    """Edges NOT shared by exactly two triangles; 0 means watertight.

    The detector behind the "signed volume is unreliable" warning: the
    tetra sum is exact only over a closed surface, and this is the closure
    test that costs one dictionary pass instead of a guess.
    """
    counts: Dict[Tuple[int, int], int] = {}
    for tri in triangles:
        for i in range(3):
            lo, hi = tri[i], tri[(i + 1) % 3]
            edge = (lo, hi) if lo < hi else (hi, lo)
            counts[edge] = counts.get(edge, 0) + 1
    return sum(1 for n in counts.values() if n != 2)


def _matmul3(x, y):
    return [[sum(x[i][k] * y[k][j] for k in range(3)) for j in range(3)]
            for i in range(3)]


def eigen_symmetric3(m: Sequence[Sequence[float]],
                     sweeps: int = 24) -> Tuple[List[float], List[List[float]]]:
    """Eigen-decomposition of a symmetric 3x3 by cyclic Jacobi rotations.

    Returns (eigenvalues, eigenvectors as ROW vectors, value[i] belonging
    to vector[i]). Pure Python on purpose - no numpy exists in the plugin
    environment, and 3x3 Jacobi converges in a handful of sweeps. An
    already-diagonal matrix (a cube's isotropic covariance) exits
    immediately with the identity basis - no rotation is ever invented.
    """
    a = [list(row) for row in m]
    v = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    for _ in range(sweeps):
        off = math.sqrt(a[0][1] ** 2 + a[0][2] ** 2 + a[1][2] ** 2)
        if off < 1e-15:
            break
        for p in range(2):
            for q in range(p + 1, 3):
                if abs(a[p][q]) < 1e-18:
                    continue
                theta = 0.5 * math.atan2(2.0 * a[p][q], a[p][p] - a[q][q])
                c, s = math.cos(theta), math.sin(theta)
                g = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
                g[p][p] = c
                g[q][q] = c
                g[p][q] = -s
                g[q][p] = s
                gt = [[g[j][i] for j in range(3)] for i in range(3)]
                a = _matmul3(gt, _matmul3(a, g))
                v = _matmul3(v, g)
    values = [a[0][0], a[1][1], a[2][2]]
    vectors = [[v[0][j], v[1][j], v[2][j]] for j in range(3)]
    return values, vectors


def principal_frame(flat: Sequence[float]) -> Tuple[List[float], List[List[float]]]:
    """(centroid, axes) of a flat [x,y,z,...] cloud.

    Axes are three unit ROW vectors ordered by descending variance,
    sign-canonicalized (each of the first two axes has its
    largest-magnitude component positive) and exactly right-handed
    (axis 2 = cross(axis 0, axis 1)) - the same cloud always yields the
    same frame, which the determinism guarantee in the handler rests on.
    """
    n = len(flat) // 3
    if n == 0:
        raise ValueError("empty point list")
    centroid = [sum(flat[k::3]) / n for k in range(3)]
    cov = [[0.0] * 3 for _ in range(3)]
    for i in range(n):
        d = [flat[3 * i + k] - centroid[k] for k in range(3)]
        for r in range(3):
            for c in range(r, 3):
                cov[r][c] += d[r] * d[c]
    for r in range(3):
        for c in range(r, 3):
            cov[r][c] /= n
            cov[c][r] = cov[r][c]
    values, vectors = eigen_symmetric3(cov)
    order = sorted(range(3), key=lambda k: -values[k])
    axes = [list(vectors[k]) for k in order]
    for ax in axes[:2]:
        m = max(range(3), key=lambda k: abs(ax[k]))
        if ax[m] < 0:
            for k in range(3):
                ax[k] = -ax[k]
    axes[2] = _cross(axes[0], axes[1])
    return centroid, axes


def _project_extent(flat, origin, axis) -> Tuple[float, float]:
    """(min, max) of the cloud projected on `axis` about `origin`."""
    lo = hi = None
    for i in range(len(flat) // 3):
        t = _dot([flat[3 * i + k] - origin[k] for k in range(3)], axis)
        lo = t if lo is None or t < lo else lo
        hi = t if hi is None or t > hi else hi
    return lo, hi


def classify(half_extents: Sequence[float], fill: float) -> str:
    """One primitive kind from principal half-extents (descending) + fill."""
    a, b, c = half_extents
    b = max(b, 1e-9)
    c = max(c, 1e-9)
    if (a >= CAPSULE_MIN_ELONG * b and b <= CAPSULE_MAX_ROUND * c
            and fill < CAPSULE_FILL_MAX):
        return "capsule"
    if fill >= BOX_FILL_MIN:
        return "box"
    if a <= SPHERE_MAX_ANISO * c:
        return "sphere"
    return "box"


def frame_to_euler_xyz_deg(axes: Sequence[Sequence[float]]) -> List[float]:
    """XYZ euler (DEGREES, #636) of the rotation whose COLUMNS are `axes`.

    Convention pinned by tests: R = Rz(rz) @ Ry(ry) @ Rx(rx), with
    R[i][j] = axes[j][i]. Gimbal fallback (|R20| ~ 1) zeroes rz.
    """
    r20 = axes[0][2]
    if abs(r20) > 1.0 - 1e-9:
        ry = math.degrees(math.asin(-max(-1.0, min(1.0, r20))))
        rx = math.degrees(math.atan2(-axes[1][0], axes[1][1]))
        rz = 0.0
    else:
        ry = math.degrees(math.asin(-r20))
        rx = math.degrees(math.atan2(axes[1][2], axes[2][2]))
        rz = math.degrees(math.atan2(axes[0][1], axes[0][0]))
    return [rx, ry, rz]


def fit_collider(flat: Sequence[float],
                 mesh_signed_volume: float) -> Dict[str, Any]:
    """Fit ONE primitive (box/sphere/capsule) in the cloud's principal frame.

    Returns every key always (None where a kind has no use for it):
      kind, centre (WORLD), rotation_deg (XYZ euler of the frame),
      size (box: full extents, descending), radius (sphere/capsule),
      height (capsule: cylinder segment EXCLUDING the two cap radii),
      axis (capsule: world unit vector of the long principal axis),
      volume_ratio (primitive / |mesh|; None when the mesh volume is
      unmeasurable), max_escape (MEASURED furthest vertex outside the
      primitive - box and sphere contain by construction, a capsule's end
      corners can poke past the hemispherical caps and the number says by
      how much).
    """
    centroid, axes = principal_frame(flat)
    spans = [_project_extent(flat, centroid, axes[k]) for k in range(3)]
    order = sorted(range(3), key=lambda k: -(spans[k][1] - spans[k][0]))
    axes = [axes[k] for k in order]
    axes[2] = _cross(axes[0], axes[1])      # right-handed after the reorder
    spans = [spans[k] for k in order]
    spans[2] = _project_extent(flat, centroid, axes[2])
    half = [(s[1] - s[0]) / 2.0 for s in spans]
    mid = [(s[1] + s[0]) / 2.0 for s in spans]
    centre = [centroid[k] + sum(mid[a] * axes[a][k] for a in range(3))
              for k in range(3)]
    box_vol = 8.0 * max(half[0], 1e-12) * max(half[1], 1e-12) * max(half[2], 1e-12)
    volume = abs(mesh_signed_volume)
    fill = volume / box_vol if volume > 1e-30 else 0.0
    kind = classify(half, fill)
    out: Dict[str, Any] = {
        "kind": kind,
        "centre": centre,
        "rotation_deg": frame_to_euler_xyz_deg(axes),
        "size": None, "radius": None, "height": None, "axis": None,
        "volume_ratio": None,
        "max_escape": 0.0,
    }
    if kind == "box":
        out["size"] = [2.0 * h for h in half]
        prim_vol = box_vol
    elif kind == "sphere":
        radius = 0.0
        for i in range(len(flat) // 3):
            d = [flat[3 * i + k] - centre[k] for k in range(3)]
            radius = max(radius, _length(d))
        out["radius"] = radius
        prim_vol = 4.0 / 3.0 * math.pi * radius ** 3
    else:
        axis = axes[0]
        radius = 0.0
        for i in range(len(flat) // 3):
            d = [flat[3 * i + k] - centre[k] for k in range(3)]
            t = _dot(d, axis)
            radius = max(radius, _length(
                [d[k] - t * axis[k] for k in range(3)]))
        half_cyl = max(0.0, half[0] - radius)
        escape = 0.0
        for i in range(len(flat) // 3):
            d = [flat[3 * i + k] - centre[k] for k in range(3)]
            t = max(-half_cyl, min(half_cyl, _dot(d, axis)))
            gap = _length([d[k] - t * axis[k] for k in range(3)]) - radius
            escape = max(escape, gap)
        out["axis"] = axis
        out["radius"] = radius
        out["height"] = 2.0 * half_cyl
        out["max_escape"] = escape
        prim_vol = (math.pi * radius * radius * (2.0 * half_cyl)
                    + 4.0 / 3.0 * math.pi * radius ** 3)
    if volume > 1e-30:
        out["volume_ratio"] = prim_vol / volume
    return out


def cone_from_hinge(hinge_axis: Sequence[float],
                    range_deg: Sequence[float],
                    twist_deg: Sequence[float] = (0.0, 0.0)) -> Dict[str, Any]:
    """The handoff's swing/twist cone from hinge currency.

    The knee rule, verbatim from the motion handoff: axis along the hinge,
    swing2Limit = 0, swing1Limit covering the flex arc, twist locked near
    zero, and the arc placed so neutral sits at the extreme.
    swing_centre_deg IS the placement: rotate the joint frame by it about
    `axis` and the symmetric +-swing1 cone covers exactly [lo, hi]. A
    one-sided range (the knee's (0, 110)) then has neutral on the cone's
    edge, and no-hyperextension is the range's own asymmetry, not a
    special case. swing_axis is the deterministic perpendicular: the world
    basis vector least aligned with the hinge, Gram-Schmidt'd against it.
    """
    axis = _unit(list(hinge_axis))
    if axis is None:
        raise ValueError("hinge_axis must not be the zero vector")
    lo, hi = float(range_deg[0]), float(range_deg[1])
    basis = min(([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]),
                key=lambda e: abs(_dot(e, axis)))
    swing_axis = _unit(_sub(basis, [c * _dot(basis, axis) for c in axis]))
    return {
        "axis": axis,
        "swing_axis": swing_axis,
        "swing1": (hi - lo) / 2.0,
        "swing2": 0.0,
        "twist_lo": float(twist_deg[0]),
        "twist_hi": float(twist_deg[1]),
        "swing_centre_deg": (lo + hi) / 2.0,
    }
