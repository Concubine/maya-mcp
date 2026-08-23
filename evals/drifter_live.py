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


def build_skeleton() -> dict:
    # confirm=True is required - new_scene refuses to discard the current
    # scene without it (status "error", not raised), and a caller that
    # ignores the status silently builds on top of whatever was already
    # there. Measured live: three unconfirmed calls left drifter_root,
    # drifter_root_001, drifter_root_002 (315 joints) in one scene.
    new_scene_res = call("new_scene", {"confirm": True})
    if new_scene_res.get("status") != "ok":
        raise SystemExit("new_scene failed: %r" % (new_scene_res.get("error"),))
    res = call("create_skeleton", {"joints": JOINTS}).get("result") or {}
    if len(res.get("joints", [])) != len(JOINTS):
        raise SystemExit("create_skeleton returned %d joints, expected %d"
                         % (len(res.get("joints", [])), len(JOINTS)))
    return res


if __name__ == "__main__":
    preflight()
    result = build_skeleton()
    print("built %d joints" % len(result.get("joints", [])))
