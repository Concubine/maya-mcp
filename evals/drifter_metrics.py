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
    """Distance from the bell apex point to the tendril tip point.

    Both arguments are CENTROIDS of a landmark set, not single vertices -
    see the landmark section below for why a single vertex cannot be used.
    """
    return distance(apex, tip)


# --- Landmarks: index-free selection, aggregate measurement ----------------
#
# MEASURED in the first live Unity run (#743 Task 10) and this is the whole
# reason the rule below is shaped the way it is:
#
#   1. Unity's FBX import split the drifter's 23,922 vertices into 93,344.
#      UV/hard-normal seams duplicate vertices at the same POSITION, and no
#      importer setting (weld, optimize) collapses them. So neither Maya's
#      .vtx[] index nor the raw FBX control-point index names the same
#      physical point in both engines, and any RAW mean over vertices is
#      biased by however many duplicates each engine happens to carry.
#   2. The 12 lowest vertices on a tapered tendril cap sit at 0.0, 1.7,
#      1.7, 3.5, 3.5, 5.2, 5.2, 6.9, 6.9, 8.6, 8.6 and 10.3 mm from each
#      other - all DISTINCT positions. "The lowest vertex" is therefore a
#      coin-flip between a dozen candidates spread over a centimetre, and
#      float noise across an FBX round-trip is more than enough to flip it.
#      The 26/42 deltas of 0.6-12.1 mm that failed the first consumer gate
#      were exactly that candidate spread, not a skinning error.
#
# So a landmark is (a) SELECTED as a set, by a geometric band rather than
# an extremum, (b) DEDUPED by quantised position so a split mesh weighs the
# same as an unsplit one, and (c) MEASURED as an aggregate - a centroid or
# a mean radius - which barely moves when the two engines disagree about
# one member. Selection happens once at bind in each engine independently;
# the resulting indices are then tracked per frame, which is what keeps a
# metric following the SAME physical feature as it deforms.

POSITION_QUANTUM = 1e-4
"""Position-key grid, in metres (0.1 mm).

Coarse enough to collapse a split vertex onto its twin across an FBX
round-trip, fine enough to keep the 1.7 mm-apart cap candidates distinct.
"""


def position_key(p: Point, quantum: float = POSITION_QUANTUM) -> tuple:
    """Quantised position - a split vertex and its twin share one key."""
    return (int(round(p[0] / quantum)), int(round(p[1] / quantum)),
            int(round(p[2] / quantum)))


def dedupe_by_position(points: List[Point], indices: Sequence[int],
                       quantum: float = POSITION_QUANTUM) -> List[int]:
    """One index per distinct position, first occurrence wins, order kept.

    Order is preserved rather than sorted so a caller can reason about
    which index survived; first-wins makes the choice deterministic.
    """
    seen = set()
    out = []
    for i in indices:
        k = position_key(points[i], quantum)
        if k not in seen:
            seen.add(k)
            out.append(i)
    return out


def low_band_indices(points: List[Point], half_width: float) -> List[int]:
    """Indices within `half_width` of the mesh's MINIMUM y.

    A band, not an argmin: the set is stable even when float noise flips
    which individual vertex is lowest, because a sub-millimetre flip does
    not move anyone across a centimetre-wide boundary.
    """
    if not points:
        raise ValueError("low_band_indices needs at least 1 point")
    lo = min(p[1] for p in points)
    return [i for i, p in enumerate(points) if p[1] - lo <= half_width]


def high_band_indices(points: List[Point], half_width: float) -> List[int]:
    """Indices within `half_width` of the mesh's MAXIMUM y."""
    if not points:
        raise ValueError("high_band_indices needs at least 1 point")
    hi = max(p[1] for p in points)
    return [i for i, p in enumerate(points) if hi - p[1] <= half_width]


def rim_band_indices(points: List[Point], rim_y: float, half_width: float,
                     radius_min: float) -> List[int]:
    """Indices near the bell's rim height and off its vertical axis.

    The radius floor is load-bearing, not tidiness: each of the eight
    tendrils is BUILT starting at the bell's rim, so each one's polar
    cap-centre vertex also sits at rim height, ~0.02 m from the axis. A
    plain Y band catches 1,815 vertices on this mesh and most of them are
    those cap clusters.
    """
    out = []
    for i, p in enumerate(points):
        radius = math.sqrt(p[0] ** 2 + p[2] ** 2)
        if abs(p[1] - rim_y) < half_width and radius > radius_min:
            out.append(i)
    return out


def lowest_n(points: List[Point], indices: Sequence[int], n: int) -> List[int]:
    """The `n` indices with the smallest y, ties broken by index.

    Rank selection, not thresholding, and it exists because a threshold
    could not make the two engines agree on set SIZE. MEASURED across an
    FBX round-trip: the same band+dedupe rule yielded 105 tip vertices in
    Maya and 120 in Unity (774 vs 784 at the rim), because float32
    positions land either side of a hard boundary - and of the dedupe's
    own quantum grid - differently in each engine. A constant offset from
    that is harmless, but during `tendril_reach`'s curl the 15 extra
    members moved differently and drove apex_to_tip 38 mm apart.

    So the producer DECLARES the cardinality and the consumer reproduces
    it: search a deliberately wider band, then cut to the declared n. The
    index tiebreak is what keeps the cut deterministic when two vertices
    share a y exactly.
    """
    ranked = sorted(indices, key=lambda i: (points[i][1], i))
    return ranked[:n]


def highest_n(points: List[Point], indices: Sequence[int], n: int) -> List[int]:
    """The `n` indices with the largest y, ties broken by index."""
    ranked = sorted(indices, key=lambda i: (-points[i][1], i))
    return sorted(ranked[:n])


def nearest_y_n(points: List[Point], indices: Sequence[int], target_y: float,
                n: int) -> List[int]:
    """The `n` indices whose y is closest to `target_y`, ties by index."""
    ranked = sorted(indices, key=lambda i: (abs(points[i][1] - target_y), i))
    return sorted(ranked[:n])


def centroid(points: List[Point], indices: Sequence[int]) -> Tuple[float, float, float]:
    """Mean position of the selected indices.

    Dedupe the indices first (`dedupe_by_position`) whenever the mesh may
    be split - this function deliberately does not, so the caller decides.
    """
    if not indices:
        raise ValueError("centroid needs at least 1 index")
    n = float(len(indices))
    return (sum(points[i][0] for i in indices) / n,
            sum(points[i][1] for i in indices) / n,
            sum(points[i][2] for i in indices) / n)


def ring_diameter(points: List[Point], indices: Sequence[int]) -> float:
    """Twice the mean XZ radius of a ring about its OWN XZ centre.

    Replaces the farthest-pair rim measure. Two reasons, both measured:
    a farthest pair is an extremum and inherits the same coin-flip as the
    lowest vertex; and referencing the ring's own centre rather than the
    world axis makes the number survive the root translation `pulse_swim`
    applies (0.7 m of it).
    """
    if not indices:
        raise ValueError("ring_diameter needs at least 1 index")
    cx = sum(points[i][0] for i in indices) / float(len(indices))
    cz = sum(points[i][2] for i in indices) / float(len(indices))
    total = 0.0
    for i in indices:
        total += math.sqrt((points[i][0] - cx) ** 2 + (points[i][2] - cz) ** 2)
    return 2.0 * total / float(len(indices))


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
