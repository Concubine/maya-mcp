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
import drifter_metrics as dm                       # noqa: E402
from live_call import call, structured_result       # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "drifter_live")
BASELINE_PATH = os.path.join(OUT_DIR, "baseline.json")

# --- Global constraints, as constants -------------------------------------
FPS = 30
VERTEX_CEILING = 30000      # raised deliberately to afford round tendrils
                             # (#743 rework) - do NOT raise it further; lower
                             # BELL_DIVISIONS or TENDRIL_DIVISIONS instead
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
TENDRIL_SPAN = RIM_Y - TENDRIL_BOTTOM_Y          # 3.0 m nominal

ROOT = "drifter_root"


def _rib_ring(index: int) -> float:
    """Angle in radians for rib/tendril `index` (1-based), 45 deg apart."""
    return math.radians(45.0 * (index - 1))


def rib_name(rib: int, joint: int) -> str:
    return "drifter_rib%d_%02d" % (rib, joint)


def tendril_name(tendril: int, joint: int) -> str:
    return "drifter_tendril%d_%02d" % (tendril, joint)


# Per-tendril length factors. Deliberately irregular - eight identical
# clones is most of what makes a creature read as a prop. Every joint chain
# is scaled by its factor and its GEOMETRY matches, so no tip joint is ever
# left owning zero vertices (a joint owning nothing produces near-zero
# displacement, which looks exactly like success in any check that does not
# measure movement).
TENDRIL_LENGTH_FACTOR = (1.00, 0.78, 0.94, 0.66, 0.99, 0.83, 0.90, 0.72)


def tendril_step(tendril: int) -> float:
    """Joint spacing for one tendril, from its own length factor."""
    return (TENDRIL_SPAN * TENDRIL_LENGTH_FACTOR[tendril - 1]
            / TENDRIL_JOINTS)


# --- Joint-inside-geometry guard (#743) ------------------------------------
#
# Giving the tendrils rest-pose curvature with `bend` moved the GEOMETRY
# while an earlier build's joint chains stayed on their straight analytic
# line - every tendril bone ended up running through empty space beside its
# tube (measured: tendril 1 = 0.253 m at radius 0.055 = 4.6x, tendril 3 =
# 0.296 m at 0.045 = 6.6x, tendril 7 = 0.276 m at 0.043 = 6.4x; a joint
# inside its tube measures about one radius). `closestDistance` binding
# would have handed each tendril's vertices to whatever bone was nearest -
# for several tendrils, a NEIGHBOURING tendril's - and a turntable would
# have looked completely fine either way. It did look fine.
#
# So the build order inverts: geometry (with every deformer already
# applied) defines the skeleton, not the other way round. Rib/root joints
# keep their analytic positions - the bell is only ever radially rippled
# (`wave`), never bent, so they never left their geometry. Tendril joints
# are fit to the tube's MEASURED centreline after flare+bend: sample each
# height ring's vertices, take its centroid and mean radius, then resample
# that 11-point polyline at 10 equal ARC-LENGTH intervals (not just re-using
# the 11 construction rings verbatim - after a bend, equal height-steps are
# not exactly equal arc-length steps).
JOINT_INSIDE_TOL_RATIO = 2.0
RIB_RADIUS_FLOOR = 0.15     # metres - see rib_root_joint_specs()


def rib_root_joint_specs() -> tuple:
    """The 25 analytic joints (root + 8 ribs x 3) and their local radii.

    The bell is a single hollow shell with no wall thickness to measure, so
    a rib/root joint's "local radius" is not a tube radius - it is the
    joint's own analytic distance from the bell's vertical axis (RIM_R *
    frac), the natural size of the spoke-like structure it represents. That
    goes to 0 right at the apex, where a joint legitimately sits almost on
    the shell, so it is floored at RIB_RADIUS_FLOOR (0.15 m, roughly the
    scale of the apex region) rather than letting the ratio blow up on a
    joint that is doing nothing wrong.
    """
    specs = [{"name": ROOT, "position": [0.0, APEX_Y, 0.0]}]
    radius_of = {ROOT: RIB_RADIUS_FLOOR}
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
            radius_of[name] = max(radius, RIB_RADIUS_FLOOR)
            parent = name
    return specs, radius_of


def _tendril_ring_probe() -> list:
    """Vertex indices per height ring on an UNDEFORMED tendril cylinder.

    Every tendril is built with the same TENDRIL_DIVISIONS, so a
    polyCylinder's vertex layout - which ring a given vertex INDEX belongs
    to - is identical across all eight; this needs measuring only once, on
    a throwaway probe, and is valid after flare/bend because those
    reposition points without adding, removing or reordering them.

    Rings are read in OBJECT space, before any transform or deformer is
    applied. Within a ring, only vertices with a non-trivial radius are
    kept - a plain polyCylinder also has two polar cap-centre vertices at
    radius ~0, and including them would pull a ring's centroid toward the
    axis for no geometric reason.
    """
    probe_res = call("create_primitive",
                     {"kind": "cylinder", "name": "drifter_ring_probe",
                      "divisions": TENDRIL_DIVISIONS})
    if probe_res.get("status") != "ok":
        raise SystemExit("ring probe cylinder failed: %r"
                         % (probe_res.get("error"),))
    name = (probe_res.get("result") or {})["name"]
    code = (
        "import maya.api.OpenMaya as om\n"
        "sel = om.MSelectionList(); sel.add(%r)\n"
        "fn = om.MFnMesh(sel.getDagPath(0))\n"
        "pts = fn.getPoints(om.MSpace.kObject)\n"
        "buckets = {}\n"
        "for i, p in enumerate(pts):\n"
        "    r = (p.x ** 2 + p.z ** 2) ** 0.5\n"
        "    if r < 0.05:\n"
        "        continue\n"
        "    y = round(p.y, 5)\n"
        "    buckets.setdefault(y, []).append(i)\n"
        "ys = sorted(buckets.keys(), reverse=True)\n"
        "[buckets[y] for y in ys]\n"
    ) % (name,)
    exec_res = call("execute_python", {"code": code, "timeout_s": 60})
    if exec_res.get("status") != "ok":
        raise SystemExit("ring probe measurement call failed: %r"
                         % (exec_res.get("error"),))
    exec_result = exec_res.get("result") or {}
    if exec_result.get("traceback"):
        raise SystemExit("ring probe measurement raised:\n%s"
                         % exec_result["traceback"])
    rings = structured_result(exec_result, "ring probe")
    if len(rings) != TENDRIL_DIVISIONS + 1:
        raise SystemExit("expected %d rings from the probe cylinder, got %d"
                         % (TENDRIL_DIVISIONS + 1, len(rings)))
    del_res = call("delete_objects", {"names": [name]})
    if del_res.get("status") != "ok":
        raise SystemExit("delete_objects(ring probe) failed: %r"
                         % (del_res.get("error"),))
    return rings


def _tendril_ring_centroids(mesh: str, ring_indices: list) -> list:
    """World-space centroid and mean radius of each height ring, POST-deform.

    Returns a list of (position, radius) pairs, attachment ring first.
    """
    code = (
        "import maya.api.OpenMaya as om\n"
        "sel = om.MSelectionList(); sel.add(%r)\n"
        "fn = om.MFnMesh(sel.getDagPath(0))\n"
        "pts = fn.getPoints(om.MSpace.kWorld)\n"
        "rings = %r\n"
        "out = []\n"
        "for idxs in rings:\n"
        "    cx = sum(pts[i].x for i in idxs) / len(idxs)\n"
        "    cy = sum(pts[i].y for i in idxs) / len(idxs)\n"
        "    cz = sum(pts[i].z for i in idxs) / len(idxs)\n"
        "    radius = sum(((pts[i].x - cx) ** 2 + (pts[i].y - cy) ** 2\n"
        "                  + (pts[i].z - cz) ** 2) ** 0.5 for i in idxs) / len(idxs)\n"
        "    out.append(([cx, cy, cz], radius))\n"
        "out\n"
    ) % (mesh, ring_indices)
    exec_res = call("execute_python", {"code": code, "timeout_s": 60})
    if exec_res.get("status") != "ok":
        raise SystemExit("ring centroid call on %s failed: %r"
                         % (mesh, exec_res.get("error")))
    exec_result = exec_res.get("result") or {}
    if exec_result.get("traceback"):
        raise SystemExit("ring centroid measurement on %s raised:\n%s"
                         % (mesh, exec_result["traceback"]))
    return structured_result(exec_result, "ring centroids for %s" % mesh)


def _resample_polyline(points: list, radii: list, count: int) -> tuple:
    """Place `count` points at equal ARC-LENGTH intervals along a polyline.

    `points[0]`/`radii[0]` is the tube's attachment ring and is used only as
    the t=0 anchor - the rib tip already owns that position, so it is never
    itself returned. `points[-1]` is the tip, always returned exactly as
    the last (count-th) point. Radii are interpolated the same way each
    position is, so a fitted joint's local tube radius matches wherever
    along its segment it actually landed.
    """
    seg_lengths = [dm.distance(points[i], points[i + 1])
                  for i in range(len(points) - 1)]
    cumulative = [0.0]
    for length in seg_lengths:
        cumulative.append(cumulative[-1] + length)
    total = cumulative[-1]
    out_points, out_radii = [], []
    for i in range(1, count + 1):
        target = total * i / float(count)
        seg = len(seg_lengths) - 1
        for s in range(len(seg_lengths)):
            if cumulative[s + 1] >= target - 1e-9:
                seg = s
                break
        seg_len = seg_lengths[seg]
        t = 0.0 if seg_len < 1e-9 else (target - cumulative[seg]) / seg_len
        p0, p1 = points[seg], points[seg + 1]
        out_points.append([p0[k] + t * (p1[k] - p0[k]) for k in range(3)])
        r0, r1 = radii[seg], radii[seg + 1]
        out_radii.append(r0 + t * (r1 - r0))
    return out_points, out_radii


def fit_tendril_joint_specs(tendril: int, ring_data: list) -> tuple:
    """The 10 joint specs for one tendril, fit to its tube's measured centreline.

    `ring_data` is the 11 (position, radius) pairs from
    `_tendril_ring_centroids`, attachment ring first. Resampled to 10
    equal-arc-length points - matching the old analytic build's spacing
    semantics exactly (joint 1 one step below the rib tip, joint 10 at the
    very tip) while actually lying on the deformed tube.
    """
    ring_points = [p for p, _ in ring_data]
    ring_radii = [r for _, r in ring_data]
    positions, radii = _resample_polyline(ring_points, ring_radii,
                                          TENDRIL_JOINTS)
    specs = []
    radius_of = {}
    parent = rib_name(tendril, RIB_JOINTS)
    for j in range(1, TENDRIL_JOINTS + 1):
        name = tendril_name(tendril, j)
        specs.append({"name": name, "position": positions[j - 1],
                      "parent": parent})
        radius_of[name] = radii[j - 1]
        parent = name
    return specs, radius_of


def assert_joints_inside(mesh: str, joint_names: list, radius_of: dict) -> dict:
    """Every joint must lie within JOINT_INSIDE_TOL_RATIO local radii of the
    nearest vertex of `mesh`.

    This is the permanent guard against the #743 defect: a joint can bind,
    export and import cleanly while sitting metres from the geometry it is
    meant to drive, because `closestDistance` binding hands each vertex to
    WHATEVER bone happens to be nearest - even a neighbouring tendril's -
    and a turntable looks identical either way. Nothing else in this
    fixture catches that; it measures fine, exports fine, imports fine, and
    is wrong. Fails the run (raises) on any violation and reports the worst
    offenders either way.
    """
    code = (
        "import maya.api.OpenMaya as om\n"
        "sel = om.MSelectionList(); sel.add(%r)\n"
        "fn = om.MFnMesh(sel.getDagPath(0))\n"
        "verts = fn.getPoints(om.MSpace.kWorld)\n"
        "joints = %r\n"
        "out = []\n"
        "for jname in joints:\n"
        "    jp = cmds.xform(jname, q=True, ws=True, t=True)\n"
        "    best = None\n"
        "    for v in verts:\n"
        "        d2 = ((v.x - jp[0]) ** 2 + (v.y - jp[1]) ** 2\n"
        "              + (v.z - jp[2]) ** 2)\n"
        "        if best is None or d2 < best:\n"
        "            best = d2\n"
        "    out.append(best ** 0.5)\n"
        "out\n"
    ) % (mesh, joint_names)
    exec_res = call("execute_python", {"code": code, "timeout_s": 180})
    if exec_res.get("status") != "ok":
        raise SystemExit("assert_joints_inside call failed: %r"
                         % (exec_res.get("error"),))
    exec_result = exec_res.get("result") or {}
    if exec_result.get("traceback"):
        raise SystemExit("assert_joints_inside measurement raised:\n%s"
                         % exec_result["traceback"])
    distances = structured_result(exec_result, "joint-inside distances")
    rows = []
    for name, dist in zip(joint_names, distances):
        radius = radius_of[name]
        ratio = dist / radius if radius > 0 else math.inf
        rows.append({"joint": name, "distance": dist, "radius": radius,
                    "ratio": ratio})
    rows.sort(key=lambda r: r["ratio"], reverse=True)
    violations = [r for r in rows if r["ratio"] > JOINT_INSIDE_TOL_RATIO]
    if violations:
        raise SystemExit(
            "%d joint(s) exceed JOINT_INSIDE_TOL_RATIO=%.1f - worst: %s"
            % (len(violations), JOINT_INSIDE_TOL_RATIO,
               ", ".join("%s %.3fm/%.3fm=%.1fx"
                        % (r["joint"], r["distance"], r["radius"], r["ratio"])
                        for r in violations[:5])))
    return {"worst": rows[:10], "max_ratio": rows[0]["ratio"] if rows else None,
            "all": rows}


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


def start_scene() -> None:
    """A fresh scene, confirmed.

    confirm=True is required - new_scene refuses to discard the current
    scene without it (status "error", not raised), and a caller that
    ignores the status silently builds on top of whatever was already
    there. Measured live: three unconfirmed calls left drifter_root,
    drifter_root_001, drifter_root_002 (315 joints) in one scene.

    Called ONCE, before geometry - the build order is geometry-then-skeleton
    now (#743), so this can no longer live inside build_skeleton().
    """
    new_scene_res = call("new_scene", {"confirm": True})
    if new_scene_res.get("status") != "ok":
        raise SystemExit("new_scene failed: %r" % (new_scene_res.get("error"),))


def build_skeleton(joints: list) -> dict:
    """create_skeleton from an explicit, already-fitted `joints` list.

    Called AFTER the geometry exists (#743) - rib/root positions are
    analytic (rib_root_joint_specs), tendril positions are fit to the
    tube's measured centreline (fit_tendril_joint_specs), and it is the
    CALLER's job to assemble the full 105-joint list in parent-before-child
    order before calling this.
    """
    res = call("create_skeleton", {"joints": joints}).get("result") or {}
    if len(res.get("joints", [])) != len(joints):
        raise SystemExit("create_skeleton returned %d joints, expected %d"
                         % (len(res.get("joints", [])), len(joints)))
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
TENDRIL_DIVISIONS = 10      # cylinder: 20*d*(d+1) verts -> ~2200, ROUND
BELL_SCALE = [1.2, 0.9, 1.2]

# Per-tendril base thickness. Varied with the length factors so the eight
# read as a creature's appendages rather than eight copies of one prop.
TENDRIL_THICKNESS = (0.11, 0.06, 0.09, 0.05, 0.10, 0.07, 0.085, 0.055)

# Rest-pose curvature per tendril, in DEGREES, and a per-tendril yaw for
# the bend handle so no two curve the same way. Mixed signs on purpose -
# eight tendrils all bowing outward is as uniform as eight straight ones.
TENDRIL_BEND_DEG = (34.0, -22.0, 41.0, -30.0, 26.0, -38.0, 45.0, -25.0)
TENDRIL_BEND_YAW = (0.0, 38.0, -25.0, 61.0, -47.0, 14.0, -66.0, 29.0)


def build_deformed_parts() -> dict:
    """The bell and eight varied tendrils, EVERY deformer applied, UNCOMBINED.

    Geometry-then-skeleton (#743): this builds and deforms exactly what
    `build_geometry` used to build, but stops short of combining, because
    each tendril's joints must be fit to its tube's real centreline while
    it is still its own mesh - `combine` would merge vertex indices across
    all nine parts and the per-tendril ring probe indices computed by
    `_tendril_ring_probe` would no longer line up.

    Tendrils are CYLINDERS now that the ceiling allows it (30000): a cube
    gives a square cross-section that reads as a rod however it is
    textured, and cross-section is geometry, not material. Each one is
    tapered with `flare` - the deformer's own docs call it "THE taper, for
    a limb thick at one end and thin at the other" - and every one also
    gets a `bend`, replacing an earlier per-tendril `twist`. twist reported
    a genuine non-zero max_displacement but changed the silhouette not at
    all: flare keeps the cross-section perfectly circular, and twisting a
    circle yields the same circle. `bend` changes the silhouette, so its
    effect can be judged by looking rather than by trusting a displacement
    number. `bend` is also exactly what moved the tendrils' geometry off
    their old analytic joint chains - see the module-level comment above
    JOINT_INSIDE_TOL_RATIO.
    """
    parts = []
    tendril_diagnostics = []
    tendril_joint_specs = []
    tendril_radius_of = {}

    # --- the bell: a squashed sphere, then a RADIAL ripple for lobes -----
    bell_res = call("create_primitive",
                    {"kind": "sphere", "name": "drifter_bell",
                     "divisions": BELL_DIVISIONS,
                     "translate": [0.0, (APEX_Y + RIM_Y) / 2.0, 0.0],
                     "scale": BELL_SCALE})
    if bell_res.get("status") != "ok":
        raise SystemExit("create_primitive(bell) failed: %r"
                         % (bell_res.get("error"),))
    bell = (bell_res.get("result") or {})["name"]
    # `wave` is a CONCENTRIC RADIAL ripple bounded by minRadius/maxRadius -
    # a scalloped rim rather than a smooth dome edge. It takes NO
    # lowBound/highBound, unlike bend/squash/twist/flare/sine.
    #
    # The brief's original numbers (amplitude=0.055, wavelength=0.42,
    # minRadius=0.18) were measured LIVE to be a no-op: the tool's own
    # response carried the warning "wave moved the mesh by 0.0110369 (mesh
    # extent 1.92094) - that is not a visible deformation" - 0.6% of the
    # bell's extent, invisible in every capture. Retuned live against an
    # isolated probe sphere (same divisions/scale) until the ripple was
    # visibly a ridged rim rather than a smooth ellipsoid, without turning
    # the bell into a stack of rings: amplitude 0.18 (vs 0.055), wavelength
    # 0.25 (vs 0.42, more ripples across the radius), minRadius 0.35 (vs
    # 0.18, keeps the crown smooth and concentrates the ripple toward the
    # equator/rim). Measured max_displacement on the probe: 0.0363 m on a
    # 1.92 m extent (parts of #669's live-tuning pattern - see also the
    # blendshape deformers in build_blendshapes, tuned the same way).
    wave_res = call("deform", {"mesh": bell, "deformer": "wave",
                               "delete_history_after": True,
                               "params": {"amplitude": 0.18,
                                          "wavelength": 0.25,
                                          "minRadius": 0.35, "maxRadius": 1.0,
                                          "dropoff": -0.35}})
    if wave_res.get("status") != "ok":
        raise SystemExit("deform(bell wave) failed: %r"
                         % (wave_res.get("error"),))
    bell_wave_displacement = (wave_res.get("result") or {}).get(
        "max_displacement")
    bell_wave_warnings = (wave_res.get("result") or {}).get("warnings") or []
    parts.append(bell)

    # Vertex-index-per-ring map, measured ONCE (see _tendril_ring_probe) -
    # every tendril shares it because every tendril is built with the same
    # TENDRIL_DIVISIONS.
    ring_indices = _tendril_ring_probe()

    # --- eight tendrils, none of them identical --------------------------
    for t in range(1, TENDRILS + 1):
        theta = _rib_ring(t)
        length = TENDRIL_SPAN * TENDRIL_LENGTH_FACTOR[t - 1]
        thick = TENDRIL_THICKNESS[t - 1]
        tendril_res = call("create_primitive",
                           {"kind": "cylinder",
                            "name": "drifter_tendril_geo%d" % t,
                            "divisions": TENDRIL_DIVISIONS,
                            "translate": [RIM_R * math.cos(theta),
                                          RIM_Y - length / 2.0,
                                          RIM_R * math.sin(theta)],
                            "scale": [thick, length, thick]})
        if tendril_res.get("status") != "ok":
            raise SystemExit("create_primitive(tendril %d) failed: %r"
                             % (t, tendril_res.get("error")))
        name = (tendril_res.get("result") or {})["name"]

        # Taper: full thickness at the attachment, ending BLUNT-ish. An
        # earlier build used endFlare 0.18 and the tendrils came out as
        # needle points - the creature read as an urchin, not as something
        # soft that trails. 0.45 keeps the taper visible without the spike.
        flare_res = call("deform", {"mesh": name, "deformer": "flare",
                                    "delete_history_after": True,
                                    "params": {"startFlareX": 1.0,
                                               "startFlareZ": 1.0,
                                               "endFlareX": 0.45,
                                               "endFlareZ": 0.45,
                                               "curve": 0.5}})
        if flare_res.get("status") != "ok":
            raise SystemExit("deform(tendril %d flare) failed: %r"
                             % (t, flare_res.get("error")))
        flare_displacement = (flare_res.get("result") or {}).get(
            "max_displacement")
        flare_warnings = (flare_res.get("result") or {}).get("warnings") or []

        # Rest-pose SLACK. This replaces the twist above: curvature is in
        # DEGREES (#636) - "a visible hunch is 20-60" - and the handle is
        # rotated per tendril (radial angle + its own yaw offset) so each
        # one curves its own way rather than all eight bowing in parallel.
        bend_res = call("deform", {"mesh": name, "deformer": "bend",
                                   "delete_history_after": True,
                                   "params": {"curvature":
                                                  TENDRIL_BEND_DEG[t - 1],
                                              "rotate": [
                                                  0.0,
                                                  math.degrees(theta)
                                                  + TENDRIL_BEND_YAW[t - 1],
                                                  0.0]}})
        if bend_res.get("status") != "ok":
            raise SystemExit("deform(tendril %d bend) failed: %r"
                             % (t, bend_res.get("error")))
        bend_displacement = (bend_res.get("result") or {}).get(
            "max_displacement")
        bend_warnings = (bend_res.get("result") or {}).get("warnings") or []

        # Fit THIS tendril's 10 joints to its tube's measured centreline,
        # now that flare and bend have both been baked in
        # (delete_history_after=True on each deform call above). This is
        # the #743 fix: the joints are placed from what the mesh actually
        # is, not from the analytic line the geometry was originally
        # supposed to follow before `bend` moved it.
        ring_data = _tendril_ring_centroids(name, ring_indices)
        specs, radius_of = fit_tendril_joint_specs(t, ring_data)
        tendril_joint_specs.extend(specs)
        tendril_radius_of.update(radius_of)

        tendril_diagnostics.append({
            "tendril": t, "length": length, "thickness": thick,
            "bend_deg": TENDRIL_BEND_DEG[t - 1],
            "bend_yaw_deg": TENDRIL_BEND_YAW[t - 1],
            "flare_max_displacement": flare_displacement,
            "flare_warnings": flare_warnings,
            "bend_max_displacement": bend_displacement,
            "bend_warnings": bend_warnings,
            "fitted_ring_centroids": ring_data,
        })
        parts.append(name)

    return {"parts": parts,
            "bell_wave_max_displacement": bell_wave_displacement,
            "bell_wave_warnings": bell_wave_warnings,
            "tendril_diagnostics": tendril_diagnostics,
            "tendril_joint_specs": tendril_joint_specs,
            "tendril_radius_of": tendril_radius_of}


def combine_geometry(parts: list) -> dict:
    """Combine the deformed, already-fit-against parts into ONE mesh.

    Called AFTER build_skeleton (#743) - one mesh means one skinCluster
    means one SkinnedMeshRenderer in Unity, which is the shape a game
    character actually takes, but combining any earlier would have merged
    vertex indices across all nine parts before the per-tendril ring
    sampling in build_deformed_parts could use them.
    """
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
    return {"mesh": combined, "vertices": verts}


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
                              # RE-MEASURED live 2026-08-23 against the
                              # rebuilt rig (drifter_rib2_02, same target
                              # joint) - identical numbers reproduced
                              # (0.6->0.6708m at +15deg, 0.6->0.5155m at
                              # -15deg, X exactly 0.0 delta, Y 0.00048m) -
                              # Z stands confirmed, not just carried over.
TENDRIL_KEYS = 5            # keys per looping clip. Was 9: author_clip
#   evaluates the DEFORMED MESH at every key (it returns per_key displacement
#   measurements), so cost scales with vertices x keys x joints. Nine keys
#   authored three clips in ~12 min at 13,250 verts; at 23,922 verts with a
#   skin cluster and blend shapes it wedged Maya TWICE - one core pegged at
#   100% for 40+ min with memory dead flat at 4.4 GB, a spin, not progress.
#   Five keys still spans a full 2*pi of travelling wave.
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

    NEVER rotate a tendril joint about local X. Its child sits at
    translate [0.3, 0, 0] - along local X - because create_skeleton aims X
    down the bone. Rotation about X is a pure TWIST and bends nothing:
    measured 0.00 degrees of segment turn at 25 degrees of rotateX, against
    25.0 degrees for either Y or Z. On a square-section tendril that twist
    is nearly invisible, so it produced perfect-looking curves, a passing
    byte gate, and zero deformation. An earlier draft of this file rotated
    about X on the (wrong) theory that jointOrient=[0,0,0] means the local
    frame IS the world frame - it does not; jointOrient is relative to the
    PARENT, and the tendril chain inherits the rib tip's frame.

    Local Z swings the tendril RADIALLY (in/out from the bell axis) and
    local Y swings it TANGENTIALLY, both relative to that tendril's own
    ring angle. To make all eight trail the SAME world direction - which
    is what drag is - the desired world swing must be decomposed into each
    tendril's own Y and Z by its ring angle.

    per_tendril_offset=True gives each tendril its own phase and lets it
    swing radially (an organic, non-uniform shimmer - right for idle).
    False decomposes a single world-space drag direction per tendril, so
    the eight trail together.
    """
    out = {}
    for t in range(1, TENDRILS + 1):
        ring = _rib_ring(t)
        for j in range(1, TENDRIL_JOINTS + 1):
            if per_tendril_offset:
                # Idle: radial shimmer, each tendril phase-offset.
                angle = amp_deg * math.sin(phase - WAVE_K * j + ring)
                out[tendril_name(t, j)] = [0.0, 0.0, angle]
            else:
                # Swim: one world direction (-Z, opposing travel) resolved
                # into this tendril's radial (local Z) and tangential
                # (local Y) components.
                angle = amp_deg * math.sin(phase - WAVE_K * j)
                out[tendril_name(t, j)] = [0.0,
                                           -angle * math.cos(ring),
                                           -angle * math.sin(ring)]
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


def build_fixture() -> dict:
    """#743: geometry defines the skeleton, not the other way round.

    1. Fresh scene.
    2. Build the bell and all eight tendrils, every deformer applied
       (build_deformed_parts) - this is verbatim what the old
       build_geometry did, minus the combine.
    3. Fit each tendril's 10 joints to its tube's MEASURED centreline
       (done inside build_deformed_parts, per tendril, right after its
       deformers are baked).
    4. Rib/root joints stay analytic (rib_root_joint_specs) - the bell is
       only ever radially rippled, never bent, so they never left their
       geometry.
    5. create_skeleton from the combined (rib/root + tendril) spec list.
    6. THEN combine the parts into drifter_body.
    7. assert_joints_inside - every one of the 105 joints must lie within
       JOINT_INSIDE_TOL_RATIO local radii of the nearest vertex, or the
       run fails.
    """
    preflight()
    start_scene()

    geo = build_deformed_parts()

    rib_root_specs, rib_root_radius_of = rib_root_joint_specs()
    joints = rib_root_specs + geo["tendril_joint_specs"]
    if len(joints) != 105:
        raise SystemExit("assembled %d joint specs, expected 105" % len(joints))
    parentless = [j for j in joints if "parent" not in j]
    if len(parentless) != 1:
        raise SystemExit("%d parentless joints, expected exactly 1: %r"
                         % (len(parentless), [j["name"] for j in parentless]))
    radius_of = dict(rib_root_radius_of)
    radius_of.update(geo["tendril_radius_of"])

    skeleton = build_skeleton(joints)

    combined = combine_geometry(geo["parts"])

    joint_names = [j["name"] for j in joints]
    inside_report = assert_joints_inside(combined["mesh"], joint_names,
                                         radius_of)

    return {"vertices": combined["vertices"], "mesh": combined["mesh"],
            "joints": len(skeleton.get("joints", [])),
            "parentless": len(parentless),
            "joint_inside": inside_report,
            "tendril_diagnostics": geo["tendril_diagnostics"]}


if __name__ == "__main__":
    result = build_fixture()
    print("drifter_body: %d vertices (ceiling %d)"
         % (result["vertices"], VERTEX_CEILING))
    print("skeleton: %d joints, %d parentless"
         % (result["joints"], result["parentless"]))
    print("assert_joints_inside: max ratio %.3f (tolerance %.1f)"
         % (result["joint_inside"]["max_ratio"], JOINT_INSIDE_TOL_RATIO))
    for row in result["joint_inside"]["worst"]:
        print("  %-24s dist=%.4fm radius=%.4fm ratio=%.3fx"
             % (row["joint"], row["distance"], row["radius"], row["ratio"]))
