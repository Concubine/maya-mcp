"""Phase-6 gate for #695: animation clips on the #668 humanoid.

Two clips, both loop=True (the field-informed check this phase added):

    1  idle - 2.0 s breathing sway with a BLINK keyed mid-clip
       (exercises blend-weight keying), judged front-on
    2  walk - 1.2 s stride cycle with pelvis bob via root_position
       (exercises root translation), judged from the side; REPLACES the
       idle (the one-clip-at-a-time contract, asserted)

Rotation literals start from humanoid_live.biped_pose's MEASURED axis
table: create_skeleton aims local X down the bone, so the bend axis of a
vertical chain is its local Y, an ankle's is its local Z, and both
shoulders take the SAME local sign (R's frame is L's turned 180 about Y).
The SIGN of a hip's forward swing was re-measured here and is the
opposite of the one that table's prose implies - see the WALK_KEYS
comment for the probe numbers. Pixels outrank derivations - if a sheet
reads wrong, fix the literals from what the render shows and re-run.

TAKE NAMES ARE LOOKED UP BY NAME, not compared as a whole list. The plan
was written expecting exactly one take per file; Task 7's measurement
battery (tests/test_handlers_mayapy.py::TestClipExportInMaya::
test_the_measurements) then measured that Maya's FBX exporter ALWAYS
writes its own default "Take 001" alongside the take that
FBXExportSplitAnimationIntoTakes names after the clip - the file carries
["Take 001", "<clip>"]. That is not a defect (export.py's anim_violations
already validates by-name lookup for exactly this reason), so this gate
asserts the clip-named take is PRESENT and carries the right duration and
curves, mirroring the mayapy test rather than the plan's stale literal.

Measured checks (this script) + judged sheets (the acceptance):
    build humanoid + skeleton + bind + blink target -> author idle
    (loop) -> preview sheet -> export include_animation, byte-gated ->
    author walk (replaces, warning asserted) -> preview sheet -> export ->
    static-mutator refusal probed live -> delete_clip -> static export
    carries ZERO curves -> baseline.json.

DESTRUCTIVE: calls new_scene. Port 9878, the agent-launched Maya, per the
two-Maya policy - never point this at the user's 9877.

Run:  uv run python evals/clip_live.py
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

from humanoid_live import JOINTS, MESH, PARTS  # noqa: E402
from live_call import call, structured_result  # noqa: E402
from maya_plugin.handlers import fbxbytes  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
OUT_DIR = os.path.join(_HERE, "clip_live")
JOINT_COUNT = 20

# Blink target sculpt: a soft brow-drop on the head sphere (front of the
# head sits near (0, 1.80, 0.15) per the PARTS table). It only has to be
# VISIBLE at 256 px - the P5 gate measured that too-subtle sculpts render
# invisibly, so this uses the widened-literal lesson from day one.
#
# MEASURED (this run, 2026-08-20) and widened once more. The plan's
# [0, -.06, .02] wired a real 0.0441 m delta, but at the preview's default
# 320 px WHOLE-FIGURE framing the head spans ~20 px and the blink changed a
# 26x31 px patch by at most 102/255 at 640 px - the same "real but
# unreadable" shape the P5 gate hit with its brow. Two fixes, both applied:
# the preview renders at 640 px with zoom (below), and the drop is widened
# here. At 640 px / zoom 1.6 the pre-widening delta already moved a 41x47 px
# patch by 125/255 and read as a creased brow side by side; the wider one
# below is what makes it read inside a 16-cell flipbook.
BLINK_CENTER = [0.0, 1.80, 0.15]
BLINK_RADIUS = 0.16
BLINK_DELTA = [0.0, -0.09, 0.03]

# Preview framing, chosen from the pixels (above), not from the plan's
# defaults: at 320 px the figure occupied 108x147 px of the frame and
# neither the 3-degree sway nor the blink could be judged. 640 px with a
# modest zoom puts the figure at ~348x472 px with no near-plane clipping
# (the #670 risk was checked in the probe render and did not appear).
PREVIEW_RESOLUTION = 640
IDLE_ZOOM = 1.6
WALK_ZOOM = 1.5

IDLE_KEYS = [
    {"time_s": 0.0,
     "rotations": {"spine_01": [0, 0, 0], "chest": [0, 0, 0],
                   "L_shoulder": [0, 0, 0], "R_shoulder": [0, 0, 0]},
     "blend_weights": {"blink": 0.0}},
    {"time_s": 0.5,
     "rotations": {"spine_01": [0, -3, 0], "chest": [0, -3, 0],
                   "L_shoulder": [0, 0, 4], "R_shoulder": [0, 0, 4]},
     "blend_weights": {"blink": 0.0}},
    {"time_s": 1.0,
     "rotations": {"spine_01": [0, 0, 0], "chest": [0, 0, 0],
                   "L_shoulder": [0, 0, 0], "R_shoulder": [0, 0, 0]},
     "blend_weights": {"blink": 1.0}},
    {"time_s": 1.2,
     "rotations": {"spine_01": [0, 1, 0], "chest": [0, 1, 0],
                   "L_shoulder": [0, 0, 1], "R_shoulder": [0, 0, 1]},
     "blend_weights": {"blink": 0.0}},
    {"time_s": 2.0,
     "rotations": {"spine_01": [0, 0, 0], "chest": [0, 0, 0],
                   "L_shoulder": [0, 0, 0], "R_shoulder": [0, 0, 0]},
     "blend_weights": {"blink": 0.0}},
]

# The walk: contact (L forward) -> passing -> contact (R forward) ->
# passing -> contact (L forward, == first key: loop). The LEGS alternate via
# OPPOSITE L/R signs (vertical bones share one local-Y-is-world-X frame).
# The ARMS counter-swing via the SAME local-Y sign on both shoulders: the
# horizontal bones point opposite ways (+X / -X), so one world rotation
# about Y moves them fore/aft oppositely - hand-mirroring the signs would
# swing them IN PHASE, the same trap humanoid_live's docstring records for
# the golem poses. Ankles are local Z; pelvis bob rides the root.
#
# HIP SIGNS MEASURED, NOT DERIVED (2026-08-20, this gate's first run). The
# plan wrote the forward swing as local -Y on the hips, reading
# humanoid_live.biped_pose's table, whose prose calls local Y=-t "a forward
# (world +X) pitch". The humanoid FACES +Z (the toe joints sit at z=+0.14),
# and a probe of the built rig measured the opposite sign for fore/aft
# travel - with the plan's literals, at frame 0:
#
#     L_hip -25  ->  L_ankle z = -0.334 (BEHIND)   R_hip +20 -> +0.081
#     L_shoulder +15 -> L_wrist z = -0.118 (behind)
#
# i.e. the leg with the "forward" literal travelled BACKWARD, which put
# each arm in phase with the leg on its OWN side - the tin-soldier read,
# and the sheet showed it. Negating the hip values (only) restores the
# intended cycle: local +Y on a hip swings that leg toward +Z. The knee
# and ankle literals are already correct under the measured convention -
# negative knee = shin folds BACKWARD (the only way a knee bends),
# negative ankle = toe up - so they are left exactly as planned. Pixels
# outrank derivations; this is that rule being applied.
WALK_FPS = 30
WALK_KEYS = [
    {"time_s": 0.0,
     "rotations": {"L_hip": [0, 25, 0], "R_hip": [0, -20, 0],
                   "L_knee": [0, 5, 0], "R_knee": [0, -30, 0],
                   "L_ankle": [0, 0, -5], "R_ankle": [0, 0, 10],
                   "L_shoulder": [0, 15, 0], "R_shoulder": [0, 15, 0],
                   "L_elbow": [0, 0, 10], "R_elbow": [0, 0, 25]},
     "root_position": [0.0, 0.97, 0.0]},
    {"time_s": 0.3,
     "rotations": {"L_hip": [0, 0, 0], "R_hip": [0, 5, 0],
                   "L_knee": [0, -5, 0], "R_knee": [0, -45, 0],
                   "L_ankle": [0, 0, 0], "R_ankle": [0, 0, -15],
                   "L_shoulder": [0, 0, 0], "R_shoulder": [0, 0, 0],
                   "L_elbow": [0, 0, 15], "R_elbow": [0, 0, 15]},
     "root_position": [0.0, 1.01, 0.0]},
    {"time_s": 0.6,
     "rotations": {"L_hip": [0, -20, 0], "R_hip": [0, 25, 0],
                   "L_knee": [0, -30, 0], "R_knee": [0, 5, 0],
                   "L_ankle": [0, 0, 10], "R_ankle": [0, 0, -5],
                   "L_shoulder": [0, -15, 0], "R_shoulder": [0, -15, 0],
                   "L_elbow": [0, 0, 25], "R_elbow": [0, 0, 10]},
     "root_position": [0.0, 0.97, 0.0]},
    {"time_s": 0.9,
     "rotations": {"L_hip": [0, 5, 0], "R_hip": [0, 0, 0],
                   "L_knee": [0, -45, 0], "R_knee": [0, -5, 0],
                   "L_ankle": [0, 0, -15], "R_ankle": [0, 0, 0],
                   "L_shoulder": [0, 0, 0], "R_shoulder": [0, 0, 0],
                   "L_elbow": [0, 0, 15], "R_elbow": [0, 0, 15]},
     "root_position": [0.0, 1.01, 0.0]},
    {"time_s": 1.2,
     "rotations": {"L_hip": [0, 25, 0], "R_hip": [0, -20, 0],
                   "L_knee": [0, 5, 0], "R_knee": [0, -30, 0],
                   "L_ankle": [0, 0, -5], "R_ankle": [0, 0, 10],
                   "L_shoulder": [0, 15, 0], "R_shoulder": [0, 15, 0],
                   "L_elbow": [0, 0, 10], "R_elbow": [0, 0, 25]},
     "root_position": [0.0, 0.97, 0.0]},
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
        print("FAIL: %s: %s" % (command,
                                json.dumps(response.get("error"))[:600]))
        sys.exit(1)
    return response.get("result") or {}


def expect_refusal(command, params, needle, label):
    response = send(command, params)
    refused = (response.get("status") != "ok"
               and needle in json.dumps(response.get("error")))
    check(label, refused, json.dumps(response.get("error"))[:160])


def py(code, what, timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": code},
                                timeout_s), what)


def out(name):
    return os.path.join(OUT_DIR, name)


def take_named(anim, name):
    """The take this clip named, looked up by name (see the module
    docstring: Maya always writes its own 'Take 001' alongside it)."""
    if not anim:
        return None
    for take in anim.get("takes", []):
        if take.get("name") == name:
            return take
    return None


def save_preview(tag, result):
    saved = 0
    for image in result.get("images", []):
        path = out("%s_%s.png" % (tag, image["label"].replace("=", "")
                                  .replace(".", "_")))
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(image["png_b64"]))
        saved += 1
    check("preview %s rendered %d frames" % (tag, saved), saved >= 4,
          "frames=%s" % [f["frame"] for f in result.get("frames", [])])


def main():
    if PORT == 9877:
        print("refusing to run on 9877: this eval discards the open scene "
              "(two-Maya policy). Launch a disposable Maya on 9878.")
        return 2

    os.makedirs(OUT_DIR, exist_ok=True)
    identity = py("import os\n{'pid': os.getpid()}", "identity")
    print("Maya on %d: pid %s, writing to %s\n"
          % (PORT, identity["pid"], OUT_DIR))

    # ---- 1. humanoid + skeleton + bind + blink target
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
       "scale=True, normal=0, preserveNormals=True)\nTrue"
       % ("|" + MESH), "freeze the combined mesh")
    skeleton = ok("create_skeleton", {"joints": JOINTS})
    root = skeleton["root"]
    bind = ok("bind_skin", {"mesh": "|" + MESH, "root": root},
              timeout_s=600.0)
    check("the bind leaves NO vertex unowned",
          bind["unweighted_vertices"] == 0,
          "unweighted=%d" % bind["unweighted_vertices"])
    ok("duplicate", {"name": "|" + MESH, "new_name": "humanoid_blink"})
    ok("sculpt_ops", {"mesh": "|humanoid_blink", "ops": [
        {"op": "soft_move", "center": BLINK_CENTER, "radius": BLINK_RADIUS,
         "delta": BLINK_DELTA, "falloff": "smooth"}]})
    wired = ok("create_blendshape", {"mesh": "|" + MESH, "targets": [
        {"name": "blink", "target_mesh": "|humanoid_blink"}]})
    check("the blink target wired with a real delta",
          wired["targets"][0]["max_delta"] > 0.01,
          "max_delta=%.4f" % wired["targets"][0]["max_delta"])
    ok("setup_lighting", {"preset": "three_point"})

    # ---- 2. loop contract probed live: an open cycle must refuse
    bad = [dict(IDLE_KEYS[0]), dict(IDLE_KEYS[1])]
    bad[1] = dict(bad[1], time_s=2.0)
    expect_refusal("author_clip",
                   {"root": root, "name": "open", "fps": 30, "loop": True,
                    "keys": bad},
                   "does not close",
                   "loop=true refuses an open cycle with the measured delta")

    # ---- 3. the idle: authored, measured, previewed, exported
    idle = ok("author_clip", {"root": root, "name": "idle", "fps": 30,
                              "interpolation": "smooth", "loop": True,
                              "keys": IDLE_KEYS})
    check("idle: duration and frames measured back",
          abs(idle["duration_s"] - 2.0) < 1e-6 and idle["frames"] == 61,
          "duration=%.3f frames=%d" % (idle["duration_s"], idle["frames"]))
    moved = [k["max_displacement"] for k in idle["per_key"]]
    # the LAST key equals the first (loop), so its displacement vs frame 0
    # is ~0 BY CONSTRUCTION - that near-zero IS the measured loop closure.
    check("idle: every interior key measured real motion",
          moved[0] == 0.0 and all(m > 0.005 for m in moved[1:-1]),
          json.dumps([round(m, 4) for m in moved]))
    check("idle: the loop measurably closes (last key ~= first)",
          moved[-1] < 1e-3, "closure=%.5f" % moved[-1])
    check("idle: the blink channel is keyed",
          idle["keyed_weight_channels"] == ["blink"])
    preview = ok("preview_clip", {"root": root, "name": "idle",
                                  "angle": "front",
                                  "resolution": PREVIEW_RESOLUTION,
                                  "zoom": IDLE_ZOOM},
                 timeout_s=900.0)
    save_preview("idle", preview)

    # ---- 4. static mutators refuse while the clip exists
    expect_refusal("pose_skeleton",
                   {"root": root, "rotations": {"chest": [0, 0, 10]}},
                   "clip", "pose_skeleton refuses while the clip owns the "
                   "channels")
    expect_refusal("set_blendshape_weights",
                   {"mesh": "|" + MESH, "weights": {"blink": 0.5}},
                   "animation curves",
                   "set_blendshape_weights refuses on the keyed channel")

    # ---- 5. export the idle, byte-gated
    idle_fbx = out("idle.fbx")
    if os.path.exists(idle_fbx):
        os.unlink(idle_fbx)
    result = ok("export_fbx", {"path": idle_fbx.replace("\\", "/"),
                               "metres_per_unit": 1.0,
                               "include_skins": True,
                               "include_animation": True}, timeout_s=900.0)
    anim = result["animation"]
    print("  idle animation: %s" % json.dumps(anim)[:400])
    idle_take = take_named(anim, "idle")
    check("idle: the file carries a take named after the clip",
          idle_take is not None,
          json.dumps([t["name"] for t in anim["takes"]] if anim else None))
    check("idle: take duration matches within a frame",
          idle_take is not None
          and abs(idle_take["duration_s"] - 2.0) <= 1.0 / 30,
          "duration_s=%s" % (idle_take or {}).get("duration_s"))
    by = {(t["target"], t["property"]): t for t in anim["targets"]}
    idle_joints = ("spine_01", "chest", "L_shoulder", "R_shoulder")
    check("idle: every keyed joint bakes 61-key rotation curves",
          all(by.get((j, "Lcl Rotation"), {}).get("key_count") == 61
              and by.get((j, "Lcl Rotation"), {}).get("curves") == 3
              for j in idle_joints),
          json.dumps({j: by.get((j, "Lcl Rotation"), {}).get("key_count")
                      for j in idle_joints}))
    check("idle: the blink channel carries DeformPercent curves",
          ("blink", "DeformPercent") in by,
          json.dumps(sorted(str(k) for k in by)[:8]))
    check("idle: skins and shapes still green alongside animation",
          result["skin"]["deformers"] == 1
          and result["skin"]["clusters"] == JOINT_COUNT
          and result["shapes"]["shapes"][0]["name"] == "blink",
          json.dumps(result["skin"]))
    facts = fbxbytes.read_fbx(idle_fbx)
    check("idle: an independent byte read agrees with the tool",
          fbxbytes.anim_facts(facts) == anim)

    # ---- 6. the walk REPLACES the idle; previewed from the side; exported
    walk = ok("author_clip", {"root": root, "name": "walk",
                              "fps": WALK_FPS, "interpolation": "smooth",
                              "loop": True, "keys": WALK_KEYS})
    check("walk: replacing the idle is stated",
          walk["replaced"] == "idle"
          and any("replaced clip 'idle'" in w for w in walk["warnings"]))
    check("walk: root bob keyed", walk["root_position_keyed"] is True)
    moved = [k["max_displacement"] for k in walk["per_key"]]
    check("walk: every interior stride key measured real motion",
          all(m > 0.05 for m in moved[1:-1]),
          json.dumps([round(m, 4) for m in moved]))
    check("walk: the loop measurably closes (last key ~= first)",
          moved[-1] < 1e-3, "closure=%.5f" % moved[-1])
    preview = ok("preview_clip", {"root": root, "name": "walk",
                                  "angle": "side",
                                  "resolution": PREVIEW_RESOLUTION,
                                  "zoom": WALK_ZOOM},
                 timeout_s=900.0)
    save_preview("walk", preview)
    # the pelvis bob, measured off the evaluated scene at contact/passing
    bob = py(
        "import maya.cmds as cmds\n"
        "cmds.currentTime(0)\n"
        "_lo = cmds.xform(%(r)r, query=True, worldSpace=True,\n"
        "                 translation=True)[1]\n"
        "cmds.currentTime(9)\n"
        "_hi = cmds.xform(%(r)r, query=True, worldSpace=True,\n"
        "                 translation=True)[1]\n"
        "cmds.currentTime(0)\n"
        "{'contact_y': round(_lo, 4), 'passing_y': round(_hi, 4)}"
        % {"r": root}, "pelvis bob")
    check("walk: the pelvis bobs (contact %.3f -> passing %.3f)"
          % (bob["contact_y"], bob["passing_y"]),
          bob["passing_y"] - bob["contact_y"] > 0.02)

    walk_fbx = out("walk.fbx")
    if os.path.exists(walk_fbx):
        os.unlink(walk_fbx)
    result = ok("export_fbx", {"path": walk_fbx.replace("\\", "/"),
                               "metres_per_unit": 1.0,
                               "include_skins": True,
                               "include_animation": True}, timeout_s=900.0)
    anim_w = result["animation"]
    by_w = {(t["target"], t["property"]): t for t in anim_w["targets"]}
    walk_take = take_named(anim_w, "walk")
    check("walk: a take named 'walk', 37-key joint curves",
          walk_take is not None
          and by_w.get(("L_hip", "Lcl Rotation"), {}).get("key_count") == 37,
          json.dumps([t["name"] for t in anim_w["takes"]]))
    check("walk: the 'walk' take's duration matches within a frame",
          walk_take is not None
          and abs(walk_take["duration_s"] - 1.2) <= 1.0 / WALK_FPS,
          "duration_s=%s" % (walk_take or {}).get("duration_s"))
    check("walk: root translation curves present at 37 keys",
          by_w.get(("pelvis", "Lcl Translation"), {}).get("key_count") == 37,
          json.dumps({str(k): v.get("key_count")
                      for k, v in by_w.items()
                      if k[1] == "Lcl Translation"}))

    # ---- 7. delete_clip returns the skeleton to static land
    gone = ok("delete_clip", {"root": root})
    check("delete_clip removed the walk and measured the return",
          gone["clip"] == "walk" and gone["deleted_curves"] > 0)
    reposed = ok("pose_skeleton", {"root": root,
                                   "rotations": {"chest": [0, -10, 0]}})
    check("static posing works again after delete_clip",
          reposed["max_displacement"] > 0.01)
    ok("reset_pose", {"root": root})
    static_fbx = out("static.fbx")
    if os.path.exists(static_fbx):
        os.unlink(static_fbx)
    result = ok("export_fbx", {"path": static_fbx.replace("\\", "/"),
                               "metres_per_unit": 1.0,
                               "include_skins": True}, timeout_s=600.0)
    facts = fbxbytes.read_fbx(static_fbx)
    check("a static export after delete_clip carries ZERO curve records",
          len(facts.anim_curves) == 0 and result["animation"] is None,
          "curves=%d" % len(facts.anim_curves))
    os.unlink(static_fbx)   # evidence is the check; the file is not a
    # deliverable of this gate

    with open(out("baseline.json"), "w") as fh:
        json.dump({
            "idle": {"fbx": "idle.fbx", "keys": len(IDLE_KEYS),
                     "duration_s": idle["duration_s"],
                     "frames": idle["frames"],
                     "per_key": idle["per_key"],
                     "animation": anim},
            "walk": {"fbx": "walk.fbx", "keys": len(WALK_KEYS),
                     "duration_s": walk["duration_s"],
                     "frames": walk["frames"],
                     "per_key": walk["per_key"],
                     "pelvis_bob": bob,
                     "animation": anim_w},
        }, fh, indent=2, sort_keys=True)
    print("  baseline: %s" % out("baseline.json"))

    print("\n" + "=" * 72)
    print("JUDGE the preview frames in %s:" % OUT_DIR)
    print("  idle_*: the figure must visibly sway and settle; the blink")
    print("  must read on the face mid-sheet and be gone by the last cell.")
    print("  A frozen sheet with green numbers is a FAIL.")
    print("  walk_*: read the cells as a flipbook - legs must alternate,")
    print("  arms must counter-swing, the body must ride slightly lower at")
    print("  contact than at passing. Legs twisting in place instead of")
    print("  swinging is the wrong-axis failure the measured table exists")
    print("  to prevent. First and last cells must match (the loop).")
    print("=" * 72 + "\n")

    failed = [label for passed, label in CHECKS if not passed]
    print("\n%d/%d passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
