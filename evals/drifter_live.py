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


def measure_cylinder_coupling() -> dict:
    """The #669 datapoint: what a cylinder costs per unit of LENGTH detail.

    Recorded, not routed around. A tendril needs >=10 loops along its
    length; this says what that would cost in vertices if a cylinder
    supplied them. `divisions` multiplies BOTH axis subdivisions on a
    cylinder, which is #669 exactly - there is no way to ask a cylinder
    for more length loops without also paying for more around-the-axis
    loops.
    """
    out = []
    for d in (1, 4, 8, 12):
        create_res = call("create_primitive",
                          {"kind": "cylinder", "name": "drifter_probe_cyl",
                           "divisions": d})
        if create_res.get("status") != "ok":
            raise SystemExit("create_primitive(cylinder, divisions=%d) "
                             "failed: %r" % (d, create_res.get("error")))
        res = create_res.get("result") or {}
        name = res.get("name")
        info_res = call("get_object_info", {"name": name})
        if info_res.get("status") != "ok":
            raise SystemExit("get_object_info(%r) failed: %r"
                             % (name, info_res.get("error")))
        stats = (info_res.get("result") or {}).get("mesh_stats") or {}
        out.append({"divisions": d, "vertices": stats.get("verts"),
                    "faces": stats.get("faces")})
        delete_res = call("delete_objects", {"names": [name]})
        if delete_res.get("status") != "ok":
            raise SystemExit("delete_objects(%r) failed: %r"
                             % (name, delete_res.get("error")))
    return {"cylinder_divisions": out}


BELL_DIVISIONS = 4          # sphere: 400*d^2 faces -> ~6.4k
TENDRIL_DIVISIONS = 12      # cube: 6*d^2 faces -> ~864, 12 loops of length
BELL_SCALE = [1.2, 0.9, 1.2]
TENDRIL_SCALE = [0.08, TENDRIL_SPAN, 0.08]


def build_geometry() -> dict:
    """One bell plus eight tendrils, combined into ONE mesh.

    One mesh means one skinCluster means one SkinnedMeshRenderer in Unity,
    which is the shape a game character actually takes. Tendrils are
    CUBES, not cylinders - see measure_cylinder_coupling's docstring and
    the #669 datapoint it records.
    """
    parts = []
    bell_res = call("create_primitive",
                    {"kind": "sphere", "name": "drifter_bell",
                     "divisions": BELL_DIVISIONS,
                     "translate": [0.0, (APEX_Y + RIM_Y) / 2.0, 0.0],
                     "scale": BELL_SCALE})
    if bell_res.get("status") != "ok":
        raise SystemExit("create_primitive(bell) failed: %r"
                         % (bell_res.get("error"),))
    bell = (bell_res.get("result") or {})["name"]
    parts.append(bell)

    for t in range(1, TENDRILS + 1):
        theta = _rib_ring(t)
        tendril_res = call("create_primitive",
                           {"kind": "cube", "name": "drifter_tendril_geo%d" % t,
                            "divisions": TENDRIL_DIVISIONS,
                            "translate": [RIM_R * math.cos(theta),
                                          (RIM_Y + TENDRIL_BOTTOM_Y) / 2.0,
                                          RIM_R * math.sin(theta)],
                            "scale": TENDRIL_SCALE})
        if tendril_res.get("status") != "ok":
            raise SystemExit("create_primitive(tendril %d) failed: %r"
                             % (t, tendril_res.get("error")))
        name = (tendril_res.get("result") or {})["name"]
        parts.append(name)

    combine_res = call("combine", {"names": parts, "name": "drifter_body"})
    if combine_res.get("status") != "ok":
        raise SystemExit("combine failed: %r" % (combine_res.get("error"),))
    combined = (combine_res.get("result") or {})["name"]
    info_res = call("get_object_info", {"name": combined})
    if info_res.get("status") != "ok":
        raise SystemExit("get_object_info(%r) failed: %r"
                         % (combined, info_res.get("error")))
    stats = (info_res.get("result") or {}).get("mesh_stats") or {}
    verts = int(stats.get("verts") or 0)
    if verts > VERTEX_CEILING:
        raise SystemExit(
            "drifter_body has %d vertices, ceiling is %d - lower "
            "BELL_DIVISIONS or TENDRIL_DIVISIONS rather than raising the "
            "ceiling" % (verts, VERTEX_CEILING))
    return {"mesh": combined, "vertices": verts, "parts": parts}


def bind_and_weight(mesh: str) -> dict:
    """Bind ABOVE Unity's limit on purpose, then measure what we made.

    max_influences=8 constructs the truncation case; bound at the default
    4 the asset could never exceed Unity's cap and the question could not
    arise. over_four PREDICTS a consumer-side difference before we go
    looking for one.
    """
    bind_res = call("bind_skin", {"mesh": mesh, "root": ROOT,
                                  "max_influences": MAX_INFLUENCES,
                                  "method": "closestDistance"})
    if bind_res.get("status") != "ok":
        raise SystemExit("bind_skin failed: %r" % (bind_res.get("error"),))
    bind = bind_res.get("result") or {}
    if int(bind.get("unweighted_vertices", -1)) != 0:
        raise SystemExit(
            "%d unweighted vertices - a vertex no joint owns stays behind "
            "when the creature moves, and nothing looks wrong at bind time"
            % bind.get("unweighted_vertices"))

    before = call("weight_report", {"mesh": mesh}).get("result") or {}
    smooth_res = call("smooth_weights", {"mesh": mesh, "iterations": 2})
    if smooth_res.get("status") != "ok":
        raise SystemExit("smooth_weights failed: %r" % (smooth_res.get("error"),))
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


if __name__ == "__main__":
    preflight()
    result = build_skeleton()
    print("built %d joints" % len(result.get("joints", [])))
