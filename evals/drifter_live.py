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
    # The bind above already saturates max_influences at the cap (8), so
    # smoothing has no headroom left to exceed it here. A False on the flag
    # below is therefore inconclusive, not reassuring - it does not show that
    # smoothing RESPECTS the cap, only that this particular smoothing pass
    # never got a chance to test it. Answering the real question needs a
    # separate bind at a LOWER max_influences (leaving headroom), then
    # smoothing that, then checking whether the post-smooth max stays under
    # the cap it was bound at.
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
            "smoothing_changed_observed_max": (facts_after["max_influences"]
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
            "result": res.get("result"),
            # This probe never reads per-vertex influences before/after the
            # call, so "status: ok" / "unpaired_vertices: 0" cannot tell a
            # correct self-mirror apart from a silent overwrite on the
            # self-paired ribs (see docstring). Recorded explicitly so a
            # reader of the JSON alone does not mistake this for a
            # correctness signal.
            "not_a_correctness_signal": True}


BLEND_TARGETS = ("bell_crease", "tendril_flare")


def build_blendshapes(mesh: str) -> dict:
    """Two targets so each clip must PIN the other's channel to rest.

    That padding rule (maya_plugin/handlers/clip.py:537) is today only ever
    checked against itself. With two targets it becomes consumer-visible:
    if padding fails, Unity plays drift_idle with a crease stuck on.

    Targets are duplicates of the COMBINED, BOUND mesh (topology-identical,
    as create_blendshape requires), each sculpted with maya_deform and then
    baked (delete_history_after=True) so the target is a static shape with
    no live deformer coupling it to a handle someone could move later.

    `deform`'s real signature is (mesh, deformer, params, delete_history_after)
    - not the (name, kind, amount, axis) the plan guessed. There is no
    "taper" deformer; the whitelist is bend/flare/lattice/sculpt/sine/
    squash/twist/wave (maya_plugin/handlers/sculpt.py DEFORMER_WHITELIST).
    Both deformers below were tuned live against the actual mesh (see
    task-6-report.md for the measured max_displacement of each trial):

    - bell_crease: `squash`, factor=-0.6, bounded to a narrow band
      (+-0.15 m) centred on the rim (world Y=RIM_Y). Squash's negative
      factor pinches the cross-section inward; narrowing the bound keeps
      the pinch localised to the rim instead of squeezing the whole bell -
      visually a fold where the dome meets the tendril tops, which a
      linear skin blend cannot produce.
    - tendril_flare: `flare`, startFlare{X,Z}=1.4 at the tendril TIPS
      (world Y=TENDRIL_BOTTOM_Y) tapering to endFlare{X,Z}=1.0 at the rim,
      bounded +-1.5 m around the tendril span's midpoint so it covers the
      full RIM_Y..TENDRIL_BOTTOM_Y range without reaching into the bell.
    """
    crease_dup_res = call("duplicate", {"name": mesh,
                                        "new_name": "drifter_tgt_bell_crease"})
    if crease_dup_res.get("status") != "ok":
        raise SystemExit("duplicate(bell_crease) failed: %r"
                         % (crease_dup_res.get("error"),))
    crease = (crease_dup_res.get("result") or {}).get("name")
    crease_deform = call("deform", {
        "mesh": crease, "deformer": "squash",
        "params": {"factor": -0.6, "lowBound": -0.15, "highBound": 0.15,
                   "translate": [0.0, RIM_Y, 0.0]},
        "delete_history_after": True,
    })
    if crease_deform.get("status") != "ok":
        raise SystemExit("deform(bell_crease) failed: %r"
                         % (crease_deform.get("error"),))
    crease_moved = (crease_deform.get("result") or {}).get("max_displacement")

    flare_mid_y = (RIM_Y + TENDRIL_BOTTOM_Y) / 2.0
    flare_dup_res = call("duplicate", {"name": mesh,
                                       "new_name": "drifter_tgt_tendril_flare"})
    if flare_dup_res.get("status") != "ok":
        raise SystemExit("duplicate(tendril_flare) failed: %r"
                         % (flare_dup_res.get("error"),))
    flare = (flare_dup_res.get("result") or {}).get("name")
    flare_deform = call("deform", {
        "mesh": flare, "deformer": "flare",
        "params": {"startFlareX": 1.4, "startFlareZ": 1.4,
                   "endFlareX": 1.0, "endFlareZ": 1.0,
                   "lowBound": -1.5, "highBound": 1.5,
                   "translate": [0.0, flare_mid_y, 0.0]},
        "delete_history_after": True,
    })
    if flare_deform.get("status") != "ok":
        raise SystemExit("deform(tendril_flare) failed: %r"
                         % (flare_deform.get("error"),))
    flare_moved = (flare_deform.get("result") or {}).get("max_displacement")

    res = call("create_blendshape",
               {"mesh": mesh,
                "targets": [{"name": BLEND_TARGETS[0], "target_mesh": crease},
                            {"name": BLEND_TARGETS[1], "target_mesh": flare}]})
    if res.get("status") != "ok":
        raise SystemExit("create_blendshape failed: %r" % (res.get("error"),))
    result = res.get("result") or {}
    aliases = result.get("aliases") or result.get("targets") or []
    if len(aliases) != 2:
        raise SystemExit("expected 2 blendshape aliases, got %r" % (aliases,))
    return {"node": result.get("blend_shape"), "aliases": list(BLEND_TARGETS),
            "target_build_displacement": {"bell_crease": crease_moved,
                                          "tendril_flare": flare_moved},
            "raw": result}


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


BEND_AXIS = "Z"              # measured (Step 1b): see task-7-report.md table.
                              # +15deg on drifter_rib2_02 moves the rib TIP
                              # (drifter_rib2_03) radius from world Y AWAY
                              # from the bell axis (0.6 -> 0.6708m, +11.8%);
                              # -15deg moves it TOWARD the axis (0.6 ->
                              # 0.5155m, -14.1%). X gave EXACTLY zero tip
                              # movement (bone-aligned twist); Y gave a
                              # negligible 0.0005m. Negative amounts (as
                              # used by _bell_contract) therefore curl
                              # inward, matching the intended semantics.
TENDRIL_KEYS = 9            # keys per looping clip - the wave needs samples
IDLE_WAVE_DEG = 7.0
SWIM_WAVE_DEG = 16.0
WAVE_K = 0.55               # radians of phase LAG per joint down the chain
SWIM_DRAG = math.pi / 2.0   # tendrils trail the bell by a quarter cycle


def _rib_sway(amount: float) -> dict:
    """Every rib's second joint, rotated about the MEASURED bend axis."""
    return {rib_name(r, 2): _bend(amount) for r in range(1, RIBS + 1)}


def _bell_contract(amount: float) -> dict:
    """Ribs curling inward - the pulse."""
    out = {}
    for r in range(1, RIBS + 1):
        out[rib_name(r, 2)] = _bend(amount)
        out[rib_name(r, 3)] = _bend(amount * 0.6)
    return out


def _tendril_wave(phase: float, amp_deg: float,
                  per_tendril_offset: bool) -> dict:
    """A travelling wave down every tendril, not a rigid swing.

    Without this the tendrils are 80 of the rig's 105 joints and NOTHING
    keys them: they hang off the rib tips and translate with the body like
    eight stiff rods. This is how games fake trailing dynamics when they do
    not run cloth or dynamic bones - the same curve applied down the chain
    with a phase LAG, so the bend propagates from the bell to the tip.

    Rotation is about local X, which for a tendril joint IS world X: Task 3
    measured drifter_tendril2_05 jointOrient = [0,0,0], so tendril local
    frames are the world frame. A tendril hangs along -Y, so rotating about
    X swings it in the YZ plane - along the swim axis, which is what makes
    it read as drag rather than as a twist.

    per_tendril_offset=True gives each tendril its own phase (an organic,
    non-uniform shimmer - right for idle). False keeps all eight in phase
    so they trail TOGETHER, which is what drag looks like.
    """
    out = {}
    for t in range(1, TENDRILS + 1):
        ring = _rib_ring(t) if per_tendril_offset else 0.0
        for j in range(1, TENDRIL_JOINTS + 1):
            angle = amp_deg * math.sin(phase - WAVE_K * j + ring)
            out[tendril_name(t, j)] = [angle, 0.0, 0.0]
    return out


def _wave_keys(count: int, duration_s: float, amp_deg: float,
               per_tendril_offset: bool, drag: float = 0.0) -> list:
    """Phase runs a FULL 2*pi across the clip so the loop closes exactly.

    author_clip(loop=True) refuses a cycle whose last key does not equal
    its first, and carries the measured difference in the refusal. A whole
    number of periods makes that exact rather than nearly-exact.
    """
    keys = []
    for n in range(count):
        frac = n / float(count - 1)
        phase = 2.0 * math.pi * frac - drag
        keys.append({"time_s": duration_s * frac,
                     "rotations": _tendril_wave(phase, amp_deg,
                                                per_tendril_offset)})
    return keys


def _bend(amount: float) -> list:
    """Rotation vector about the MEASURED rib bend axis (Step 1b)."""
    if BEND_AXIS is None:
        raise SystemExit("run the Step 1b bend-axis measurement first - the "
                         "ribs carry non-trivial per-joint orientations and "
                         "the curl axis is not assumable")
    return [amount if BEND_AXIS == "X" else 0.0,
            amount if BEND_AXIS == "Y" else 0.0,
            amount if BEND_AXIS == "Z" else 0.0]


def _merge(*maps) -> dict:
    out = {}
    for m in maps:
        out.update(m)
    return out


def author_takes() -> dict:
    ik = solve_tendril_reach()
    clips = []
    zero_w = {b: 0.0 for b in BLEND_TARGETS}

    # --- pulse_swim FIRST: bell contracts, tendrils TRAIL it --------------
    # Authored before drift_idle on purpose. padded_channels compares a
    # clip's own touched channels against the UNION of channels clips
    # ALREADY ON THE RIG touch - it is order-dependent. drift_idle keys
    # BOTH blend_weights explicitly at every key (rest padding never
    # applies there), so its only route to a non-empty padded_channels is
    # joint/root channels an earlier clip already keys and it does not:
    # pulse_swim's rib-3 joints (_bell_contract touches rib_name(r,3), idle
    # never does) and root_position (idle never keys it). Authored first,
    # drift_idle would compare against nothing and report padded_channels
    # empty - measured this way on the first run of this gate.
    #
    # The root glides forward and RETURNS. It must: author_clip(loop=True)
    # validates that the last key closes onto the first across rotations,
    # weights AND root position, so a net-displacing cycle is refused
    # outright. An in-place cycle still keys the translate channel - the
    # only one author_clip supports - and a game drives net travel itself.
    swim_keys = _wave_keys(TENDRIL_KEYS, 1.0, SWIM_WAVE_DEG,
                           per_tendril_offset=False, drag=SWIM_DRAG)
    for n, key in enumerate(swim_keys):
        frac = n / float(TENDRIL_KEYS - 1)
        pulse = math.sin(2.0 * math.pi * frac)
        key["rotations"] = _merge(key["rotations"],
                                  _bell_contract(-22.0 * max(pulse, 0.0)))
        key["blend_weights"] = {"bell_crease": max(pulse, 0.0),
                                "tendril_flare": 0.0}
        key["root_position"] = [0.0, APEX_Y, 0.35 * (1.0 - math.cos(
            2.0 * math.pi * frac))]
    swim = call("author_clip", {
        "root": ROOT, "name": "pulse_swim", "fps": FPS,
        "interpolation": "smooth", "loop": True,
        "keys": swim_keys})
    if swim.get("status") != "ok":
        raise SystemExit("pulse_swim refused: %r" % (swim.get("error"),))
    clips.append(swim["result"])

    # --- drift_idle: ribs sway, tendrils undulate out of phase -----------
    idle_keys = _wave_keys(TENDRIL_KEYS, 2.0, IDLE_WAVE_DEG,
                           per_tendril_offset=True)
    for n, key in enumerate(idle_keys):
        frac = n / float(TENDRIL_KEYS - 1)
        key["rotations"] = _merge(
            key["rotations"],
            _rib_sway(2.0 * math.sin(2.0 * math.pi * frac)))
        key["blend_weights"] = dict(zero_w)
    idle = call("author_clip", {
        "root": ROOT, "name": "drift_idle", "fps": FPS,
        "interpolation": "smooth", "loop": True,
        "keys": idle_keys})
    if idle.get("status") != "ok":
        raise SystemExit("drift_idle refused: %r" % (idle.get("error"),))
    clips.append(idle["result"])

    # --- tendril_reach: one-shot, IK-derived, no wave --------------------
    reach = call("author_clip", {
        "root": ROOT, "name": "tendril_reach", "fps": FPS,
        "interpolation": "smooth", "loop": False,
        "keys": [
            {"time_s": 0.0, "rotations": {j: [0.0, 0.0, 0.0]
                                          for j in ik["rotations"]},
             "blend_weights": {"bell_crease": 0.0, "tendril_flare": 0.0}},
            {"time_s": 1.2, "rotations": ik["rotations"],
             "blend_weights": {"bell_crease": 0.0, "tendril_flare": 1.0}},
        ]})
    if reach.get("status") != "ok":
        raise SystemExit("tendril_reach refused: %r" % (reach.get("error"),))
    clips.append(reach["result"])

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


if __name__ == "__main__":
    preflight()
    result = build_skeleton()
    print("built %d joints" % len(result.get("joints", [])))
