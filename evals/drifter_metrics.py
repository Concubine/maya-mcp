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


METRICS = ("rim_diameter", "apex_to_tip")


def _key(sample) -> tuple:
    return (sample["clip"], int(sample["frame"]))


def compare_samples(declared, measured, tol: float) -> List[dict]:
    """Declared-vs-measured, per clip, per frame, per metric.

    Refuses a missing measurement rather than skipping it: a consumer gate
    that silently compares the samples it happens to have is how a partial
    run reads as a pass.
    """
    have = {_key(s): s for s in measured}
    out = []
    for want in declared:
        k = _key(want)
        got = have.get(k)
        if got is None:
            raise ValueError(
                "no measurement for clip %s frame %d" % (k[0], k[1]))
        for metric in METRICS:
            declared_val = float(want[metric])
            measured_val = float(got[metric])
            if not (math.isfinite(declared_val) and math.isfinite(measured_val)):
                # A NaN delta compares False against any tol (NaN > tol is
                # always False), so a corrupted measurement would pass
                # silently. Treat non-finite on either side as a violation
                # in its own right; delta is meaningless here, so report it
                # as infinite rather than inventing a number.
                out.append({"clip": k[0], "frame": k[1], "metric": metric,
                            "declared": declared_val,
                            "measured": measured_val, "delta": math.inf})
                continue
            delta = abs(declared_val - measured_val)
            if delta > tol:
                out.append({"clip": k[0], "frame": k[1], "metric": metric,
                            "declared": declared_val,
                            "measured": measured_val, "delta": delta})
    return out


def seam_violations(samples, looping_clips, tol: float) -> List[dict]:
    """First frame vs last frame, for looping clips only.

    author_clip's own `loop=True` already refuses a cycle that does not
    close IN MAYA. This is the other half: whether the seam survives the
    consumer's import, resampling and tangent handling.
    """
    looping = set(looping_clips)
    by_clip: dict = {}
    for s in samples:
        if s["clip"] in looping:
            by_clip.setdefault(s["clip"], []).append(s)
    out = []
    for clip, rows in sorted(by_clip.items()):
        rows = sorted(rows, key=lambda r: int(r["frame"]))
        first, last = rows[0], rows[-1]
        for metric in METRICS:
            delta = abs(float(first[metric]) - float(last[metric]))
            if delta > tol:
                out.append({"clip": clip, "metric": metric,
                            "first": float(first[metric]),
                            "last": float(last[metric]), "delta": delta})
    return out


def histogram_facts(buckets) -> dict:
    """Flatten weight_report's influence histogram into three numbers.

    over_four is the one that matters: Unity truncates to four influences
    per vertex and renormalises, so a non-zero count here PREDICTS a
    consumer-side deformation difference before we go looking for one.
    """
    vertices = sum(int(b["vertices"]) for b in buckets)
    over = sum(int(b["vertices"]) for b in buckets
               if int(b["influences"]) > 4)
    top = max((int(b["influences"]) for b in buckets), default=0)
    return {"max_influences": top, "vertices": vertices, "over_four": over}
