"""Phase-2 gate for #668: the humanoid. ~20 joints, bound and craft-weighted,
posed through the golem five-pose set adapted to a biped - the poses exercise
exactly the joints that are hard (hips, shoulders, spine).

Measured checks (this script) + judged renders (the acceptance):

    1  build one combined humanoid mesh + 20-joint skeleton + bind
    2  weights craft: hand the torso shell back to the chest (by FACES),
       region-author the LEFT shoulder out on the arm, mirror to the right,
       smooth the hips/shoulders; weight_report must end clean
       (unweighted 0, exceeded 0) and L/R must be symmetric
    3  five poses (rest/crouch/extend/air/absorb from the golem set):
       per-mesh displacement > 0, shells unchanged, and the PER-EDGE
       tearing detector - every edge vs ITS OWN bind length (review item c)
    4  renders per pose - JUDGED: hips and shoulders must read as one
       continuous body, no candy-wrapper pinch, no tearing
    5  reset between poses, byte-identical topology at the end
    6  export include_skins from the bind pose; byte gate + baseline

DESTRUCTIVE: calls new_scene. Port 9878, the agent-launched Maya, per the
two-Maya policy - never point this at the user's 9877.

Run:  uv run python evals/humanoid_live.py
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
from maya_plugin.handlers.export import WEIGHT_SUM_TOL  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
OUT_DIR = os.path.join(_HERE, "humanoid_live")
POSES_PATH = os.path.join(_HERE, "golem_delivery", "poses.json")

MESH = "humanoid"
JOINT_COUNT = 20
# Per-edge ceiling (review item c): each edge vs ITS OWN bind length. Looser
# than the serpent's global 1.5x because hip/shoulder creases legitimately
# stretch single short edges harder than a uniform tube ever does.
EDGE_STRETCH_MAX = 1.8
# ...and a tear has to be BIG ENOUGH TO SEE, not just proportionally large.
# Measured on this mesh: the shortest bind edges are the circumference rings -
# 2.1 mm on a leg, 5.3 mm on the torso (#669's around-vs-along coupling puts
# 160 columns on every cylinder). A 1.3 mm difference between two neighbours -
# well under one pixel of the 640 px gate render of a 2 m figure - reads as a
# 1.6x "tear" on a 2 mm edge. So the ratio ceiling is applied to edges that
# actually GREW by a centimetre or more; the unfiltered worst ratio is still
# printed every pose, so the noise floor stays visible instead of hidden.
TEAR_GROWTH_MIN = 0.01   # metres
PIECES = 12              # torso, head, 2 shoulder + 2 hip balls, 2 arms,
                         # 2 legs, 2 feet -> shells

# The skeleton, hand-listed. This block IS the preset="biped" experiment:
# the verdict block at the end reports how it felt (spec: decide with the
# humanoid build in hand).
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

# Body pieces: kind, name, divisions, scale, translate, rotate. Divisions kept
# modest - the around-vs-along coupling (#669) makes length rows expensive;
# this eval is that ticket's second data point.
#
# The brief carried ONE divisions for every piece. Measured against
# modeling.build_unit_primitive: a sphere multiplies BOTH axes by 20, a
# cylinder only its circumference, so divisions=8 everywhere spent 25,600 of
# the mesh's 33,414 vertices on a HEAD that only rides the neck - and every
# weight op pays for them. The head drops to 2 (40x40); the deforming
# cylinders keep 8.
DIVISIONS = 8
BALL_DIVISIONS = 2
# The brief's pieces left measured 4 cm AIR at every seam: torso 1.02..1.62 vs
# legs 0.06..0.98, torso half-width 0.17 vs arms starting at x=0.21, torso top
# 1.62 vs head 1.66. At bind the renders hid it; under a posed hip the gap
# opened into a black band at the waist (first run's crouch render). Each limb
# now runs INTO the torso so the seam is covered by overlap, which is how a
# shells-not-welded body reads as one.
#
# The four BALLS are the second thing the renders forced. An arm whose stump
# sits 8 cm inboard of its pivot swings that stump straight out through the
# torso wall: at the extend pose (arms up 115 deg) the close-up showed the
# armpit torn open with the arm's end cap hanging in it, and the same notch
# appeared at the hips at 60 deg of flex. A ball centred ON the joint rotates
# about its own centre, so it covers that seam at every angle - the golem's
# own delivered rig solved it the same way and called them gaskets.
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


def py(code, what, timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s), what)


def out(name):
    return os.path.join(OUT_DIR, name)


# Captures every edge's CURRENT length; on the first call it also stores the
# list as the bind baseline in the plugin's persistent exec namespace, so the
# per-edge comparison (review item c) never round-trips thousands of floats.
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
    HUMANOID_BIND_EDGES = list(_lengths)
_worst = 0.0
_worst_i = -1
_seen = 0.0
_seen_i = -1
_seen_grew = 0.0
for _i in range(len(_lengths)):
    _b0 = HUMANOID_BIND_EDGES[_i]
    if _b0 <= 1e-9:
        continue
    _ratio = _lengths[_i] / _b0
    if _ratio > _worst:
        _worst = _ratio
        _worst_i = _i
    if _lengths[_i] - _b0 >= %(grow)r and _ratio > _seen:
        _seen = _ratio
        _seen_i = _i
        _seen_grew = _lengths[_i] - _b0
{'edges': len(_lengths),
 'shells': cmds.polyEvaluate(_mesh, shell=True),
 'vertices': len(_flat) // 3,
 'max_edge_ratio': round(_worst, 6),
 'worst_edge': _worst_i,
 'max_visible_ratio': round(_seen, 6),
 'worst_visible_edge': _seen_i,
 'worst_visible_growth': round(_seen_grew, 6)}
"""


def edge_probe(store, what):
    return py(EDGE_PROBE % {"mesh": "|" + MESH, "store": repr(bool(store)),
                            "grow": TEAR_GROWTH_MIN},
              what)


def biped_pose(joints_deg):
    """The golem pose abstraction (hip/knee/ankle/shoulder/elbow, degrees)
    on the biped, in each joint's OWN local frame.

    The brief mapped every leg bend onto local X ("legs bend about X"). That
    is only true of a world-aligned skeleton, and `create_skeleton` does not
    build one: it runs Maya's own orientJoint xyz/yup, aiming each joint's
    local X DOWN ITS BONE. Measured world axes of the built rig (first run):

        hip, knee     X=(0,-1,0)  Y=(-1,0,0)  Z=(0,0,-1)
        spine, chest  X=(0, 1,0)  Y=(-1,0,0)  Z=(0,0, 1)
        ankle         X=(0,-.39,.92) Y=(0,.92,.39) Z=(-1,0,0)
        L_shoulder    identity;  R_shoulder  X=(-1,0,0) Z=(0,0,-1)

    So for every vertical bone local X is the TWIST axis - the brief's pose
    spun the legs about their own length instead of swinging them, which is
    why the first run's crouch stood up straight and tore at the hips. A
    forward (world +X) pitch of t is local Y = -t on the vertical chains and
    local Z = -t on the ankle, whose bone already points forward-down.

    The arms need no per-side sign flip either: R_shoulder's frame is the
    L one turned 180 about Y, so the SAME local Z on both sides is already a
    mirrored world swing (+ raises both). The brief's hand-mirrored signs
    dropped one arm while lifting the other (first run's crouch render).
    """
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
              "resolution": 640, "samples": 3, "renderer": "arnold"}
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
        path = out("humanoid_%s_%s.png" % (tag, image["angle"]))
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(image["png_b64"]))
        written.append(path)
    check("render %s" % tag, len(written) == 2,
          "renderer=%s" % response["result"].get("renderer"))
    return written


def main():
    if PORT == 9877:
        print("refusing to run on 9877: this eval discards the open scene "
              "(two-Maya policy). Launch a disposable Maya on 9878.")
        return 2

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(POSES_PATH) as fh:
        golem_poses = json.load(fh)
    identity = py("import os\n{'pid': os.getpid()}", "identity")
    print("Maya on %d: pid %s, writing to %s\n"
          % (PORT, identity["pid"], OUT_DIR))

    # ---- 1. build one mesh, one skeleton, bind
    ok("new_scene", {"confirm": True})
    for kind, name, divisions, scale, translate, rotate in PARTS:
        params = {"kind": kind, "name": name, "divisions": divisions,
                  "scale": scale, "translate": translate}
        if rotate:
            params["rotate"] = rotate
        ok("create_primitive", params)
    # `names`, not `objects`: measured against combine._resolve_inputs, which
    # reads params["names"] and refuses anything else ("names must be a list
    # of at least two objects").
    ok("combine", {"names": [p[1] for p in PARTS], "name": MESH})
    frozen = py(
        "import maya.cmds as cmds\n"
        "cmds.makeIdentity(%r, apply=True, translate=False, rotate=True, "
        "scale=True, normal=0, preserveNormals=True)\n"
        "[round(v, 9) for v in cmds.getAttr(%r + '.scale')[0]]"
        % ("|" + MESH, "|" + MESH), "freeze the combined mesh")
    check("the humanoid carries no node scale before binding",
          frozen == [1.0, 1.0, 1.0], "scale=%s" % (frozen,))

    skeleton = ok("create_skeleton", {"joints": JOINTS})
    check("the skeleton built all %d joints" % JOINT_COUNT,
          len(skeleton["joints"]) == JOINT_COUNT,
          "root=%s" % skeleton["root"])
    root = skeleton["root"]

    bind = ok("bind_skin", {"mesh": "|" + MESH, "root": root},
              timeout_s=600.0)
    check("the bind leaves NO vertex unowned",
          bind["unweighted_vertices"] == 0,
          "unweighted=%d warnings=%s"
          % (bind["unweighted_vertices"], bind["warnings"]))
    at_bind = edge_probe(store=True, what="bind-pose edge baseline")
    print("  bind: %s" % json.dumps(at_bind))
    check("the combined mesh is %d shells" % PIECES,
          at_bind["shells"] == PIECES, "shells=%d" % at_bind["shells"])

    # ---- 2. the craft pass
    report0 = ok("weight_report", {"mesh": "|" + MESH})
    print("  bind report: unweighted=%d exceeded=%d hist=%s"
          % (report0["unweighted_vertices"],
             report0["max_influences_exceeded"],
             json.dumps(report0["histogram"])))

    # The torso comes back to the chest FIRST, by faces. Measured cause: a
    # closestDistance bind puts a shoulder among the four influences of torso
    # vertices as far down as the waist - at y=1.31 the shoulder is 0.220 away
    # and spine_01 0.219, so the max_influences=4 cut flips between the two
    # from one vertex to its neighbour. Swing that shoulder 115 deg and the
    # 0.06 stray weight alone moved one vertex 2.3 cm past its neighbour; the
    # bigger 0.42 weights up at the collar tore the torso top into flaps
    # (extend close-up, run 2). No sphere can undo it - the shoulder region and
    # the torso wall occupy the SAME space - so this is the `faces` form of the
    # tool, hard-assigning the whole shell. 0.85 rather than 1.0 keeps a
    # fifteen-percent spine/pelvis gradient alive so the waist still bends.
    torso_faces = py(
        "import maya.cmds as cmds\n"
        "_f = cmds.polySelect(%r, extendToShell=0, noSelection=True)\n"
        "cmds.select([%r + '.f[%%d]' %% i for i in _f], replace=True)\n"
        "_bb = [round(v, 3) for v in cmds.exactWorldBoundingBox()]\n"
        "cmds.select(clear=True)\n"
        "{'faces': [int(i) for i in _f], 'bbox': _bb}"
        % ("|" + MESH, "|" + MESH), "torso shell faces")
    # Shell 0 is the first piece united, but "first" is an assumption and this
    # hands 1282 faces to a weight edit - so the bbox is CHECKED against the
    # torso's authored size before it is used.
    tb = torso_faces["bbox"]
    check("shell 0 is the torso",
          abs(tb[3] - tb[0] - 0.34) < 0.02 and abs(tb[4] - tb[1] - 0.62) < 0.02,
          "faces=%d bbox=%s" % (len(torso_faces["faces"]), tb))
    reclaim = ok("set_region_weights", {
        "mesh": "|" + MESH, "joint": "chest",
        "faces": torso_faces["faces"], "weight": 0.85})
    check("the chest reclaimed the torso shell",
          reclaim["vertices_in_region"] > 0
          and reclaim["changed_vertices"] > 0
          and reclaim["unweighted_vertices"] == 0,
          "region=%d changed=%d sole_owner=%d"
          % (reclaim["vertices_in_region"], reclaim["changed_vertices"],
             reclaim["sole_owner_vertices"]))

    # The shoulder author sits OUT ON THE ARM at 0.32, not on the joint at
    # 0.22: measured, the torso wall reaches x=0.17, so a 0.11 sphere here
    # stops 0.04 short of it and can never hand torso vertices to an arm. It
    # still covers the outboard half of the shoulder ball and the upper arm.
    region = ok("set_region_weights", {
        "mesh": "|" + MESH, "joint": "L_shoulder",
        "within_radius_of": [0.32, 1.50, 0.0], "radius": 0.11,
        "weight": 0.9, "falloff": "linear"})
    check("the shoulder region took the authored weight",
          region["vertices_in_region"] > 0 and region["changed_vertices"] > 0,
          "region=%d changed=%d" % (region["vertices_in_region"],
                                    region["changed_vertices"]))

    mirror = ok("mirror_weights", {"mesh": "|" + MESH, "axis": "x"})
    check("the mirror wrote the right side from the left",
          mirror["mirrored_vertices"] > 0 and mirror["unweighted_vertices"] == 0,
          "mirrored=%d unpaired=%d changed=%d"
          % (mirror["mirrored_vertices"], mirror["unpaired_vertices"],
             mirror["changed_vertices"]))

    smooth = ok("smooth_weights", {
        "mesh": "|" + MESH,
        "joints": ["L_hip", "R_hip", "L_shoulder", "R_shoulder"],
        "iterations": 2})
    check("smoothing touched the hard joints and kept integrity",
          smooth["changed_vertices"] > 0
          and smooth["unweighted_vertices"] == 0
          and smooth["max_influences_exceeded"] == 0,
          "smoothed=%d changed=%d" % (smooth["smoothed_vertices"],
                                      smooth["changed_vertices"]))

    report = ok("weight_report", {"mesh": "|" + MESH})
    check("the crafted weights are clean",
          report["unweighted_vertices"] == 0
          and report["max_influences_exceeded"] == 0,
          "unweighted=%d exceeded=%d sum_err=%.2g"
          % (report["unweighted_vertices"],
             report["max_influences_exceeded"],
             report["max_weight_sum_error"]))
    by_joint = {p["joint"].split("|")[-1]: p["vertices"]
                for p in report["per_joint"]}
    lr = [("L_shoulder", "R_shoulder"), ("L_hip", "R_hip"),
          ("L_knee", "R_knee"), ("L_elbow", "R_elbow")]
    asym = {"%s/%s" % (a, b): (by_joint.get(a, 0), by_joint.get(b, 0))
            for a, b in lr
            if abs(by_joint.get(a, 0) - by_joint.get(b, 0))
            > 0.02 * max(by_joint.get(a, 0), by_joint.get(b, 1))}
    check("left and right ownership are symmetric within 2%", not asym,
          json.dumps(asym) if asym else
          "; ".join("%s=%d/%d" % (a, by_joint.get(a, 0), by_joint.get(b, 0))
                    for a, b in lr))

    # ---- 3+4. the five poses, measured and rendered
    ok("setup_lighting", {"preset": "three_point"})
    render("bind")
    baseline_poses = {}
    for pose_name in ("rest", "crouch", "extend", "air", "absorb"):
        rotations = biped_pose(golem_poses[pose_name]["joints_deg"])
        posed = ok("pose_skeleton", {"root": root, "rotations": rotations})
        inert = [m for m in posed["per_mesh"] if m["max_displacement"] < 1e-3]
        check("%s: the mesh moved with the skeleton" % pose_name,
              posed["max_displacement"] > 0.05 and not inert,
              "max_disp=%.4f displaced=%d"
              % (posed["max_displacement"], posed["displaced_vertices"]))
        probe = edge_probe(store=False, what="%s edge probe" % pose_name)
        check("%s: no edge grew %dmm+ AND past %.1fx ITS OWN bind length"
              % (pose_name, TEAR_GROWTH_MIN * 1000, EDGE_STRETCH_MAX),
              probe["max_visible_ratio"] <= EDGE_STRETCH_MAX,
              "visible=%.3f (edge %d, +%.1fmm); unfiltered worst=%.3f "
              "(edge %d)"
              % (probe["max_visible_ratio"], probe["worst_visible_edge"],
                 probe["worst_visible_growth"] * 1000,
                 probe["max_edge_ratio"], probe["worst_edge"]))
        check("%s: topology unchanged" % pose_name,
              probe["shells"] == PIECES
              and probe["edges"] == at_bind["edges"],
              "shells=%d edges=%d" % (probe["shells"], probe["edges"]))
        render(pose_name)
        baseline_poses[pose_name] = {
            "rotations_deg": rotations,
            "max_displacement": posed["max_displacement"],
            "max_edge_ratio": probe["max_edge_ratio"],
            "max_visible_edge_ratio": probe["max_visible_ratio"],
        }
        reset = ok("reset_pose", {"root": root})
        back = edge_probe(store=False, what="%s reset probe" % pose_name)
        check("%s: reset returned the mesh to bind" % pose_name,
              back["max_edge_ratio"] <= 1.0 + 1e-6,
              "max_edge_ratio=%.6f after reset (tool reported max_disp=%.4f)"
              % (back["max_edge_ratio"], reset["max_displacement"]))

    print("\n" + "=" * 72)
    print("JUDGE: each posed render must read as ONE CONTINUOUS BODY.")
    print("Candy-wrapper pinching at shoulders, a hip crease that tears")
    print("open, or a limb that stays behind is a FAIL even with every")
    print("number above green. Renders: %s" % OUT_DIR)
    print("=" * 72 + "\n")

    # ---- 6. skinned export from the bind pose
    fbx = out("humanoid.fbx")
    if os.path.exists(fbx):
        os.unlink(fbx)
    response = send("export_fbx", {"path": fbx.replace("\\", "/"),
                                   "metres_per_unit": 1.0,
                                   "include_skins": True}, timeout_s=600.0)
    exported = check("the skinned humanoid exports",
                     response.get("status") == "ok",
                     json.dumps(response.get("error"))[:300])
    if exported:
        result = response["result"]
        skin = result["skin"]
        print("  skin: %s" % json.dumps(skin))
        check("one deformer, one cluster per joint",
              skin["deformers"] == 1 and skin["clusters"] == JOINT_COUNT,
              "deformers=%d clusters=%d"
              % (skin["deformers"], skin["clusters"]))
        check("a bind pose, no unowned file vertices",
              skin["bind_pose_present"] is True
              and skin["unweighted_file_vertices"] == 0)
        check("file weight sums inside the exporter's pruning",
              skin["max_weight_sum_error"] is not None
              and skin["max_weight_sum_error"] < WEIGHT_SUM_TOL,
              "err=%r tol=%g" % (skin["max_weight_sum_error"],
                                 WEIGHT_SUM_TOL))
        facts = fbxbytes.read_fbx(fbx)
        limbs = [n for n in facts.nodes if n.kind == "LimbNode"]
        check("the bytes carry %d LimbNode joints" % JOINT_COUNT,
              len(limbs) == JOINT_COUNT, "LimbNodes=%d" % len(limbs))
        check("an independent byte read agrees with the tool",
              fbxbytes.skin_facts(facts) == skin)
        with open(out("baseline.json"), "w") as fh:
            json.dump({
                "fbx": "humanoid.fbx",
                "bytes": result["bytes"],
                "joint_models": len(limbs),
                "skin": skin,
                "world_bounds_min": result["world_bounds_min"],
                "world_bounds_max": result["world_bounds_max"],
                "poses": baseline_poses,
            }, fh, indent=2, sort_keys=True)
        print("  baseline: %s" % out("baseline.json"))

    print("\n" + "-" * 72)
    print("PRESET VERDICT INPUT (#668 open question): the skeleton above is")
    print("%d hand-listed joints, %d lines of literal data. Record on the"
          % (JOINT_COUNT, len(JOINTS)))
    print("ticket whether that was a papercut worth preset=\"biped\" or fine.")
    print("-" * 72)

    failed = [label for passed, label in CHECKS if not passed]
    print("\n%d/%d passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
