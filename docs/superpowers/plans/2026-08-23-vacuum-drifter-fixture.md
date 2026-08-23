# Vacuum Drifter Fixture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fully deformable creature — skinned bell, eight ten-joint tendrils, three animation takes, one flat texture — export it, and measure the deformed result in a real Unity, so the seams a rigid asset can never touch get exercised and measured.

**Architecture:** Three artefacts on the pattern #718 established. Pure geometry/policy functions live in `evals/drifter_metrics.py` and are unit-tested headlessly. The live Maya gate `evals/drifter_live.py` drives the MCP tool surface over the shared TCP client, measures, exports, checks the bytes, and writes `evals/drifter_live/baseline.json`. The consumer gate `evals/drifter_unity.py` holds C# and pass/fail policy derived from that baseline, and is driven by the agent through the unityMCP tools — a Python process cannot call an MCP tool.

**Tech Stack:** Python 3 + `uv`, `pytest`, the repo's `evals/live_call.py` TCP client, the `maya` MCP server (live Maya), the `unityMCP` MCP server (live Unity editor), C# executed through `mcp__unityMCP__execute_code`.

Spec: [`docs/superpowers/specs/2026-08-23-vacuum-drifter-fixture-design.md`](../specs/2026-08-23-vacuum-drifter-fixture-design.md)
Ticket: [#743](http://localhost:3000/issues/743)

## Global Constraints

Every task's requirements implicitly include this section.

- **Metre-native.** `maya_export_fbx(metres_per_unit=1.0)`; only 1.0 exports. Assert `export_metres_per_unit == 1.0`, never the `linear_unit` string.
- **Vertex ceiling: 15000 total.** The gate asserts the ceiling and reports the actual count. Exceeding it FAILS the gate.
- **Rig: exactly 105 joints** — 1 root, 8 ribs × 3, 8 tendrils × 10.
- **fps: 30**, declared explicitly and restated at export.
- **Loop-seam tolerance: 1e-4** (metres, on the §8 metrics, in the consumer).
- **Deformation comparison tolerance: 1e-3 metres** between Maya-declared and Unity-measured.
- **Bind at `max_influences=8`** — deliberately above Unity's four, to construct the truncation case.
- **MCP is the primary path.** If the Maya plugin or the Unity editor is unreachable or `claude mcp list` shows a server unhealthy: report in one line and STOP. **No CLI batchmode fallback.**
- **Never touch `evals/golem_rerun_665/out_v4/`** — another agent's in-flight work. Never commit, clean, or edit it.
- **Never point the Unity gate at Demigol.** Scratch project only; its importer forces `importAnimation=false`.
- **Port discipline.** `evals/live_call.py` reads `MAYA_MCP_PORT` (default 9878). Set `MAYA_MCP_EXPECT_PID` to the pid you intend to talk to — a port is not an identity (#648).
- **Naming:** every scene node is prefixed `drifter_`.

---

## File Structure

| File | Responsibility |
|---|---|
| `evals/drifter_metrics.py` | **New.** Pure functions: frame-invariant metrics, seam comparison, influence-histogram policy, sample comparison. No Maya, no network, no I/O. |
| `tests/test_drifter_metrics.py` | **New.** Unit tests for the above. |
| `evals/drifter_live.py` | **New.** Live Maya gate: build → skin → blendshapes → clips → material → export → byte gate → writes `evals/drifter_live/baseline.json`. |
| `evals/drifter_live/baseline.json` | **New (generated).** The single source of declared truth. Committed. |
| `evals/drifter_unity.py` | **New.** Consumer gate: C# template, `verify()`, `_steps_text()`, `main()`. Derives everything from the baseline. |
| `tests/test_drifter_unity.py` | **New.** Unit tests for `verify()` policy without any Unity. |

`drifter_metrics.py` exists so both gates compute the same numbers the same way. Putting the metrics in either gate would mean the consumer gate reimplements them — which is exactly how #737's `check_poses` ended up self-consistent instead of consumer-true.

---

### Task 1: Frame-invariant metrics

**Files:**
- Create: `evals/drifter_metrics.py`
- Test: `tests/test_drifter_metrics.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `distance(a, b) -> float`, `farthest_pair(points) -> tuple[int, int, float]`, `rim_diameter(points) -> float`, `apex_to_tip(apex, tip) -> float`. `points` is a list of `[x, y, z]` floats.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_drifter_metrics.py
"""#743: the drifter fixture's pure metrics.

These are frame-invariant on purpose. #737 turned on comparing a quantity
that survives any rigid or mirrored transform, because height agreed to
2 micrometres on three poses whose arms were metres out. Every metric here
must be a distance between two points on the same mesh - never a coordinate,
never a bounding box.
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "evals"))

import drifter_metrics as dm  # noqa: E402


def test_distance_is_euclidean():
    assert dm.distance([0.0, 0.0, 0.0], [3.0, 4.0, 0.0]) == 5.0


def test_farthest_pair_finds_the_extremes():
    pts = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [5.0, 0.0, 0.0], [2.0, 0.0, 0.0]]
    i, j, d = dm.farthest_pair(pts)
    assert {i, j} == {0, 2}
    assert d == 5.0


def test_rim_diameter_of_a_unit_circle_ring():
    pts = [[math.cos(t * math.pi / 8), 0.0, math.sin(t * math.pi / 8)]
           for t in range(16)]
    assert abs(dm.rim_diameter(pts) - 2.0) < 1e-9


def test_rim_diameter_is_invariant_under_rigid_motion():
    pts = [[math.cos(t * math.pi / 8), 0.0, math.sin(t * math.pi / 8)]
           for t in range(16)]
    # Rotate 37 degrees about Y and translate: the diameter must not move.
    a = math.radians(37.0)
    moved = [[p[0] * math.cos(a) - p[2] * math.sin(a) + 11.0,
              p[1] - 4.0,
              p[0] * math.sin(a) + p[2] * math.cos(a) + 6.0] for p in pts]
    assert abs(dm.rim_diameter(pts) - dm.rim_diameter(moved)) < 1e-9


def test_rim_diameter_is_invariant_under_mirroring():
    pts = [[math.cos(t * math.pi / 8), 0.0, math.sin(t * math.pi / 8)]
           for t in range(16)]
    mirrored = [[-p[0], p[1], p[2]] for p in pts]
    assert abs(dm.rim_diameter(pts) - dm.rim_diameter(mirrored)) < 1e-9


def test_apex_to_tip_is_a_plain_distance():
    assert abs(dm.apex_to_tip([0.0, 4.0, 0.0], [0.0, 0.1, 0.0]) - 3.9) < 1e-12


def test_rim_diameter_refuses_fewer_than_two_points():
    try:
        dm.rim_diameter([[0.0, 0.0, 0.0]])
    except ValueError as exc:
        assert "at least 2" in str(exc)
    else:
        raise AssertionError("expected ValueError")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_drifter_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'drifter_metrics'`

- [ ] **Step 3: Write minimal implementation**

```python
# evals/drifter_metrics.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_drifter_metrics.py -v`
Expected: PASS, 7 passed

- [ ] **Step 5: Commit**

```bash
git add evals/drifter_metrics.py tests/test_drifter_metrics.py
git commit -m "test(#743): frame-invariant metrics for the drifter fixture"
```

---

### Task 2: Comparison and histogram policy

**Files:**
- Modify: `evals/drifter_metrics.py`
- Modify: `tests/test_drifter_metrics.py`

**Interfaces:**
- Consumes: Task 1's `distance` / `rim_diameter` / `apex_to_tip`.
- Produces:
  - `compare_samples(declared, measured, tol) -> list[dict]` — both args are lists of `{"clip": str, "frame": int, "rim_diameter": float, "apex_to_tip": float}`; returns violation dicts `{"clip", "frame", "metric", "declared", "measured", "delta"}`.
  - `seam_violations(samples, looping_clips, tol) -> list[dict]` — samples for one source; returns `{"clip", "metric", "first", "last", "delta"}` for looping clips whose first and last frame disagree.
  - `histogram_facts(buckets) -> dict` — buckets are `[{"influences": int, "vertices": int}, ...]`; returns `{"max_influences": int, "vertices": int, "over_four": int}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_drifter_metrics.py`:

```python
DECLARED = [
    {"clip": "pulse_swim", "frame": 0, "rim_diameter": 1.200,
     "apex_to_tip": 3.900},
    {"clip": "pulse_swim", "frame": 15, "rim_diameter": 0.900,
     "apex_to_tip": 3.700},
]


def test_compare_samples_clean_when_inside_tolerance():
    measured = [dict(s) for s in DECLARED]
    measured[1]["rim_diameter"] += 5e-4
    assert dm.compare_samples(DECLARED, measured, 1e-3) == []


def test_compare_samples_reports_the_metric_that_moved():
    measured = [dict(s) for s in DECLARED]
    measured[1]["apex_to_tip"] = 3.500
    bad = dm.compare_samples(DECLARED, measured, 1e-3)
    assert len(bad) == 1
    assert bad[0]["clip"] == "pulse_swim"
    assert bad[0]["frame"] == 15
    assert bad[0]["metric"] == "apex_to_tip"
    assert abs(bad[0]["delta"] - 0.2) < 1e-9


def test_compare_samples_refuses_a_missing_measurement():
    try:
        dm.compare_samples(DECLARED, DECLARED[:1], 1e-3)
    except ValueError as exc:
        assert "pulse_swim" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_seam_violations_ignores_a_one_shot_clip():
    samples = [
        {"clip": "tendril_reach", "frame": 0, "rim_diameter": 1.2,
         "apex_to_tip": 3.9},
        {"clip": "tendril_reach", "frame": 30, "rim_diameter": 1.2,
         "apex_to_tip": 2.4},
    ]
    assert dm.seam_violations(samples, ["pulse_swim"], 1e-4) == []


def test_seam_violations_catches_a_loop_that_does_not_close():
    samples = [
        {"clip": "pulse_swim", "frame": 0, "rim_diameter": 1.2,
         "apex_to_tip": 3.9},
        {"clip": "pulse_swim", "frame": 15, "rim_diameter": 0.9,
         "apex_to_tip": 3.7},
        {"clip": "pulse_swim", "frame": 30, "rim_diameter": 1.2,
         "apex_to_tip": 3.8},
    ]
    bad = dm.seam_violations(samples, ["pulse_swim"], 1e-4)
    assert len(bad) == 1
    assert bad[0]["metric"] == "apex_to_tip"
    assert abs(bad[0]["delta"] - 0.1) < 1e-9


def test_histogram_facts_counts_vertices_over_four():
    buckets = [{"influences": 2, "vertices": 100},
               {"influences": 4, "vertices": 50},
               {"influences": 6, "vertices": 7}]
    facts = dm.histogram_facts(buckets)
    assert facts == {"max_influences": 6, "vertices": 157, "over_four": 7}


def test_histogram_facts_on_a_bind_that_never_exceeds_four():
    buckets = [{"influences": 3, "vertices": 10},
               {"influences": 4, "vertices": 20}]
    assert dm.histogram_facts(buckets)["over_four"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_drifter_metrics.py -v`
Expected: FAIL — `AttributeError: module 'drifter_metrics' has no attribute 'compare_samples'`

- [ ] **Step 3: Write minimal implementation**

Append to `evals/drifter_metrics.py`:

```python
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
            delta = abs(float(want[metric]) - float(got[metric]))
            if delta > tol:
                out.append({"clip": k[0], "frame": k[1], "metric": metric,
                            "declared": float(want[metric]),
                            "measured": float(got[metric]), "delta": delta})
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_drifter_metrics.py -v`
Expected: PASS, 14 passed

- [ ] **Step 5: Commit**

```bash
git add evals/drifter_metrics.py tests/test_drifter_metrics.py
git commit -m "test(#743): declared-vs-measured, seam and influence-histogram policy"
```

---

### Task 3: Preflight and the rig layout

**Files:**
- Create: `evals/drifter_live.py`
- Test: manual run against a live Maya (this task has no headless test — it is the live gate's skeleton)

**Interfaces:**
- Consumes: `evals/live_call.py`'s `call()`; `drifter_metrics`.
- Produces: `JOINTS` (list of 105 dicts for `create_skeleton`), `BELL`/`TENDRIL` geometry constants, `preflight()`, `build_skeleton()`.

**Before starting:** confirm which Maya answers. A port is not an identity (#648), and a Maya launched before the last deploy holds stale modules.

- [ ] **Step 1: Verify the live Maya and record its identity**

```bash
uv run python -c "import sys; sys.path.insert(0,'evals'); import live_call; print(live_call.call('ping', {}))"
```

Expected: a `result` carrying `pid`, `package_dir`, `loaded_digest`, `restart_required`. **`restart_required` must be false.** If it is true, STOP and ask the user to restart that Maya — a stale plugin will refuse or mis-author the skeleton (#703's gate refuses pre-fix skeletons outright).

Record the pid and export it for the rest of the session:

```bash
export MAYA_MCP_EXPECT_PID=<the pid ping reported>
```

- [ ] **Step 2: Write the rig layout and preflight**

```python
# evals/drifter_live.py
"""#743 live gate: the vacuum drifter - a FULLY DEFORMABLE fixture.

The golem was rigid chunks and taught us everything a rigid hierarchy can
(#665, #711, #712, #713, #728, #737). This is its structural opposite: one
skinned mesh, 105 joints, three takes, and nothing rigid anywhere.

What this gate is FOR - each is a seam no delivered asset has crossed:

  1  a real skinCluster carried into a consumer (the golem's chunks were
     rigid-PARENTED to joints, which is a different import path entirely)
  2  a skin cluster and an ANIMATED blend-shape channel in the SAME take
  3  pose_ik on a ten-joint chain with no natural fold - it was gated on a
     three-joint humanoid limb where preferredAngle decides the bend
  4  bind at max_influences=8, ABOVE Unity's four, so the truncation case
     exists to be measured instead of hoped for

Measurements are FRAME-INVARIANT distances (drifter_metrics), never
heights and never coordinates - #737's whole lesson.

Usage:
    uv run python evals/drifter_live.py
Exit: 0 pass, 1 fail. Writes evals/drifter_live/baseline.json.
"""

from __future__ import annotations

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import drifter_metrics as dm            # noqa: E402
from live_call import call              # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "drifter_live")
BASELINE_PATH = os.path.join(OUT_DIR, "baseline.json")

# --- Global constraints, as constants -------------------------------------
FPS = 30
VERTEX_CEILING = 15000
MAX_INFLUENCES = 8          # deliberately above Unity's 4 - see docstring
SEAM_TOL = 1e-4             # metres, on the frame-invariant metrics
COMPARE_TOL = 1e-3          # metres, Maya-declared vs Unity-measured
RIBS = 8
RIB_JOINTS = 3
TENDRILS = 8
TENDRIL_JOINTS = 10

# --- Layout, in metres ----------------------------------------------------
APEX_Y = 4.0                # bell apex
RIM_Y = 3.1                 # bell equator, where tendrils start
RIM_R = 0.6                 # bell radius: 1.2 m across
TENDRIL_BOTTOM_Y = 0.1
TENDRIL_SPAN = RIM_Y - TENDRIL_BOTTOM_Y          # 3.0 m
TENDRIL_STEP = TENDRIL_SPAN / TENDRIL_JOINTS     # 0.3 m per joint

ROOT = "drifter_root"


def _rib_ring(index: int) -> float:
    """Angle in radians for rib/tendril `index` (1-based), 45 deg apart."""
    return math.radians(45.0 * (index - 1))


def rib_name(rib: int, joint: int) -> str:
    return "drifter_rib%d_%02d" % (rib, joint)


def tendril_name(tendril: int, joint: int) -> str:
    return "drifter_tendril%d_%02d" % (tendril, joint)


def build_joint_specs() -> list:
    """The 105 joints, as create_skeleton's explicit `joints` form.

    Tendrils descend from rib TIPS, not from the root, so the hierarchy is
    genuinely deep and a weight error at the bell margin propagates three
    metres down a tendril where a measurement cannot miss it.
    """
    specs = [{"name": ROOT, "position": [0.0, APEX_Y, 0.0]}]
    for rib in range(1, RIBS + 1):
        theta = _rib_ring(rib)
        parent = ROOT
        for j in range(1, RIB_JOINTS + 1):
            frac = j / float(RIB_JOINTS)
            radius = RIM_R * frac
            y = APEX_Y - (APEX_Y - RIM_Y) * frac
            name = rib_name(rib, j)
            specs.append({"name": name,
                          "position": [radius * math.cos(theta), y,
                                       radius * math.sin(theta)],
                          "parent": parent})
            parent = name
        for j in range(1, TENDRIL_JOINTS + 1):
            name = tendril_name(rib, j)
            specs.append({"name": name,
                          "position": [RIM_R * math.cos(theta),
                                       RIM_Y - TENDRIL_STEP * j,
                                       RIM_R * math.sin(theta)],
                          "parent": parent})
            parent = name
    return specs


JOINTS = build_joint_specs()


def preflight() -> dict:
    """Refuse to run against a stale or unidentified plugin.

    A green result from the wrong Maya is worse than no result (#648), and
    a Maya holding pre-deploy modules will refuse or mis-author the
    skeleton (#703).
    """
    ping = call("ping", {}).get("result") or {}
    if not ping:
        raise SystemExit("no Maya answered - start one, or check "
                         "MAYA_MCP_PORT. Do NOT fall back to batchmode.")
    if ping.get("restart_required"):
        raise SystemExit(
            "the answering Maya (pid %s) holds stale modules - restart it "
            "before running this gate" % ping.get("pid"))
    return ping
```

- [ ] **Step 3: Verify the layout arithmetic without touching Maya**

```bash
uv run python -c "import sys; sys.path.insert(0,'evals'); import drifter_live as d; print(len(d.JOINTS)); print(d.JOINTS[0]); print(d.JOINTS[-1]); print(sum(1 for j in d.JOINTS if 'parent' not in j))"
```

Expected:
```
105
{'name': 'drifter_root', 'position': [0.0, 4.0, 0.0]}
{'name': 'drifter_tendril8_10', 'position': [...], 'parent': 'drifter_tendril8_09'}
1
```

**105 joints and exactly one parentless joint.** `create_skeleton` refuses the whole call if more than one joint names no parent, so checking it here saves a round trip.

- [ ] **Step 4: Build the skeleton in the live Maya**

```python
# append to evals/drifter_live.py

def build_skeleton() -> dict:
    call("new_scene", {})
    res = call("create_skeleton", {"joints": JOINTS}).get("result") or {}
    if len(res.get("joints", [])) != len(JOINTS):
        raise SystemExit("create_skeleton returned %d joints, expected %d"
                         % (len(res.get("joints", [])), len(JOINTS)))
    return res
```

Run it:

```bash
uv run python -c "import sys; sys.path.insert(0,'evals'); import drifter_live as d; d.preflight(); r=d.build_skeleton(); print(len(r['joints']))"
```

Expected: `105`

**Record the orientations.** `create_skeleton` auto-orients local X down the bone and reports what actually landed, in degrees. Print a few and note them — bend axes are per-joint local frames, and the tendril clips in Task 6 need to know which local axis curls.

- [ ] **Step 5: Commit**

```bash
git add evals/drifter_live.py
git commit -m "feat(#743): drifter rig layout - 105 joints, tendrils off rib tips"
```

---

### Task 4: Geometry, within the vertex ceiling

**Files:**
- Modify: `evals/drifter_live.py`

**Interfaces:**
- Consumes: Task 3's constants and `preflight()`.
- Produces: `measure_cylinder_coupling() -> dict`, `build_geometry() -> dict` returning `{"mesh": str, "vertices": int, "parts": [...]}`.

**The #669 decision this task makes, and why.** A ten-joint tendril needs at least ten edge loops along its length. `create_primitive`'s `divisions` is a MULTIPLIER whose cost differs wildly per kind: a cube spends it linearly per axis (`6*d^2` faces) while a sphere multiplies it by 20 on **both** axes (`400*d^2`). A cylinder's height subdivisions cannot be raised without dragging its axis subdivisions along — which is #669 exactly. Eight cylinders resolved enough to bend would blow the 15000-vertex ceiling many times over.

So tendrils are built from **cubes**, and the cylinder cost is **measured and recorded** as this run's #669 datapoint rather than argued about.

- [ ] **Step 1: Measure the cylinder coupling and record it**

```python
# append to evals/drifter_live.py

def measure_cylinder_coupling() -> dict:
    """The #669 datapoint: what a cylinder costs per unit of LENGTH detail.

    Recorded, not routed around. A tendril needs >=10 loops along its
    length; this says what that would cost in vertices if a cylinder
    supplied them.
    """
    out = []
    for d in (1, 4, 8, 12):
        res = call("create_primitive",
                   {"kind": "cylinder", "name": "drifter_probe_cyl",
                    "divisions": d}).get("result") or {}
        info = call("get_object_info",
                    {"name": res.get("name")}).get("result") or {}
        out.append({"divisions": d, "vertices": info.get("vertices"),
                    "faces": info.get("faces")})
        call("delete_objects", {"names": [res.get("name")]})
    return {"cylinder_divisions": out}
```

Run it and read the numbers:

```bash
uv run python -c "import sys,json; sys.path.insert(0,'evals'); import drifter_live as d; d.preflight(); print(json.dumps(d.measure_cylinder_coupling(), indent=2))"
```

Expected: vertex counts rising steeply with `divisions`. **Write the actual numbers into the commit message** — they are the finding, and #669 has never had a measured cost table.

- [ ] **Step 2: Build the bell and the eight tendrils**

```python
# append to evals/drifter_live.py

BELL_DIVISIONS = 4          # sphere: 400*d^2 faces -> ~6.4k
TENDRIL_DIVISIONS = 12      # cube: 6*d^2 faces -> ~864, 12 loops of length
BELL_SCALE = [1.2, 0.9, 1.2]
TENDRIL_SCALE = [0.08, TENDRIL_SPAN, 0.08]


def build_geometry() -> dict:
    """One bell plus eight tendrils, combined into ONE mesh.

    One mesh means one skinCluster means one SkinnedMeshRenderer in Unity,
    which is the shape a game character actually takes.
    """
    parts = []
    bell = (call("create_primitive",
                 {"kind": "sphere", "name": "drifter_bell",
                  "divisions": BELL_DIVISIONS,
                  "translate": [0.0, (APEX_Y + RIM_Y) / 2.0, 0.0],
                  "scale": BELL_SCALE}).get("result") or {})["name"]
    parts.append(bell)

    for t in range(1, TENDRILS + 1):
        theta = _rib_ring(t)
        name = (call("create_primitive",
                     {"kind": "cube", "name": "drifter_tendril_geo%d" % t,
                      "divisions": TENDRIL_DIVISIONS,
                      "translate": [RIM_R * math.cos(theta),
                                    (RIM_Y + TENDRIL_BOTTOM_Y) / 2.0,
                                    RIM_R * math.sin(theta)],
                      "scale": TENDRIL_SCALE}).get("result") or {})["name"]
        parts.append(name)

    combined = (call("combine", {"names": parts,
                                 "new_name": "drifter_body"}).get("result")
                or {})["name"]
    info = call("get_object_info", {"name": combined}).get("result") or {}
    verts = int(info.get("vertices", 0))
    if verts > VERTEX_CEILING:
        raise SystemExit(
            "drifter_body has %d vertices, ceiling is %d - lower "
            "BELL_DIVISIONS or TENDRIL_DIVISIONS rather than raising the "
            "ceiling" % (verts, VERTEX_CEILING))
    return {"mesh": combined, "vertices": verts, "parts": parts}
```

- [ ] **Step 3: Run it and confirm the budget holds**

```bash
uv run python -c "import sys,json; sys.path.insert(0,'evals'); import drifter_live as d; d.preflight(); d.build_skeleton(); print(json.dumps(d.build_geometry(), indent=2))"
```

Expected: a `vertices` count **under 15000**. If it exceeds, lower `BELL_DIVISIONS` first — the bell is the larger half.

- [ ] **Step 4: Look at it**

```bash
uv run python -c "import sys; sys.path.insert(0,'evals'); import live_call; print(live_call.call('capture_turntable', {'name':'drifter_body'})['result'].get('path'))"
```

Read the returned image. Eight tendrils, evenly spaced, hanging from the bell's rim, nothing intersecting. Correct what you SEE before adding detail — a rig bound to wrong geometry produces measurements that are precise and meaningless.

- [ ] **Step 5: Commit**

```bash
git add evals/drifter_live.py
git commit -m "feat(#743): drifter geometry - cube tendrils, and the #669 cylinder cost measured"
```

---

### Task 5: Bind, weights, and the influence distribution

**Files:**
- Modify: `evals/drifter_live.py`

**Interfaces:**
- Consumes: Task 4's `build_geometry()`; `drifter_metrics.histogram_facts`.
- Produces: `bind_and_weight(mesh) -> dict` returning `{"skin_cluster", "unweighted", "histogram", "facts", "mirror": {...}}`.

- [ ] **Step 1: Bind at 8 influences and read the distribution**

```python
# append to evals/drifter_live.py

def bind_and_weight(mesh: str) -> dict:
    """Bind ABOVE Unity's limit on purpose, then measure what we made.

    max_influences=8 constructs the truncation case; bound at the default
    4 the asset could never exceed Unity's cap and the question could not
    arise. over_four PREDICTS a consumer-side difference before we go
    looking for one.
    """
    bind = call("bind_skin", {"mesh": mesh, "root": ROOT,
                              "max_influences": MAX_INFLUENCES,
                              "method": "closestDistance"}).get("result") or {}
    if int(bind.get("unweighted_vertices", -1)) != 0:
        raise SystemExit(
            "%d unweighted vertices - a vertex no joint owns stays behind "
            "when the creature moves, and nothing looks wrong at bind time"
            % bind.get("unweighted_vertices"))

    before = call("weight_report", {"mesh": mesh}).get("result") or {}
    call("smooth_weights", {"mesh": mesh, "iterations": 2})
    after = call("weight_report", {"mesh": mesh}).get("result") or {}

    facts_before = dm.histogram_facts(before.get("histogram", []))
    facts_after = dm.histogram_facts(after.get("histogram", []))
    return {"skin_cluster": bind.get("skin_cluster"),
            "unweighted": int(after.get("unweighted_vertices", 0)),
            "histogram": after.get("histogram", []),
            "facts_before_smoothing": facts_before,
            "facts": facts_after,
            "smoothing_raised_max": (facts_after["max_influences"]
                                     > facts_before["max_influences"])}
```

- [ ] **Step 2: Run it and read the two questions it answers**

```bash
uv run python -c "import sys,json; sys.path.insert(0,'evals'); import drifter_live as d; d.preflight(); d.build_skeleton(); g=d.build_geometry(); print(json.dumps(d.bind_and_weight(g['mesh']), indent=2))"
```

Two numbers matter and both go in the commit message:
- **`facts["over_four"]`** — how many vertices Unity will truncate. If it is 0, the truncation case did not materialise even at `max_influences=8`, and that is itself the finding: geometry crowding was not sufficient.
- **`smoothing_raised_max`** — whether `smooth_weights` respects the bind cap. Nothing states that it does.

- [ ] **Step 3: Try `mirror_weights` and record whatever happens**

```python
# append to evals/drifter_live.py

def probe_mirror(mesh: str) -> dict:
    """Ribs at 90 and 270 degrees mirror ONTO THEMSELVES.

    mirror_weights pairs positionally and has only ever seen a humanoid,
    where nothing sits on the symmetry plane except an excluded spine. A
    self-paired joint is a case it has never met. Whatever it does is a
    FINDING, not an obstacle - record it and move on.
    """
    res = call("mirror_weights", {"mesh": mesh, "root": ROOT})
    return {"status": res.get("status"),
            "error": res.get("error"),
            "result": res.get("result")}
```

Run it:

```bash
uv run python -c "import sys,json; sys.path.insert(0,'evals'); import drifter_live as d; print(json.dumps(d.probe_mirror('drifter_body'), indent=2))"
```

**Do not fix whatever this reports.** Record it verbatim; §12 of the spec keeps the fix out of scope. If it errors, the run continues with the unmirrored weights — the fixture does not need mirrored weights to be valid, it needed to ask the question.

- [ ] **Step 4: Confirm the deformation is real**

```bash
uv run python -c "import sys,json; sys.path.insert(0,'evals'); import live_call; print(json.dumps(live_call.call('pose_skeleton', {'root':'drifter_root','rotations':{'drifter_tendril1_05':[0,0,40]}})['result'].get('max_displacement'), indent=2))"
```

Expected: a displacement of **tens of centimetres**, not near zero. A pose whose displacement is near zero against the mesh's size means the rotation landed on joints owning no vertices — which looks exactly like success otherwise. Then:

```bash
uv run python -c "import sys; sys.path.insert(0,'evals'); import live_call; live_call.call('reset_pose', {'root':'drifter_root'})"
```

- [ ] **Step 5: Commit**

```bash
git add evals/drifter_live.py
git commit -m "feat(#743): bind at 8 influences, measure the distribution, probe mirror on self-paired joints"
```

---

### Task 6: Blend shapes — two targets

**Files:**
- Modify: `evals/drifter_live.py`

**Interfaces:**
- Consumes: Task 5's bound mesh.
- Produces: `build_blendshapes(mesh) -> dict` returning `{"node": str, "aliases": ["bell_crease", "tendril_flare"]}`.

Targets must share the base's topology, so both are duplicates of the **combined, bound** mesh, sculpted and handed to `create_blendshape`.

- [ ] **Step 1: Build the two targets**

```python
# append to evals/drifter_live.py

BLEND_TARGETS = ("bell_crease", "tendril_flare")


def build_blendshapes(mesh: str) -> dict:
    """Two targets so each clip must PIN the other's channel to rest.

    That padding rule (maya_plugin/handlers/clip.py:537) is today only ever
    checked against itself. With two targets it becomes consumer-visible:
    if padding fails, Unity plays drift_idle with a crease stuck on.
    """
    crease = (call("duplicate", {"name": mesh,
                                 "new_name": "drifter_tgt_bell_crease"})
              .get("result") or {})["name"]
    # Squeeze the rim inward: the fold skinning cannot produce.
    call("deform", {"name": crease, "kind": "taper", "amount": -0.35,
                    "axis": "y"})

    flare = (call("duplicate", {"name": mesh,
                                "new_name": "drifter_tgt_tendril_flare"})
             .get("result") or {})["name"]
    call("deform", {"name": flare, "kind": "flare", "amount": 0.4,
                    "axis": "y"})

    res = call("create_blendshape",
               {"mesh": mesh,
                "targets": [{"mesh": crease, "alias": BLEND_TARGETS[0]},
                            {"mesh": flare, "alias": BLEND_TARGETS[1]}]}
               ).get("result") or {}
    aliases = res.get("aliases") or res.get("targets") or []
    if len(aliases) != 2:
        raise SystemExit("expected 2 blendshape aliases, got %r" % (aliases,))
    return {"node": res.get("node"), "aliases": list(BLEND_TARGETS),
            "raw": res}
```

**If `deform`'s `kind`/`axis` parameter names do not match**, read them first — do not guess:

```bash
uv run python -c "import sys,re,io; s=io.open('src/maya_mcp/server.py',encoding='utf-8').read(); m=re.search(r'def maya_deform\((.*?)\n    \) -> ', s, re.S); print(m.group(1))"
```

Adjust the call to the real signature. Note `bend`'s curvature is in **DEGREES** (#636) — a value like `0.35` means a third of a degree, not a third of a radian.

- [ ] **Step 2: Run it and confirm both targets exist**

```bash
uv run python -c "import sys,json; sys.path.insert(0,'evals'); import drifter_live as d; print(json.dumps(d.build_blendshapes('drifter_body'), indent=2))"
```

Expected: two aliases, `bell_crease` and `tendril_flare`.

- [ ] **Step 3: Verify each target actually moves the mesh**

```bash
uv run python -c "import sys; sys.path.insert(0,'evals'); import live_call; print(live_call.call('set_blendshape_weights', {'mesh':'drifter_body','weights':{'bell_crease':1.0}})['result'])"
```

Expected: a reported displacement well above zero. A target that changes nothing is a blend shape that will export, import, animate, and do nothing — indistinguishable from success in every check that does not measure movement. Reset both to 0.0 before continuing.

- [ ] **Step 4: Look at it**

Capture the viewport at `bell_crease = 1.0` and confirm the rim genuinely folds. Then reset.

- [ ] **Step 5: Commit**

```bash
git add evals/drifter_live.py
git commit -m "feat(#743): two blend targets, so each clip must pin the other's channel"
```

---

### Task 7: Three takes, and pose_ik on a ten-joint chain

**Files:**
- Modify: `evals/drifter_live.py`

**Interfaces:**
- Consumes: Tasks 5 and 6.
- Produces: `author_takes() -> dict` returning `{"clips": [{"name", "start_frame", "end_frame", "duration_s", "loop"}], "ik": {...}}`.

- [ ] **Step 1: Solve the tendril with IK and capture the rotations**

```python
# append to evals/drifter_live.py

def solve_tendril_reach() -> dict:
    """pose_ik where it has never been: a TEN-joint chain, no natural fold.

    It was gated on a three-joint humanoid limb where preferredAngle
    decides the bend. `start` must be passed explicitly - the default is
    two joints above `joint`, the classic 2-bone limb.

    Rotation is the only joint channel author_clip keys, so the target
    must sit INSIDE the chain's reach: the tendril reaches by curling, not
    by stretching. residual is the MEASURED miss; a large one is a
    FINDING, not a failure to route around.
    """
    theta = _rib_ring(1)
    target = [RIM_R * math.cos(theta) + 1.1, 1.4, RIM_R * math.sin(theta)]
    res = call("pose_ik", {"root": ROOT,
                           "start": tendril_name(1, 1),
                           "joint": tendril_name(1, TENDRIL_JOINTS),
                           "target": target,
                           "keep": False}).get("result") or {}
    return {"target": target,
            "residual": res.get("residual"),
            "achieved": res.get("achieved_position"),
            "rotations": res.get("rotations") or {},
            "warnings": res.get("warnings") or []}
```

Run it:

```bash
uv run python -c "import sys,json; sys.path.insert(0,'evals'); import drifter_live as d; print(json.dumps({k:v for k,v in d.solve_tendril_reach().items() if k!='rotations'}, indent=2))"
```

`keep=False` measures without baking, so this is safe to repeat while tuning the target. **Record the residual whatever it is.** If `pose_ik` cannot close on a ten-joint chain, that is the question this fixture was built to ask.

- [ ] **Step 2: Author the three takes**

```python
# append to evals/drifter_live.py

def _rib_sway(amount: float) -> dict:
    """Every rib's second joint, rotated about its own local Z."""
    return {rib_name(r, 2): [0.0, 0.0, amount]
            for r in range(1, RIBS + 1)}


def _bell_contract(amount: float) -> dict:
    """Ribs curling inward - the pulse."""
    out = {}
    for r in range(1, RIBS + 1):
        out[rib_name(r, 2)] = [0.0, 0.0, amount]
        out[rib_name(r, 3)] = [0.0, 0.0, amount * 0.6]
    return out


def author_takes() -> dict:
    ik = solve_tendril_reach()
    clips = []

    idle = call("author_clip", {
        "root": ROOT, "name": "drift_idle", "fps": FPS,
        "interpolation": "smooth", "loop": True,
        "keys": [
            {"time": 0.0, "rotations": _rib_sway(-2.0),
             "blend_weights": {b: 0.0 for b in BLEND_TARGETS}},
            {"time": 1.0, "rotations": _rib_sway(2.0),
             "blend_weights": {b: 0.0 for b in BLEND_TARGETS}},
            {"time": 2.0, "rotations": _rib_sway(-2.0),
             "blend_weights": {b: 0.0 for b in BLEND_TARGETS}},
        ]}).get("result") or {}
    clips.append(idle)

    swim = call("author_clip", {
        "root": ROOT, "name": "pulse_swim", "fps": FPS,
        "interpolation": "smooth", "loop": True,
        "keys": [
            {"time": 0.0, "rotations": _bell_contract(0.0),
             "blend_weights": {"bell_crease": 0.0, "tendril_flare": 0.0},
             "root_position": [0.0, APEX_Y, 0.0]},
            {"time": 0.5, "rotations": _bell_contract(-22.0),
             "blend_weights": {"bell_crease": 1.0, "tendril_flare": 0.0},
             "root_position": [0.0, APEX_Y, 0.35]},
            {"time": 1.0, "rotations": _bell_contract(0.0),
             "blend_weights": {"bell_crease": 0.0, "tendril_flare": 0.0},
             "root_position": [0.0, APEX_Y, 0.70]},
        ]}).get("result") or {}
    clips.append(swim)

    reach = call("author_clip", {
        "root": ROOT, "name": "tendril_reach", "fps": FPS,
        "interpolation": "smooth", "loop": False,
        "keys": [
            {"time": 0.0, "rotations": {j: [0.0, 0.0, 0.0]
                                        for j in ik["rotations"]},
             "blend_weights": {"bell_crease": 0.0, "tendril_flare": 0.0}},
            {"time": 1.2, "rotations": ik["rotations"],
             "blend_weights": {"bell_crease": 0.0, "tendril_flare": 1.0}},
        ]}).get("result") or {}
    clips.append(reach)

    return {"clips": [{"name": c.get("clip"),
                       "start_frame": c.get("start_frame"),
                       "end_frame": c.get("end_frame"),
                       "duration_s": c.get("duration_s"),
                       "loop": c.get("loop"),
                       "keyed_joints": c.get("keyed_joints"),
                       "keyed_weight_channels":
                           c.get("keyed_weight_channels"),
                       "root_position_keyed": c.get("root_position_keyed"),
                       "padded_channels": c.get("padded_channels")}
                      for c in clips],
            "ik": {k: v for k, v in ik.items() if k != "rotations"}}
```

**Note the bend axis.** `_rib_sway` and `_bell_contract` rotate about local Z. `create_skeleton` auto-orients local X down the bone, so the bend axis is a **per-joint local frame** — the axis that curls a rib is not necessarily Z. Read Task 3 Step 4's recorded orientations, and if the displacement in Step 3 below is near zero, try local Y before assuming the clip is broken.

- [ ] **Step 3: Run it and verify all three clips landed**

```bash
uv run python -c "import sys,json; sys.path.insert(0,'evals'); import drifter_live as d; print(json.dumps(d.author_takes(), indent=2))"
```

Expected: three clips, contiguous non-overlapping frame ranges, `loop: true` on the first two and `false` on the third. **`padded_channels` must be non-empty on `drift_idle` and `tendril_reach`** — that is the padding rule pinning the blend channel each of them does not drive.

`author_clip(loop=True)` refuses a cycle that does not close and the refusal carries the measured difference. If it refuses, the key values are wrong — fix them; do not drop `loop`.

- [ ] **Step 4: Preview each clip**

```bash
uv run python -c "import sys; sys.path.insert(0,'evals'); import live_call; print(live_call.call('preview_clip', {'root':'drifter_root','clip':'pulse_swim'})['result'].get('path'))"
```

Read the returned sheet for each of the three. The bell should visibly contract in `pulse_swim`, and the tendril should visibly curl in `tendril_reach`. If a preview is blown-out white, that is #704 — an unexplained oddity, not a product defect; note it and continue.

- [ ] **Step 5: Commit**

```bash
git add evals/drifter_live.py
git commit -m "feat(#743): three takes - pose_ik residual on a ten-joint chain recorded"
```

---

### Task 8: Material, export, byte gate, baseline

**Files:**
- Modify: `evals/drifter_live.py`
- Create: `evals/drifter_live/baseline.json` (generated)

**Interfaces:**
- Consumes: everything above.
- Produces: `build_material(mesh) -> dict`, `sample_deformation() -> list[dict]`, `export_and_check() -> dict`, `main() -> int`.

- [ ] **Step 1: UV, generate a texture, apply it — and probe #714**

```python
# append to evals/drifter_live.py

TEXTURE_PATH = os.path.join(OUT_DIR, "drifter_basecolor.png")


def _write_texture(path: str) -> None:
    """Generate the base colour to disk so the fixture has no art dependency.

    Deterministic and re-runnable: the same bytes every run.
    """
    import struct
    import zlib
    size = 256
    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for x in range(size):
            v = (x ^ y) & 0xFF
            rows += bytes((40 + v // 3, 70 + v // 4, 120 + v // 5))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)


def build_material(mesh: str) -> dict:
    """One flat set, through the ONLY door that exists.

    Three of apply_texture_recipe's four recipes build PROCEDURAL nodes
    (noise, ramp, layered); only file_texture creates a `file` node with a
    path (maya_plugin/handlers/texture_recipes.py:104). Procedural nodes
    are exactly what #714 says the FBX drops.
    """
    os.makedirs(OUT_DIR, exist_ok=True)
    _write_texture(TEXTURE_PATH)

    uv = call("uv_atlas", {"names": [mesh], "project": "auto",
                           "normalize": True}).get("result") or {}
    call("assign_pbr", {"mesh": mesh, "name": "drifter_mat",
                        "params": {"metalness": 0.0, "roughness": 0.6}})
    filed = call("apply_texture_recipe",
                 {"mesh": mesh, "recipe": "file_texture", "slot": "color",
                  "params": {"path": TEXTURE_PATH}}).get("result") or {}
    # The #714 probe: a PROCEDURAL recipe on the normal slot, exported
    # alongside the file texture, so the bytes can say which survives.
    proc = call("apply_texture_recipe",
                {"mesh": mesh, "recipe": "noise_bump", "slot": "normal"}
                ).get("result") or {}
    return {"uv_all_inside": uv.get("all_inside"),
            "texture_path": TEXTURE_PATH,
            "file_texture": filed, "procedural_probe": proc}
```

Run it and confirm `uv_all_inside` is `true`.

- [ ] **Step 2: Sample the deformation, seven frames per clip**

```python
# append to evals/drifter_live.py

SAMPLES_PER_CLIP = 7        # first, last, and five evenly spaced interior
RIM_RING_VERTS: list = []   # filled by _find_landmarks
APEX_VERT = -1
TIP_VERT = -1


def _find_landmarks(mesh: str) -> dict:
    """Pick the landmark vertices ONCE, at rest, by index.

    Indices - not positions - so every later sample reads the SAME
    vertices. A metric that re-picks "the highest vertex" each frame is
    measuring a different point each frame.
    """
    code = (
        "import maya.cmds as cmds\n"
        "pts = cmds.xform('%s.vtx[*]', q=True, ws=True, t=True)\n"
        "P = [pts[i:i+3] for i in range(0, len(pts), 3)]\n"
        "apex = max(range(len(P)), key=lambda i: P[i][1])\n"
        "tip = min(range(len(P)), key=lambda i: P[i][1])\n"
        "rim = [i for i, p in enumerate(P) if abs(p[1] - %f) < 0.06]\n"
        "result = {'apex': apex, 'tip': tip, 'rim': rim[:64], "
        "'count': len(P)}\n" % (mesh, RIM_Y)
    )
    res = call("execute_python", {"code": code}).get("result") or {}
    return json.loads(res.get("result_repr", "{}").replace("'", '"'))


def sample_deformation(mesh: str, clips: list, landmarks: dict) -> list:
    """Frame-invariant metrics at seven frames of every clip."""
    out = []
    for clip in clips:
        start, end = int(clip["start_frame"]), int(clip["end_frame"])
        step = (end - start) / float(SAMPLES_PER_CLIP - 1)
        for n in range(SAMPLES_PER_CLIP):
            frame = int(round(start + step * n))
            code = (
                "import maya.cmds as cmds\n"
                "cmds.currentTime(%d)\n"
                "pts = cmds.xform('%s.vtx[*]', q=True, ws=True, t=True)\n"
                "P = [pts[i:i+3] for i in range(0, len(pts), 3)]\n"
                "result = {'apex': P[%d], 'tip': P[%d], "
                "'rim': [P[i] for i in %r]}\n"
                % (frame, mesh, landmarks["apex"], landmarks["tip"],
                   landmarks["rim"])
            )
            res = call("execute_python", {"code": code}).get("result") or {}
            got = json.loads(res.get("result_repr", "{}").replace("'", '"'))
            out.append({
                "clip": clip["name"], "frame": frame,
                "time_s": (frame - start) / float(FPS),
                "rim_diameter": dm.rim_diameter(got["rim"]),
                "apex_to_tip": dm.apex_to_tip(got["apex"], got["tip"]),
            })
    return out
```

- [ ] **Step 3: Export and gate the bytes**

```python
# append to evals/drifter_live.py

FBX_PATH = os.path.join(OUT_DIR, "drifter.fbx")


def export_and_check(mesh: str) -> dict:
    """The scene is BLIND to what the exporter writes - #629's whole lesson."""
    os.makedirs(OUT_DIR, exist_ok=True)
    res = call("export_fbx", {"path": FBX_PATH, "metres_per_unit": 1.0,
                              "nodes": [mesh, ROOT],
                              "include_skins": True,
                              "include_animation": True}).get("result") or {}
    problems = []
    if abs(float(res.get("metres_per_unit", 0.0)) - 1.0) > 1e-9:
        problems.append("metres_per_unit is %r" % res.get("metres_per_unit"))
    if not res.get("skin"):
        problems.append("no skin facts in the exported bytes")
    shapes = res.get("shapes") or {}
    anim = res.get("animation") or {}
    take_names = [t.get("name") for t in (anim.get("takes") or [])]
    for want in ("drift_idle", "pulse_swim", "tendril_reach"):
        if want not in take_names:
            problems.append("take %r absent (takes: %r)" % (want, take_names))
    return {"export": res, "take_names": take_names, "shapes": shapes,
            "problems": problems}
```

**Look up takes BY NAME.** An FBX also carries Maya's always-present `Take 001`, so position is not identity (#695). And #718 measured a multi-take FBX carrying **three curve records per plug** — any per-take assertion must key on stable identity, never on a uid that changes between exports.

- [ ] **Step 4: Write `baseline.json` and run the whole gate**

```python
# append to evals/drifter_live.py

def main() -> int:
    ping = preflight()
    build_skeleton()
    geo = build_geometry()
    skin = bind_and_weight(geo["mesh"])
    mirror = probe_mirror(geo["mesh"])
    blend = build_blendshapes(geo["mesh"])
    takes = author_takes()
    material = build_material(geo["mesh"])
    landmarks = _find_landmarks(geo["mesh"])
    samples = sample_deformation(geo["mesh"], takes["clips"], landmarks)
    exported = export_and_check(geo["mesh"])

    looping = [c["name"] for c in takes["clips"] if c.get("loop")]
    baseline = {
        "ticket": 743,
        "maya_pid": ping.get("pid"),
        "plugin_digest": ping.get("loaded_digest"),
        "fps": FPS,
        "tolerances": {"seam": SEAM_TOL, "compare": COMPARE_TOL},
        "vertex_ceiling": VERTEX_CEILING,
        "mesh": geo["mesh"], "vertices": geo["vertices"],
        "joints": len(JOINTS),
        "max_influences_bound": MAX_INFLUENCES,
        "skin": skin, "mirror_probe": mirror,
        "blend_targets": blend["aliases"],
        "clips": takes["clips"], "looping_clips": looping,
        "ik": takes["ik"],
        "material": material,
        "landmarks": landmarks,
        "samples": samples,
        "fbx": {"path": FBX_PATH, "take_names": exported["take_names"],
                "skin": exported["export"].get("skin"),
                "shapes": exported["shapes"],
                "metres_per_unit": exported["export"].get("metres_per_unit"),
                "bytes": exported["export"].get("bytes")},
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(BASELINE_PATH, "w") as fh:
        json.dump(baseline, fh, indent=2, sort_keys=True)

    problems = list(exported["problems"])
    if geo["vertices"] > VERTEX_CEILING:
        problems.append("vertex ceiling exceeded: %d" % geo["vertices"])
    if skin["unweighted"]:
        problems.append("%d unweighted vertices" % skin["unweighted"])

    for p in problems:
        print("FAIL: %s" % p)
    print("baseline written to %s" % BASELINE_PATH)
    print("over_four vertices (Unity will truncate these): %d"
          % skin["facts"]["over_four"])
    print("pose_ik residual on a 10-joint chain: %r"
          % takes["ik"].get("residual"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
```

Run the whole gate:

```bash
uv run python evals/drifter_live.py
```

Expected: exit 0, `baseline.json` written, and the two headline numbers printed.

- [ ] **Step 5: Commit the gate and its baseline**

```bash
git add evals/drifter_live.py evals/drifter_live/baseline.json evals/drifter_live/drifter_basecolor.png
git commit -m "feat(#743): drifter live gate - build, skin, takes, material, byte gate, baseline"
```

Do **not** `git add -A` — `evals/golem_rerun_665/out_v4/` is another agent's untracked work and must never be committed.

---

### Task 9: The consumer gate — C# and policy

**Files:**
- Create: `evals/drifter_unity.py`
- Test: `tests/test_drifter_unity.py`

**Interfaces:**
- Consumes: `evals/drifter_live/baseline.json`; `drifter_metrics.compare_samples` / `seam_violations`.
- Produces: `verify(declared, measured) -> dict` returning `{"ok": bool, "problems": [str], "detail": {...}}`; `UNITY_MEASURE_CS` (str); `_steps_text() -> str`; `main(argv) -> int`.

- [ ] **Step 1: Write the failing policy test**

```python
# tests/test_drifter_unity.py
"""#743 consumer-gate POLICY, exercised without any Unity at all.

#718's consumer gate found three defects and ALL THREE were in the gate,
not the product. A policy that only ever runs against a live editor is a
policy nobody has tested.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "evals"))

import drifter_unity as du  # noqa: E402

DECLARED = {
    "joints": 105,
    "blend_targets": ["bell_crease", "tendril_flare"],
    "looping_clips": ["drift_idle", "pulse_swim"],
    "tolerances": {"seam": 1e-4, "compare": 1e-3},
    "clips": [{"name": "drift_idle", "duration_s": 2.0},
              {"name": "pulse_swim", "duration_s": 1.0},
              {"name": "tendril_reach", "duration_s": 1.2}],
    "samples": [
        {"clip": "pulse_swim", "frame": 0, "rim_diameter": 1.2,
         "apex_to_tip": 3.9},
        {"clip": "pulse_swim", "frame": 30, "rim_diameter": 1.2,
         "apex_to_tip": 3.9},
    ],
}


def _measured(**over):
    base = {
        "bones": 105,
        "blend_shapes": ["bell_crease", "tendril_flare"],
        "clips": [{"name": "drift_idle", "length": 2.0},
                  {"name": "pulse_swim", "length": 1.0},
                  {"name": "tendril_reach", "length": 1.2}],
        "bones_per_vertex_max": 4,
        "samples": [dict(s) for s in DECLARED["samples"]],
    }
    base.update(over)
    return base


def test_a_clean_import_passes():
    assert du.verify(DECLARED, _measured())["ok"] is True


def test_a_missing_clip_fails():
    m = _measured()
    m["clips"] = [c for c in m["clips"] if c["name"] != "pulse_swim"]
    out = du.verify(DECLARED, m)
    assert out["ok"] is False
    assert any("pulse_swim" in p for p in out["problems"])


def test_a_wrong_bone_count_fails():
    out = du.verify(DECLARED, _measured(bones=104))
    assert out["ok"] is False
    assert any("bone" in p.lower() for p in out["problems"])


def test_a_missing_blend_shape_fails():
    out = du.verify(DECLARED, _measured(blend_shapes=["bell_crease"]))
    assert out["ok"] is False
    assert any("tendril_flare" in p for p in out["problems"])


def test_deformation_outside_tolerance_fails():
    m = _measured()
    m["samples"][1]["apex_to_tip"] = 3.5
    out = du.verify(DECLARED, m)
    assert out["ok"] is False
    assert any("apex_to_tip" in p for p in out["problems"])


def test_a_loop_that_reopens_in_unity_fails():
    m = _measured()
    m["samples"][1]["rim_diameter"] = 1.3
    out = du.verify(DECLARED, m)
    assert out["ok"] is False
    assert any("seam" in p.lower() for p in out["problems"])


def test_truncation_is_reported_but_does_not_fail_the_gate():
    """Unity capping at 4 is a MEASUREMENT, not a product defect."""
    out = du.verify(DECLARED, _measured(bones_per_vertex_max=4))
    assert out["ok"] is True
    assert "bones_per_vertex_max" in out["detail"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_drifter_unity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'drifter_unity'`

- [ ] **Step 3: Write the gate**

```python
# evals/drifter_unity.py
"""#743 consumer gate: the drifter, re-imported and DEFORMED by a real Unity.

The byte gate (evals/drifter_live.py) proves the FILE declares a skin
cluster, two blend-shape channels and three takes. This proves UNITY
reconstructs them - one SkinnedMeshRenderer, driven by curves on both the
bones and blendShape.<name> - and that the vertices it actually draws match
the vertices Maya computed.

Every comparison is a FRAME-INVARIANT distance (drifter_metrics), never a
coordinate and never a height. #737's check_poses reported 0 violations at
1 mm on a file that was 3.2 m wrong in a consumer, because it re-composed
poses the way OUR reader does. A shared metric cannot drift like that.

Driven through the unityMCP TOOLS by the agent, in a SCRATCH project. This
script holds the C# to run and the policy to judge its output; it never
talks to Unity itself - a Python process cannot call an MCP tool, only the
agent driving the conversation can.

If the Unity editor is not open, or `claude mcp list` shows unityMCP
unhealthy, report that and STOP. Do NOT fall back to a Unity CLI batchmode
run - CLAUDE.md, "MCP is the PRIMARY tooling path".

DECLARED is derived from evals/drifter_live/baseline.json and never
hand-restated, so the byte gate and this gate cannot silently disagree
about what was declared.

Usage:
    uv run python evals/drifter_unity.py                  # print the steps
    uv run python evals/drifter_unity.py --measurements m.json
Exit: 0 pass, 1 fail.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import drifter_metrics as dm  # noqa: E402

BASELINE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "drifter_live", "baseline.json")


def _load_baseline(path=BASELINE_PATH) -> dict:
    with open(path) as fh:
        return json.load(fh)


def verify(declared: dict, measured: dict) -> dict:
    """Pure policy. No Unity, no filesystem, no network."""
    problems = []
    tol = declared["tolerances"]

    if int(measured.get("bones", -1)) != int(declared["joints"]):
        problems.append("bone count is %r, declared %r"
                        % (measured.get("bones"), declared["joints"]))

    got_shapes = set(measured.get("blend_shapes") or [])
    for want in declared["blend_targets"]:
        if want not in got_shapes:
            problems.append("blend shape %r absent in Unity" % want)

    got_clips = {c["name"]: c for c in (measured.get("clips") or [])}
    for want in declared["clips"]:
        got = got_clips.get(want["name"])
        if got is None:
            problems.append("clip %r absent in Unity" % want["name"])
            continue
        delta = abs(float(got["length"]) - float(want["duration_s"]))
        if delta > 1e-3:
            problems.append("clip %r length %r, declared %r (delta %.3g)"
                            % (want["name"], got["length"],
                               want["duration_s"], delta))

    try:
        bad = dm.compare_samples(declared["samples"],
                                 measured.get("samples") or [],
                                 tol["compare"])
    except ValueError as exc:
        problems.append("incomplete measurement: %s" % exc)
        bad = []
    for b in bad:
        problems.append(
            "%s frame %d: %s declared %.6f, Unity %.6f (delta %.6f)"
            % (b["clip"], b["frame"], b["metric"], b["declared"],
               b["measured"], b["delta"]))

    seams = dm.seam_violations(measured.get("samples") or [],
                               declared["looping_clips"], tol["seam"])
    for s in seams:
        problems.append(
            "loop seam reopened in Unity: %s %s first %.6f last %.6f "
            "(delta %.6f)" % (s["clip"], s["metric"], s["first"],
                              s["last"], s["delta"]))

    return {"ok": not problems, "problems": problems,
            "detail": {"bones_per_vertex_max":
                       measured.get("bones_per_vertex_max"),
                       "deformation_violations": len(bad),
                       "seam_violations": len(seams)}}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_drifter_unity.py -v`
Expected: PASS, 7 passed

- [ ] **Step 5: Commit**

```bash
git add evals/drifter_unity.py tests/test_drifter_unity.py
git commit -m "test(#743): consumer-gate policy, tested without a live Unity"
```

---

### Task 10: The C# measurement and the live Unity run

**Files:**
- Modify: `evals/drifter_unity.py`
- Create: `evals/drifter_live/unity_measurement_2026-08-23.json` (generated, committed)

**Interfaces:**
- Consumes: Task 9's `verify()`.
- Produces: `UNITY_MEASURE_CS`, `_steps_text()`, `main(argv)`.

**`execute_code` snippets are METHOD BODIES.** `using` directives and LINQ are syntax errors there — that cost time on #718. Fully-qualify types (`UnityEngine.Mesh`, `System.Collections.Generic.List<>`) and write plain loops.

- [ ] **Step 1: Add the C# and the runner**

```python
# append to evals/drifter_unity.py

UNITY_MEASURE_CS = r"""
var path = "Assets/drifter.fbx";
var go = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.GameObject>(path);
var inst = (UnityEngine.GameObject)UnityEditor.PrefabUtility
    .InstantiatePrefab(go);
var smr = inst.GetComponentInChildren<UnityEngine.SkinnedMeshRenderer>();
var sb = new System.Text.StringBuilder();

sb.Append("{\"bones\":").Append(smr.bones.Length);
sb.Append(",\"blend_shapes\":[");
for (int i = 0; i < smr.sharedMesh.blendShapeCount; i++) {
    if (i > 0) sb.Append(",");
    sb.Append("\"").Append(smr.sharedMesh.GetBlendShapeName(i)).Append("\"");
}
sb.Append("]");

var bw = smr.sharedMesh.GetBonesPerVertex();
int maxBpv = 0;
for (int i = 0; i < bw.Length; i++) if (bw[i] > maxBpv) maxBpv = bw[i];
sb.Append(",\"bones_per_vertex_max\":").Append(maxBpv);

var clips = UnityEditor.AssetDatabase.LoadAllAssetsAtPath(path);
sb.Append(",\"clips\":[");
bool firstClip = true;
for (int i = 0; i < clips.Length; i++) {
    var clip = clips[i] as UnityEngine.AnimationClip;
    if (clip == null || clip.name.StartsWith("__preview")) continue;
    if (!firstClip) sb.Append(",");
    firstClip = false;
    sb.Append("{\"name\":\"").Append(clip.name).Append("\",\"length\":")
      .Append(clip.length.ToString("R")).Append("}");
}
sb.Append("]");

// SAMPLES: pose the rig, then BAKE - skinning AND blend shapes applied.
var apex = APEX_INDEX; var tip = TIP_INDEX;
var rim = new int[] { RIM_INDICES };
sb.Append(",\"samples\":[");
bool firstSample = true;
var plan = new string[] { SAMPLE_PLAN };
for (int p = 0; p < plan.Length; p++) {
    var bits = plan[p].Split('|');
    var clipName = bits[0];
    var frame = int.Parse(bits[1]);
    var t = float.Parse(bits[2]);
    UnityEngine.AnimationClip target = null;
    for (int i = 0; i < clips.Length; i++) {
        var c = clips[i] as UnityEngine.AnimationClip;
        if (c != null && c.name == clipName) target = c;
    }
    if (target == null) continue;
    target.SampleAnimation(inst, t);
    var baked = new UnityEngine.Mesh();
    smr.BakeMesh(baked, true);
    var v = baked.vertices;
    double best = 0.0;
    for (int a = 0; a < rim.Length; a++)
        for (int b = a + 1; b < rim.Length; b++) {
            var d = UnityEngine.Vector3.Distance(v[rim[a]], v[rim[b]]);
            if (d > best) best = d;
        }
    var span = UnityEngine.Vector3.Distance(v[apex], v[tip]);
    if (!firstSample) sb.Append(",");
    firstSample = false;
    sb.Append("{\"clip\":\"").Append(clipName).Append("\",\"frame\":")
      .Append(frame).Append(",\"rim_diameter\":").Append(best.ToString("R"))
      .Append(",\"apex_to_tip\":").Append(span.ToString("R")).Append("}");
    UnityEngine.Object.DestroyImmediate(baked);
}
sb.Append("]}");
UnityEngine.Object.DestroyImmediate(inst);
UnityEngine.Debug.Log(sb.ToString());
"""


def measure_cs(baseline: dict) -> str:
    """Fill the C# template from the baseline - never hand-restated."""
    lm = baseline["landmarks"]
    plan = ",".join(
        '"%s|%d|%.6f"' % (s["clip"], s["frame"], s["time_s"])
        for s in baseline["samples"])
    return (UNITY_MEASURE_CS
            .replace("APEX_INDEX", str(lm["apex"]))
            .replace("TIP_INDEX", str(lm["tip"]))
            .replace("RIM_INDICES", ", ".join(str(i) for i in lm["rim"]))
            .replace("SAMPLE_PLAN", plan))


def _steps_text() -> str:
    b = _load_baseline()
    return "\n".join([
        "#743 consumer gate - run these through the unityMCP TOOLS:",
        "",
        "0. claude mcp list -> unityMCP must be Connected. If it is not,",
        "   report it and STOP. No batchmode fallback.",
        "1. Build a SCRATCH project (never Demigol - its importer forces",
        "   importAnimation=false). Recipe: evals/multi_take_unity.py's",
        "   docstring, ~5 minutes.",
        "2. Copy %s into <scratch>/Assets/drifter.fbx" % b["fbx"]["path"],
        "3. mcp__unityMCP__manage_asset(action='modify', ...) to confirm",
        "   importAnimation and importBlendShapes are ON.",
        "4. mcp__unityMCP__execute_code with measure_cs(baseline).",
        "   NOTE: the snippet is a METHOD BODY - no `using`, no LINQ.",
        "5. Read the JSON out of the console, save it to a file, then:",
        "   uv run python evals/drifter_unity.py --measurements <file>",
    ])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--measurements")
    args = ap.parse_args(argv)
    baseline = _load_baseline()
    if not args.measurements:
        print(_steps_text())
        print("\n--- C# ---\n")
        print(measure_cs(baseline))
        return 0
    with open(args.measurements) as fh:
        measured = json.load(fh)
    out = verify(baseline, measured)
    for p in out["problems"]:
        print("FAIL: %s" % p)
    print("detail: %s" % json.dumps(out["detail"], sort_keys=True))
    print("PASS" if out["ok"] else "FAIL")
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Print the procedure and confirm the C# fills correctly**

```bash
uv run python evals/drifter_unity.py
```

Expected: the steps, then C# with real vertex indices substituted — no `APEX_INDEX` or `SAMPLE_PLAN` placeholders left.

- [ ] **Step 3: Run it against the live Unity**

Follow the printed steps using the unityMCP tools. Check `mcpforunity://instances` first and `set_active_instance` if more than one editor is connected.

**Read early failures as gate bugs.** #718's consumer gate found three defects and all three were in the gate. Two known traps: a joint's local rotation at bind is **not** zero in Unity, and `execute_code` snippets are method bodies.

- [ ] **Step 4: Save the measurement and judge it**

```bash
uv run python evals/drifter_unity.py --measurements evals/drifter_live/unity_measurement_2026-08-23.json
```

Record the result **whatever it is**. A deformation mismatch is the finding this fixture was built to produce, not a failure of the run. Note in particular whether `bones_per_vertex_max` came back as 4 against a Maya distribution containing vertices with more — that is Unity's truncation, measured.

- [ ] **Step 5: Commit and close out the ticket**

```bash
git add evals/drifter_unity.py evals/drifter_live/unity_measurement_2026-08-23.json
git commit -m "test(#743): Unity consumer measurements for the drifter fixture"
```

Then update [#743](http://localhost:3000/issues/743) with one `update_issue` call carrying the notes and the status: the measured tables (deformation declared vs Unity, bones-per-vertex, clip lengths, what the material carried), the `pose_ik` residual, the `mirror_weights` outcome, the #669 cylinder cost table, and the #714 verdict on the procedural slot. File a new ticket per genuine defect found; do not fix them here (spec §12).

---

## Self-Review

**Spec coverage.** §3.1 units → Task 8 Step 3. §3.2 rig → Task 3. §3.3 vertex budget → Task 4. §4.1 skinning and the deliberate 8-influence bind → Task 5. §4.2 two blend targets and the padding rule → Tasks 6 and 7 Step 3. §5 three takes → Task 7. §5.1 IK on a ten-joint chain → Task 7 Step 1. §5.2 loop seam, consumer side → Tasks 2 and 9. §6 material and §6.2 the #714 assertion → Task 8 Step 1. §7.1/7.2/7.3 the three artefacts → Tasks 8, 8, 9–10. §8 frame-invariant measurement → Tasks 1, 8 Step 2, 10 Step 1. §8.1 the rest of the consumer checks → Task 9. §9 the general rule → stated in the spec; no code needed. §10 standing rules → Global Constraints and Task 3 Step 1. §11 risks → Tasks 5 Step 3 and 7 Step 1 both record rather than fix.

**Two gaps I found and am naming rather than papering over:**

1. **`deform`'s exact parameter names are unverified** (Task 6 Step 1). I did not read `maya_deform`'s signature while writing this, so the task instructs reading it first rather than guessing. That is the honest handling — a plan that invents a signature produces a task that fails on its first run.
2. **`combine`, `duplicate`, `delete_objects` and `get_object_info` parameter names** are used from convention. If any refuses, read the signature from `src/maya_mcp/server.py` the same way.

**Type consistency.** `rim_diameter`/`apex_to_tip` are the metric names in `drifter_metrics.METRICS`, in the baseline `samples`, in the C# output, and in `verify()`. Clip identity is `name` everywhere in Python and `clip` inside a sample row. Landmarks are `apex`/`tip`/`rim` in both `_find_landmarks` and `measure_cs`.

**Placeholder scan.** No TBD/TODO. Every code step carries real code. The one deliberate deferral — `deform`'s signature — is an explicit read-it-first instruction with the exact command, not a "fill in details".
