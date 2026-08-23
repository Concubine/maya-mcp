"""#743: pure metrics for the vacuum drifter fixture.

No Maya, no network, no I/O - so both the live gate and the consumer gate
compute the SAME numbers the same way. #737's check_poses was blind to a
3.2 m error because it re-composed poses the way our own reader does; a
metric shared between producer and consumer cannot drift like that.

Every metric is FRAME-INVARIANT: a distance between two points on the same
mesh, so it survives any rigid or mirrored transform and admits no
coordinate-convention argument. Height is deliberately absent - it agreed to
2 micrometres on three of the golem's poses while the arms were metres out.
"""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple

Point = Sequence[float]


def distance(a: Point, b: Point) -> float:
    """Euclidean distance between two 3-vectors."""
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
                     + (a[2] - b[2]) ** 2)


def farthest_pair(points: List[Point]) -> Tuple[int, int, float]:
    """Indices and distance of the two points furthest apart.

    O(n^2) on purpose: the rim ring is tens of points, and an exact answer
    on a small set beats an approximate one nobody can check.
    """
    if len(points) < 2:
        raise ValueError("farthest_pair needs at least 2 points")
    best = (0, 1, -1.0)
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            d = distance(points[i], points[j])
            if d > best[2]:
                best = (i, j, d)
    return best


def rim_diameter(points: List[Point]) -> float:
    """Max pairwise distance across a ring of vertices."""
    if len(points) < 2:
        raise ValueError("rim_diameter needs at least 2 points")
    return farthest_pair(points)[2]


def apex_to_tip(apex: Point, tip: Point) -> float:
    """Distance from the bell apex vertex to a named tendril's tip vertex."""
    return distance(apex, tip)
