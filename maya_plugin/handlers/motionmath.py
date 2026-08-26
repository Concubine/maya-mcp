"""Pure motion metrics for measure_clip (#773). No Maya anywhere in here.

Input everywhere: `track` = a list of [x, y, z] world positions, one per
sampled frame, for one joint. The handler samples; this judges.

Every metric in this module earned its place by DISCRIMINATING in the #773
probe - a good walk-in-place clip against the same clip with a drifting plant
and one popped key, on a real rig:

* foot slide during inferred contact: 0.0 good vs 0.097 broken (a 1 m rig).
* peak speed on the popped limb: 8.05 vs 3.39; max |accel| 111 vs 53.
* left/right peak-speed asymmetry: 1.0 good vs 2.4 broken.

And one candidate measurably FAILED there, which is why it is absent: an
acceleration-spike-to-median ratio scored the GOOD clip higher (20.0) than the
broken one (10.3), because a clip with a rest phase has a near-zero median
that turns the ratio into noise. Raw per-joint numbers plus the cross-limb
comparison discriminate; the self-normalised ratio does not.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Contact inference, relative to the RIG rather than absolute: a frame is a
# contact candidate when the joint is within CONTACT_HEIGHT_FRAC of the rig's
# height above its own lowest point, moving slower than CONTACT_SPEED_FRAC of
# the rig's height PER SECOND. The #773 probe used absolute 0.02 / 0.35 on a
# 1 m rig - these are those numbers, made scale-free.
#
# Deliberately NOT a fraction of the joint's own peak speed, though that was
# the first draft: a foot that does nothing but drift has a peak that IS the
# drift, so a self-relative threshold excludes every frame and the slide it
# exists to catch goes unmeasured. Caught by test_motionmath before it
# shipped. The rig's height is the one scale that does not depend on the
# defect being measured.
CONTACT_HEIGHT_FRAC = 0.02
CONTACT_SPEED_FRAC = 0.35
# A plant that wanders further than this fraction of rig height is named in
# warnings. The probe's broken clip measured 0.097 on a 1.0-height rig against
# an exact 0.0 for the good one - 2% sits far from both.
SLIDE_WARN_FRAC = 0.02


def speeds(track: Sequence[Sequence[float]], fps: float) -> List[float]:
    """Per-interval speed, world units/second. len(track) - 1 entries."""
    return [math.dist(a, b) * fps for a, b in zip(track, track[1:])]


def accelerations(track: Sequence[Sequence[float]], fps: float) -> List[float]:
    """|dv|/dt between consecutive intervals. len(track) - 2 entries."""
    v = speeds(track, fps)
    return [abs(b - a) * fps for a, b in zip(v, v[1:])]


def path_length(track: Sequence[Sequence[float]]) -> float:
    return sum(math.dist(a, b) for a, b in zip(track, track[1:]))


def joint_kinematics(track: Sequence[Sequence[float]], fps: float) -> Dict[str, Any]:
    """The raw numbers for one joint. Judgement calls stay with the caller -
    these are reported, not thresholded (the probe showed self-normalised
    thresholds lie on clips with rest phases; a POP shows up as roughly 2x
    peak speed and max accel against the same joint's mirror instead)."""
    if len(track) < 2:
        return {"path_length": 0.0, "peak_speed": 0.0, "peak_speed_frame": 0,
                "max_accel": 0.0, "max_accel_frame": 0,
                "height_range": [0.0, 0.0]}
    v = speeds(track, fps)
    a = accelerations(track, fps)
    ys = [p[1] for p in track]
    peak_i = max(range(len(v)), key=lambda i: v[i])
    out = {
        "path_length": path_length(track),
        "peak_speed": v[peak_i],
        "peak_speed_frame": peak_i,
        "max_accel": max(a) if a else 0.0,
        "max_accel_frame": (max(range(len(a)), key=lambda i: a[i]) + 1) if a else 0,
        "height_range": [min(ys), max(ys)],
    }
    return out


def contact_runs(
    track: Sequence[Sequence[float]], fps: float, rig_height: float,
) -> List[Tuple[int, int]]:
    """Inclusive (first_frame, last_frame) index runs where the joint reads
    as planted: near its own lowest point AND nearly still.

    Inferred, not declared - the clip format carries no plant annotation, and
    the probe showed low+slow finds the plant phase of a walk cycle without
    one. Relative thresholds: near = within CONTACT_HEIGHT_FRAC of rig height
    above the track's own minimum; still = slower than CONTACT_SPEED_FRAC
    of the rig's height per second. Never a fraction of the joint's own
    peak - see the constants' comment for the drift-only foot that a
    self-relative threshold cannot see.
    """
    if len(track) < 2 or rig_height <= 0:
        return []
    v = speeds(track, fps)
    floor_y = min(p[1] for p in track)
    y_tol = CONTACT_HEIGHT_FRAC * rig_height
    speed_tol = CONTACT_SPEED_FRAC * rig_height
    flags = [track[i][1] - floor_y < y_tol and v[i] <= speed_tol
             for i in range(len(v))]
    runs: List[Tuple[int, int]] = []
    start: Optional[int] = None
    for i, on in enumerate(flags):
        if on and start is None:
            start = i
        elif not on and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(flags)))
    return runs


def max_slide(
    track: Sequence[Sequence[float]], runs: Sequence[Tuple[int, int]],
) -> float:
    """The furthest any single contact run wanders in the ground plane (XZ).

    Run-endpoint displacement, not per-frame sums: a planted foot may jitter
    within tolerance every frame, but only a net drift is a slide."""
    worst = 0.0
    for first, last in runs:
        a, b = track[first], track[last]
        worst = max(worst, math.hypot(a[0] - b[0], a[2] - b[2]))
    return worst


def loop_closure(track: Sequence[Sequence[float]]) -> float:
    """World distance between the first and last sampled frame."""
    if len(track) < 2:
        return 0.0
    return math.dist(track[0], track[-1])


def mirror_pairs(names: Sequence[str]) -> List[Tuple[str, str]]:
    """(left, right) joint pairs by the repo's own L_/R_ naming convention."""
    by_stem = {}
    for name in names:
        short = name.rsplit("|", 1)[-1]
        for prefix, side in (("L_", "left"), ("R_", "right")):
            if short.startswith(prefix):
                by_stem.setdefault(short[len(prefix):], {})[side] = name
    return [(entry["left"], entry["right"])
            for stem, entry in sorted(by_stem.items())
            if "left" in entry and "right" in entry]


def symmetry_ratio(peak_a: float, peak_b: float) -> float:
    """Larger peak over smaller: 1.0 = symmetric effort. The probe's popped
    limb read 2.4 against its mirror; the clean pair read exactly 1.0."""
    lo, hi = sorted([abs(peak_a), abs(peak_b)])
    if hi == 0.0:
        return 1.0
    if lo == 0.0:
        return float("inf")
    return hi / lo
