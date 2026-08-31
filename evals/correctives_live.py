"""#771 live gate: deltaMush relaxation and angle-fired correctives, measured
on the phase-2 humanoid - the ticket's own before/after pair.

The claim under test: `apply_delta_mush` measurably reduces the only skinning
artifact this project has ever recorded (edge stretch at the humanoid's
hips/shoulders under the harsh golem poses - crouch knee -104.7, extend
shoulder 115; residuals pinned in evals/humanoid_live/baseline.json), and
`add_corrective` makes a phase-5 blendshape target fire AT a joint angle
through a poseInterpolator, with the ramp, the guards, and the export story
all measured over the wire.

What only a live GUI Maya can prove here:
  1  the humanoid fixture reproduces its recorded baseline stretch
  2  the mush's measured reduction on that fixture (thresholds pinned from
     run 1, margins stated inline)
  3  judged renders - a ratio cannot see a silhouette collapse
  4  the corrective ramp through the real deformer chain (0 / half / 1)
  5  the driven-weight refusals over the wire
  6  export honesty: the deltaMush warning + byte-identical A/B, and the
     driven weight baking into per-take DeformPercent curves that a
     consumer's import actually plays back

DESTRUCTIVE: calls new_scene (twice - the final step imports the exported
FBX back into a fresh scene). Port 9878, the agent-launched Maya, per the
two-Maya policy - never point this at the user's 9877.

Run:  $env:MAYA_MCP_PORT='9878'; python evals/correctives_live.py --build
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import base64
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402
from maya_plugin.handlers import fbxbytes  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
OUT_DIR = os.path.join(_HERE, "correctives_live")
POSES_PATH = os.path.join(_HERE, "golem_delivery", "poses.json")
BASELINE_PATH = os.path.join(_HERE, "humanoid_live", "baseline.json")

MESH = "humanoid"

# ---------------------------------------------------------------------------
# thresholds - every one measured, provenance stated
# ---------------------------------------------------------------------------

# The humanoid gate's recorded residual stretch (baseline.json, #668 run of
# 2026-08-20): crouch 1.943, extend 2.026. The rebuild here must land in the
# same regime or the "reduction" would be measured against a different rig.
# 0.25 of slack covers bind nondeterminism without letting a 1.4-class rig
# (the mayapy standalone bind measured exactly that) impersonate the fixture.
BASELINE_REPRO_TOL = 0.25

# PINNED FROM RUN 2 (2026-08-31, agent Maya pid 65492 - run 1 ran at
# distanceWeight=0 and measured the SPIKE that made 1.0 the default, see
# probe_mush_spike.py): reductions crouch 1.943 -> 1.540 (0.403) and
# extend 2.026 -> 1.535 (0.491). Half the smaller measured reduction, so
# a mush that lost most of its bite fails while run-to-run noise (the
# baseline reproduced to 3 decimals) never can.
MUSH_MIN_REDUCTION = 0.2

# deltaMush is identity at rest (measured in the probe AND run 1: reset
# ratio 1.000000/1.000002 with the mush live).
REST_IDENTITY_TOL = 1e-3

# The corrective ramp, measured in the probe and run 1: 0.0 rest / 0.5 at
# half angle / 1.0 at the trigger. The half-angle band is wide because the
# CLAIM is monotonic interpolation, not a particular kernel.
HALF_WEIGHT_BAND = (0.25, 0.75)

# PINNED FROM RUN 2: the shoulder bulge sculpted below measured
# corrective_displacement 0.0602 m through the full chain; a tenth of it
# still proves real vertices moved while surviving sculpt-band jitter.
CORRECTIVE_DISPLACEMENT_MIN = 0.006

EXTEND_SHOULDER_DEG = 115.0   # the harshest recorded shoulder angle (#668)

CHECKS = []


def check(label, passed, detail=""):
    CHECKS.append((bool(passed), label))
    print("%s %s%s" % ("PASS" if passed else "FAIL", label,
                       ("  [%s]" % detail) if detail else ""))
    return bool(passed)


def send(command, params, timeout_s=300.0):
    try:
        return call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)


def ok(command, params, timeout_s=300.0):
    response = send(command, params, timeout_s)
    if response.get("status") != "ok":
        print("FAIL: %s: %s" % (command, json.dumps(response.get("error"))[:600]))
        sys.exit(1)
    return response.get("result") or {}


def refused(command, params, needle, label):
    """A wire call that MUST come back as a structured refusal naming `needle`."""
    response = send(command, params)
    err = response.get("error") or {}
    text = "%s %s" % (err.get("message", ""), err.get("hint", ""))
    check(label,
          response.get("status") != "ok" and needle in text,
          ("refused: %s" % err.get("message", ""))[:140]
          if response.get("status") != "ok"
          else "NOT refused - call returned ok")


def py(code, what, timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s), what)


def out(name):
    return os.path.join(OUT_DIR, name)


def preflight():
    ping = ok("ping", {}, timeout_s=15.0)
    plugin = ping.get("plugin") or {}
    process = ping.get("process") or {}
    if plugin.get("restart_required"):
        print("REFUSING: the answering Maya (pid %s) loaded a different "
              "plugin than the one on disk - restart it before gating."
              % process.get("pid"))
        sys.exit(2)
    print("gating against pid %s, scene %r" % (process.get("pid"),
                                               process.get("scene")))


# --- the humanoid fixture, copied from evals/humanoid_live.py (#668) -------
# (the constants ARE the fixture; importing them would couple two gates'
# lifecycles, the same call surfdetail_live made about the #770 proxy)

JOINTS = [
    {"name": "pelvis",     "position": [0.0,  1.00, 0.0]},
    {"name": "spine_01",   "position": [0.0,  1.15, 0.0], "parent": "pelvis"},
    {"name": "spine_02",   "position": [0.0,  1.30, 0.0], "parent": "spine_01"},
    {"name": "chest",      "position": [0.0,  1.45, 0.0], "parent": "spine_02"},
    {"name": "neck",       "position": [0.0,  1.60, 0.0], "parent": "chest"},
    {"name": "head",       "position": [0.0,  1.72, 0.0], "parent": "neck"},
    {"name": "L_shoulder", "position": [0.22, 1.50, 0.0], "parent": "chest"},
    {"name": "L_elbow",    "position": [0.45, 1.50, 0.0], "parent": "L_shoulder"},
    {"name": "L_wrist",    "position": [0.68, 1.50, 0.0], "parent": "L_elbow"},
    {"name": "R_shoulder", "position": [-0.22, 1.50, 0.0], "parent": "chest"},
    {"name": "R_elbow",    "position": [-0.45, 1.50, 0.0], "parent": "R_shoulder"},
    {"name": "R_wrist",    "position": [-0.68, 1.50, 0.0], "parent": "R_elbow"},
    {"name": "L_hip",      "position": [0.10, 0.95, 0.0], "parent": "pelvis"},
    {"name": "L_knee",     "position": [0.10, 0.50, 0.0], "parent": "L_hip"},
    {"name": "L_ankle",    "position": [0.10, 0.08, 0.0], "parent": "L_knee"},
    {"name": "L_toe",      "position": [0.10, 0.02, 0.14], "parent": "L_ankle"},
    {"name": "R_hip",      "position": [-0.10, 0.95, 0.0], "parent": "pelvis"},
    {"name": "R_knee",     "position": [-0.10, 0.50, 0.0], "parent": "R_hip"},
    {"name": "R_ankle",    "position": [-0.10, 0.08, 0.0], "parent": "R_knee"},
    {"name": "R_toe",      "position": [-0.10, 0.02, 0.14], "parent": "R_ankle"},
]

DIVISIONS = 8
BALL_DIVISIONS = 2
PARTS = [
    ("cylinder", "torso", DIVISIONS, [0.34, 0.62, 0.22], [0.0, 1.31, 0.0], None),
    ("sphere",   "head_p", BALL_DIVISIONS, [0.20, 0.26, 0.20], [0.0, 1.74, 0.0], None),
    ("sphere",   "ball_shoulder_L", BALL_DIVISIONS, [0.17, 0.17, 0.17], [0.22, 1.50, 0.0], None),
    ("sphere",   "ball_shoulder_R", BALL_DIVISIONS, [0.17, 0.17, 0.17], [-0.22, 1.50, 0.0], None),
    ("cylinder", "arm_L", DIVISIONS, [0.10, 0.56, 0.10], [0.42, 1.50, 0.0], [0, 0, 90]),
    ("cylinder", "arm_R", DIVISIONS, [0.10, 0.56, 0.10], [-0.42, 1.50, 0.0], [0, 0, 90]),
    ("sphere",   "ball_hip_L", BALL_DIVISIONS, [0.19, 0.19, 0.19], [0.10, 0.95, 0.0], None),
    ("sphere",   "ball_hip_R", BALL_DIVISIONS, [0.19, 0.19, 0.19], [-0.10, 0.95, 0.0], None),
    ("cylinder", "leg_L", DIVISIONS, [0.11, 1.00, 0.11], [0.10, 0.56, 0.0], None),
    ("cylinder", "leg_R", DIVISIONS, [0.11, 1.00, 0.11], [-0.10, 0.56, 0.0], None),
    ("cube",     "foot_L", DIVISIONS, [0.10, 0.08, 0.26], [0.10, 0.05, 0.06], None),
    ("cube",     "foot_R", DIVISIONS, [0.10, 0.08, 0.26], [-0.10, 0.05, 0.06], None),
]

EDGE_PROBE = """
import maya.cmds as cmds
import maya.api.OpenMaya as om
_mesh = %(mesh)r
_shape = cmds.listRelatives(_mesh, shapes=True, fullPath=True)[0]
_flat = cmds.xform(_mesh + '.vtx[*]', query=True, worldSpace=True,
                   translation=True)
_sel = om.MSelectionList()
_sel.add(_shape)
_it = om.MItMeshEdge(_sel.getDagPath(0))
_lengths = []
while not _it.isDone():
    _a = _it.vertexId(0) * 3
    _b = _it.vertexId(1) * 3
    _dx = _flat[_a] - _flat[_b]
    _dy = _flat[_a + 1] - _flat[_b + 1]
    _dz = _flat[_a + 2] - _flat[_b + 2]
    _lengths.append((_dx * _dx + _dy * _dy + _dz * _dz) ** 0.5)
    _it.next()
if %(store)s:
    CORRECTIVES_BIND_EDGES = list(_lengths)
_worst = 0.0
for _i in range(len(_lengths)):
    _b0 = CORRECTIVES_BIND_EDGES[_i]
    if _b0 > 1e-9:
        _r = _lengths[_i] / _b0
        if _r > _worst:
            _worst = _r
{'edges': len(_lengths), 'max_edge_ratio': round(_worst, 6)}
"""


def edge_probe(store, what):
    return py(EDGE_PROBE % {"mesh": "|" + MESH, "store": repr(bool(store))},
              what)


def biped_pose(joints_deg):
    """The #668 pose mapping - see humanoid_live.biped_pose for the measured
    frame derivation (local X is the twist axis on vertical chains)."""
    hip = joints_deg["hip"]
    knee = joints_deg["knee"]
    ankle = joints_deg["ankle"]
    shoulder = joints_deg["shoulder"]
    elbow = joints_deg["elbow"]
    spine = -hip / 6.0
    return {
        "L_hip": [0, -hip, 0], "R_hip": [0, -hip, 0],
        "L_knee": [0, -knee, 0], "R_knee": [0, -knee, 0],
        "L_ankle": [0, 0, -ankle], "R_ankle": [0, 0, -ankle],
        "L_shoulder": [0, 0, abs(shoulder)],
        "R_shoulder": [0, 0, abs(shoulder)],
        "L_elbow": [0, 0, abs(elbow)],
        "R_elbow": [0, 0, abs(elbow)],
        "spine_01": [0, -spine, 0], "spine_02": [0, -spine, 0],
        "chest": [0, -spine, 0],
    }


def render(tag):
    params = {"angles": ["front", "side"], "target": ["|" + MESH],
              "resolution": 1024, "samples": 3, "renderer": "arnold"}
    response = send("render_scene", params, timeout_s=900.0)
    if response.get("status") != "ok":
        params["renderer"] = "hw2"
        response = send("render_scene", params, timeout_s=900.0)
    if response.get("status") != "ok":
        check("render %s" % tag, False,
              json.dumps(response.get("error"))[:200])
        return
    written = []
    for image in response["result"]["images"]:
        path = out("correctives_%s_%s.png" % (tag, image["angle"]))
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(image["png_b64"]))
        written.append(path)
    check("render %s" % tag, len(written) == 2,
          "renderer=%s" % response["result"].get("renderer"))


def build_fixture(golem_poses):
    """Steps 1-2 of humanoid_live: mesh + skeleton + bind + craft pass."""
    ok("new_scene", {"confirm": True})
    for kind, name, divisions, scale, translate, rotate in PARTS:
        params = {"kind": kind, "name": name, "divisions": divisions,
                  "scale": scale, "translate": translate}
        if rotate:
            params["rotate"] = rotate
        ok("create_primitive", params)
    ok("combine", {"names": [p[1] for p in PARTS], "name": MESH})
    py("import maya.cmds as cmds\n"
       "cmds.makeIdentity(%r, apply=True, translate=False, rotate=True, "
       "scale=True, normal=0, preserveNormals=True)\n"
       "'ok'" % ("|" + MESH), "freeze the combined mesh")
    skeleton = ok("create_skeleton", {"joints": JOINTS})
    root = skeleton["root"]
    bind = ok("bind_skin", {"mesh": "|" + MESH, "root": root},
              timeout_s=600.0)
    check("the bind leaves NO vertex unowned",
          bind["unweighted_vertices"] == 0,
          "unweighted=%d" % bind["unweighted_vertices"])

    torso_faces = py(
        "import maya.cmds as cmds\n"
        "_f = cmds.polySelect(%r, extendToShell=0, noSelection=True)\n"
        "cmds.select([%r + '.f[%%d]' %% i for i in _f], replace=True)\n"
        "_bb = [round(v, 3) for v in cmds.exactWorldBoundingBox()]\n"
        "cmds.select(clear=True)\n"
        "{'faces': [int(i) for i in _f], 'bbox': _bb}"
        % ("|" + MESH, "|" + MESH), "torso shell faces")
    tb = torso_faces["bbox"]
    check("shell 0 is the torso",
          abs(tb[3] - tb[0] - 0.34) < 0.02 and abs(tb[4] - tb[1] - 0.62) < 0.02,
          "bbox=%s" % (tb,))
    ok("set_region_weights", {"mesh": "|" + MESH, "joint": "chest",
                              "faces": torso_faces["faces"], "weight": 0.85})
    ok("set_region_weights", {"mesh": "|" + MESH, "joint": "L_shoulder",
                              "within_radius_of": [0.32, 1.50, 0.0],
                              "radius": 0.11, "weight": 0.9,
                              "falloff": "linear"})
    ok("mirror_weights", {"mesh": "|" + MESH, "axis": "x"})
    ok("smooth_weights", {"mesh": "|" + MESH,
                          "joints": ["L_hip", "R_hip",
                                     "L_shoulder", "R_shoulder"],
                          "iterations": 2})
    report = ok("weight_report", {"mesh": "|" + MESH})
    check("the crafted weights are clean",
          report["unweighted_vertices"] == 0
          and report["max_influences_exceeded"] == 0,
          "unweighted=%d exceeded=%d" % (report["unweighted_vertices"],
                                         report["max_influences_exceeded"]))
    return root


def pose(root, golem_poses, name):
    ok("pose_skeleton", {"root": root,
                         "rotations": biped_pose(golem_poses[name]["joints_deg"])})


def main():
    if PORT == 9877:
        print("refusing to run on 9877: this eval discards the open scene "
              "(two-Maya policy). Launch a disposable Maya on 9878.")
        return 2
    if "--build" not in sys.argv:
        print(__doc__)
        return 0

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(POSES_PATH) as fh:
        golem_poses = json.load(fh)
    with open(BASELINE_PATH) as fh:
        baseline = json.load(fh)
    recorded = {p: baseline["poses"][p]["max_edge_ratio"]
                for p in ("crouch", "extend")}
    preflight()

    # ---- 1. fixture + baseline reproduction (the "before" side) ----------
    root = build_fixture(golem_poses)
    edge_probe(store=True, what="bind edge baseline")
    ok("setup_lighting", {"preset": "three_point"})

    before = {}
    for pname in ("crouch", "extend"):
        pose(root, golem_poses, pname)
        probe = edge_probe(store=False, what="%s pre-mush" % pname)
        before[pname] = probe["max_edge_ratio"]
        check("%s reproduces the recorded #668 baseline stretch" % pname,
              abs(probe["max_edge_ratio"] - recorded[pname]) < BASELINE_REPRO_TOL,
              "measured %.3f vs recorded %.3f (tol %.2f)"
              % (probe["max_edge_ratio"], recorded[pname], BASELINE_REPRO_TOL))
        render("%s_before" % pname)
        ok("reset_pose", {"root": root})

    # ---- 2. the mush, applied AT a harsh pose so its own report measures --
    pose(root, golem_poses, "crouch")
    mush = ok("apply_delta_mush", {"mesh": "|" + MESH}, timeout_s=600.0)
    check("the tool's own before-ratio agrees with this gate's probe",
          abs(mush["worst_edge_ratio_before"] - before["crouch"]) < 0.02,
          "tool %.3f vs gate %.3f" % (mush["worst_edge_ratio_before"],
                                      before["crouch"]))
    after = {}
    probe = edge_probe(store=False, what="crouch post-mush")
    after["crouch"] = probe["max_edge_ratio"]
    check("the tool's own after-ratio agrees with this gate's probe",
          abs(mush["worst_edge_ratio_after"] - after["crouch"]) < 0.02,
          "tool %.3f vs gate %.3f" % (mush["worst_edge_ratio_after"],
                                      after["crouch"]))
    render("crouch_after")
    ok("reset_pose", {"root": root})
    rest = edge_probe(store=False, what="rest with mush")
    check("deltaMush is identity at rest",
          abs(rest["max_edge_ratio"] - 1.0) < REST_IDENTITY_TOL,
          "ratio %.6f" % rest["max_edge_ratio"])

    pose(root, golem_poses, "extend")
    probe = edge_probe(store=False, what="extend post-mush")
    after["extend"] = probe["max_edge_ratio"]
    render("extend_after")
    ok("reset_pose", {"root": root})

    for pname in ("crouch", "extend"):
        check("the mush reduced %s stretch by at least %.2f" % (
                  pname, MUSH_MIN_REDUCTION),
              after[pname] <= before[pname] - MUSH_MIN_REDUCTION,
              "before %.3f -> after %.3f (reduction %.3f; recorded #668 "
              "residual was %.3f)"
              % (before[pname], after[pname], before[pname] - after[pname],
                 recorded[pname]))

    # ---- 3. export honesty: the warning, and the byte-identical drop ------
    # (run before the corrective section: it ends with the mush DELETED,
    # and create_blendshape must run on an unmushed mesh - a NEW blendShape
    # under a deltaMush hangs Maya's deformer reorder 20+ minutes, the
    # probe_bs_hang.py measurement that reordered this gate)
    fbx_a = out("humanoid_mush.fbx").replace("\\", "/")
    fbx_b = out("humanoid_nomush.fbx").replace("\\", "/")
    export_a = ok("export_fbx", {"path": fbx_a, "metres_per_unit": 1.0,
                                 "include_skins": True}, timeout_s=600.0)
    check("export warns that the deltaMush will be dropped",
          any("deltaMush" in w for w in export_a.get("warnings", [])),
          "warnings=%s" % json.dumps(export_a.get("warnings", []))[:200])
    ok("delete_objects", {"names": [mush["delta_mush"]]})
    export_b = ok("export_fbx", {"path": fbx_b, "metres_per_unit": 1.0,
                                 "include_skins": True}, timeout_s=600.0)
    check("without the mush, no deltaMush warning",
          not any("deltaMush" in w for w in export_b.get("warnings", [])))
    va = [round(c, 6) for m in fbxbytes.read_fbx(fbx_a).meshes for c in m]
    vb = [round(c, 6) for m in fbxbytes.read_fbx(fbx_b).meshes for c in m]
    check("the with-mush and without-mush exports carry IDENTICAL vertices",
          va == vb and len(va) > 0,
          "floats=%d max_diff=%s"
          % (len(va), max((abs(a - b) for a, b in zip(va, vb)), default=0.0)))

    # ---- 4. the corrective: a shoulder bulge that fires at extend's 115 ---
    sculpt = py(
        "import maya.cmds as cmds\n"
        "_dup = cmds.duplicate(%r, name='shoulder_fix_target')[0]\n"
        "_n = cmds.polyEvaluate(_dup, vertex=True)\n"
        "_moved = 0\n"
        "for _i in range(_n):\n"
        "    _p = cmds.pointPosition('%%s.vtx[%%d]' %% (_dup, _i), world=True)\n"
        "    _dx = _p[0] - 0.22\n"
        "    _dy = _p[1] - 1.50\n"
        "    _dz = _p[2]\n"
        "    if (_dx * _dx + _dy * _dy + _dz * _dz) ** 0.5 < 0.14:\n"
        "        cmds.move(_dx * 0.3, _dy * 0.3 + 0.03, _dz * 0.3,\n"
        "                  '%%s.vtx[%%d]' %% (_dup, _i), relative=True,\n"
        "                  worldSpace=True)\n"
        "        _moved += 1\n"
        "{'dup': cmds.ls(_dup, long=True)[0], 'moved': _moved}"
        % ("|" + MESH), "sculpt shoulder target", timeout_s=600.0)
    check("the sculpt moved a real vertex band", sculpt["moved"] > 20,
          "moved=%d" % sculpt["moved"])
    ok("create_blendshape", {
        "mesh": "|" + MESH,
        "targets": [{"name": "L_shoulder_fix",
                     "target_mesh": sculpt["dup"]}]}, timeout_s=600.0)

    corrective = ok("add_corrective", {
        "mesh": "|" + MESH, "target": "L_shoulder_fix",
        "joint": "L_shoulder",
        "rotation": [0.0, 0.0, EXTEND_SHOULDER_DEG]}, timeout_s=600.0)
    check("the corrective reads ~1 at its own trigger pose",
          corrective["weight_at_pose"] > 0.99,
          "weight_at_pose=%.4f" % corrective["weight_at_pose"])
    check("the corrective reads ~0 at rest",
          abs(corrective["weight_at_rest"]) < 0.01,
          "weight_at_rest=%.4f" % corrective["weight_at_rest"])
    check("the corrective moved real vertices through the full chain",
          corrective["corrective_displacement"] > CORRECTIVE_DISPLACEMENT_MIN,
          "displacement=%.4f (min %.3f)"
          % (corrective["corrective_displacement"],
             CORRECTIVE_DISPLACEMENT_MIN))

    interp = corrective["interpolator"]
    weight_plug = "%s.%s" % (corrective["blend_shape"], "L_shoulder_fix")
    ramp = py(
        "import maya.cmds as cmds\n"
        "_out = {}\n"
        "for _deg in (0.0, %r / 2.0, %r):\n"
        "    cmds.setAttr('L_shoulder.rotate', 0, 0, _deg)\n"
        "    _out[_deg] = round(cmds.getAttr(%r), 4)\n"
        "cmds.setAttr('L_shoulder.rotate', 0, 0, 0)\n"
        "_out"
        % (EXTEND_SHOULDER_DEG, EXTEND_SHOULDER_DEG, weight_plug),
        "measure the ramp")
    half = ramp[EXTEND_SHOULDER_DEG / 2.0]
    check("the ramp interpolates (half angle lands mid-band, monotonic)",
          ramp[0.0] < 0.01 and HALF_WEIGHT_BAND[0] < half < HALF_WEIGHT_BAND[1]
          and ramp[EXTEND_SHOULDER_DEG] > 0.99,
          "0deg=%.3f  %.1fdeg=%.3f  %.0fdeg=%.3f"
          % (ramp[0.0], EXTEND_SHOULDER_DEG / 2.0, half,
             EXTEND_SHOULDER_DEG, ramp[EXTEND_SHOULDER_DEG]))
    pose(root, golem_poses, "extend")
    render("extend_corrective")
    ok("reset_pose", {"root": root})

    # ---- 5. the guards, over the wire -------------------------------------
    refused("set_blendshape_weights",
            {"mesh": "|" + MESH, "weights": {"L_shoulder_fix": 0.5}},
            "corrective",
            "hand-setting a driven weight refuses with the corrective named")
    refused("author_clip",
            {"root": root, "name": "badclip", "fps": 24,
             "keys": [{"time_s": 0.0,
                       "blend_weights": {"L_shoulder_fix": 0.0}},
                      {"time_s": 1.0,
                       "blend_weights": {"L_shoulder_fix": 1.0}}]},
            "corrective",
            "keying a driven weight refuses instead of silently no-opping")
    refused("add_corrective",
            {"mesh": "|" + MESH, "target": "L_shoulder_fix",
             "joint": "L_shoulder", "rotation": [0.0, 0.0, 40.0]},
            "already a corrective",
            "a second corrective on a driven target refuses")
    refused("add_corrective",
            {"mesh": "|" + MESH, "target": "L_shoulder_fix",
             "joint": "L_shoulder", "rotation": [0.0, 0.0, 0.0]},
            "neutral",
            "an all-zero trigger rotation refuses")

    # Re-apply the mush now that the blendShape exists (measured instant on
    # the edit path), then prove the order guard over the wire: a NEW
    # blendShape on a mushed mesh must refuse, not hang.
    remush = ok("apply_delta_mush", {"mesh": "|" + MESH}, timeout_s=600.0)
    check("re-applying the mush after the corrective is clean",
          bool(remush["delta_mush"]), "node=%s" % remush["delta_mush"])
    bare = py(
        "import maya.cmds as cmds\n"
        "_c = cmds.polyCube(name='order_guard_cube')[0]\n"
        "_d = cmds.duplicate(_c, name='order_guard_target')[0]\n"
        "{'cube': cmds.ls(_c, long=True)[0],\n"
        " 'dup': cmds.ls(_d, long=True)[0]}", "order-guard fixtures")
    py("import maya.cmds as cmds\n"
       "_sk = cmds.createNode('joint', name='order_guard_joint')\n"
       "cmds.skinCluster('order_guard_joint', %r)\n"
       "cmds.deltaMush(%r)\n'ok'" % (bare["cube"], bare["cube"]),
       "skin+mush the order-guard cube")
    refused("create_blendshape",
            {"mesh": bare["cube"],
             "targets": [{"name": "hang_bait",
                          "target_mesh": bare["dup"]}]},
            "deltaMush",
            "a NEW blendShape under a mush refuses instead of hanging")

    # ---- 6. the clip bake: correctives ship in takes ----------------------
    for cname, peak in (("reachup", EXTEND_SHOULDER_DEG),
                        ("reachhalf", EXTEND_SHOULDER_DEG / 2.0)):
        ok("author_clip", {
            "root": root, "name": cname, "fps": 24,
            "keys": [
                {"time_s": 0.0, "rotations": {"L_shoulder": [0, 0, 0]}},
                {"time_s": 0.5, "rotations": {"L_shoulder": [0, 0, peak]}},
                {"time_s": 1.0, "rotations": {"L_shoulder": [0, 0, 0]}}]},
            timeout_s=600.0)
    fbx_c = out("humanoid_clips.fbx").replace("\\", "/")
    ok("export_fbx", {"path": fbx_c, "metres_per_unit": 1.0,
                      "include_skins": True, "include_animation": True},
       timeout_s=900.0)
    anim = fbxbytes.anim_facts(fbxbytes.read_fbx(fbx_c))
    for cname in ("reachup", "reachhalf"):
        deform = [t for t in anim["targets"]
                  if t["property"] == "DeformPercent"
                  and t["target"] == "L_shoulder_fix" and t["take"] == cname]
        rot = [t for t in anim["targets"]
               if t["property"] == "Lcl Rotation" and t["take"] == cname
               and t["target"] == "L_shoulder"]
        check("take %r carries a per-frame DeformPercent curve for the "
              "corrective" % cname,
              bool(deform) and bool(rot)
              and deform[0]["key_count"] == rot[0]["key_count"]
              and deform[0]["key_count"] >= 20,
              "deform_keys=%s rot_keys=%s"
              % (deform[0]["key_count"] if deform else None,
                 rot[0]["key_count"] if rot else None))

    # A consumer's-eye playback: reimport the file and read the CURVE the
    # importer wired to the weight (a constant curve would pass the
    # presence check above). Which take the importer activates is its own
    # business - run 2 measured that evaluating fixed timeline frames reads
    # a take whose span sits elsewhere as constant 0 - so the check reads
    # the connected curve's own keys: endpoints at rest, a real peak
    # (reachup peaks at 1.0, reachhalf at 0.5 - either proves tracking),
    # and the peak at mid-span, where the driver key sits.
    playback = py(
        "import maya.cmds as cmds\n"
        "cmds.file(new=True, force=True)\n"
        "cmds.file(%r, i=True)\n"
        "_bs = cmds.ls(type='blendShape')[0]\n"
        "_t = cmds.keyframe(_bs + '.L_shoulder_fix', query=True,\n"
        "                   timeChange=True) or []\n"
        "_v = cmds.keyframe(_bs + '.L_shoulder_fix', query=True,\n"
        "                   valueChange=True) or []\n"
        "{'keys': len(_t), 'first': round(_v[0], 4) if _v else None,\n"
        " 'last': round(_v[-1], 4) if _v else None,\n"
        " 'peak': round(max(_v), 4) if _v else None,\n"
        " 'peak_at': _t[_v.index(max(_v))] if _v else None,\n"
        " 'span': [_t[0], _t[-1]] if _t else None}"
        % fbx_c, "reimport playback", timeout_s=600.0)
    mid = ((playback["span"][0] + playback["span"][1]) / 2.0
           if playback["span"] else None)
    check("the imported curve plays the corrective (rest -> peak -> rest)",
          playback["keys"] >= 20
          and playback["first"] is not None and playback["first"] < 0.05
          and playback["last"] < 0.05
          and playback["peak"] > 0.4
          and mid is not None and abs(playback["peak_at"] - mid) <= 2.0,
          "keys=%s first=%s peak=%s@%s (span %s) last=%s"
          % (playback["keys"], playback["first"], playback["peak"],
             playback["peak_at"], playback["span"], playback["last"]))

    print("\n" + "=" * 72)
    print("JUDGE: crouch/extend before-vs-after renders must show the same")
    print("silhouette with softer creases - a mush that shrinks the figure")
    print("or melts the shoulder balls is a FAIL with every number green.")
    print("extend_corrective must show the bulge ON the raised shoulder.")
    print("Renders: %s" % OUT_DIR)
    print("=" * 72)

    failed = [label for passed, label in CHECKS if not passed]
    print("\n%d/%d passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
