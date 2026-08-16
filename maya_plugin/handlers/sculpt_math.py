"""Pure sculpt math: value noise (golem-run displace port) + falloffs."""

from __future__ import annotations

import math


def vnoise(x: float, y: float, z: float) -> float:
    """Cheap deterministic 3D value noise, trilinear interpolation, [0,1]."""

    def h(ix: int, iy: int, iz: int) -> float:
        n = (ix * 73856093) ^ (iy * 19349663) ^ (iz * 83492791)
        n = (n ^ (n >> 13)) * 1274126177
        return ((n ^ (n >> 16)) & 0xFFFF) / 65535.0

    ix, iy, iz = math.floor(x), math.floor(y), math.floor(z)
    fx, fy, fz = x - ix, y - iy, z - iz
    ix, iy, iz = int(ix), int(iy), int(iz)

    def s(t: float) -> float:
        return t * t * (3 - 2 * t)

    fx, fy, fz = s(fx), s(fy), s(fz)
    c = [[[h(ix + a, iy + b, iz + cc) for cc in (0, 1)] for b in (0, 1)] for a in (0, 1)]

    def lerp(a: float, b: float, t: float) -> float:
        return a + (b - a) * t

    return lerp(
        lerp(lerp(c[0][0][0], c[0][0][1], fz), lerp(c[0][1][0], c[0][1][1], fz), fy),
        lerp(lerp(c[1][0][0], c[1][0][1], fz), lerp(c[1][1][0], c[1][1][1], fz), fy),
        fx,
    )


def fbm(x: float, y: float, z: float, octaves: int = 2) -> float:
    """Signed fractal value noise. Octave 2 with amp 0.45 / lacunarity 2.3 /
    +7 offset reproduces the golem run's two-octave recipe exactly."""
    total, amp, freq, offset = 0.0, 1.0, 1.0, 0.0
    for _ in range(max(1, octaves)):
        total += (vnoise(x * freq + offset, y * freq, z * freq) - 0.5) * 2.0 * amp
        amp *= 0.45
        freq *= 2.3
        offset += 7.0
    return total


def bbox_extent(flat: list) -> float:
    """Diagonal of the bounding box of a flat [x,y,z,x,y,z,...] point list.

    The scale reference a displacement is judged against: "moved 0.0015" means
    nothing on its own, "moved 0.0015 across a 2.1-wide mesh" means the op was
    a no-op. Returns 0.0 for an empty or degenerate list.
    """
    if not flat or len(flat) < 3:
        return 0.0
    lo = [min(flat[i::3]) for i in range(3)]
    hi = [max(flat[i::3]) for i in range(3)]
    return math.sqrt(sum((hi[i] - lo[i]) ** 2 for i in range(3)))


def max_displacement(before: list, after: list) -> float:
    """Largest per-vertex move between two flat [x,y,z,...] lists.

    Returns 0.0 when the lists disagree in length (topology changed under the
    op, so per-vertex comparison is meaningless) - callers treat that as
    "unmeasurable", not as "nothing happened".
    """
    if not before or len(before) != len(after):
        return 0.0
    worst = 0.0
    for i in range(0, len(before), 3):
        dx = after[i] - before[i]
        dy = after[i + 1] - before[i + 1]
        dz = after[i + 2] - before[i + 2]
        d = dx * dx + dy * dy + dz * dz
        if d > worst:
            worst = d
    return math.sqrt(worst)


def falloff_weight(dist: float, radius: float, falloff: str) -> float:
    if radius <= 0.0 or dist >= radius:
        return 0.0
    t = 1.0 - dist / radius
    if falloff == "linear":
        return t
    return t * t * (3 - 2 * t)  # smoothstep
