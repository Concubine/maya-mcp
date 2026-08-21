"""Live gate for the rigid-parent rig: #719, #720, #721, #722.

The #713 golem proved a second legal rig shape - meshes parented under
joints with NO skinCluster anywhere - and every tool in the animation
surface had been written against skinned rigs only. This gate builds a rig
of exactly that shape and measures each fix against it:

    1  #719  every joint sits where it was asked to sit, and the whole
             skeleton shares the WORLD axes (orient [0,0,0] on each joint)
    2  #720  author_clip reports a NON-ZERO max_displacement - the rig is
             the only thing moving, so a zero here is the #636 echo
    3  #720  preview_clip renders it instead of refusing "no skinned mesh"
    4  #722  author_physics reads chunk ancestry THROUGH the joints
    5  #722  a joint limit on a chunk that resolves parentless REFUSES
             instead of vanishing into a complete-looking manifest
    6  #713  the animated export byte-gates, and the bytes carry the take

Pre-fix behaviour, for anyone re-running this against an older plugin:
check 1 measured (2.05, 0, 0) for a joint asked for (0, 2.05, 0), checks 2
and 4 measured 0.0 and parent:null across the board, check 3 refused
outright, and check 5 silently produced a limitless manifest.

DESTRUCTIVE: calls new_scene. Port 9878, the agent-launched Maya, per the
two-Maya policy - never point this at the user's session.

Run:  MAYA_MCP_PORT=9878 uv run python evals/rigid_rig_live.py
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys

from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402
from maya_plugin.handlers import fbxbytes  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
OUT_DIR = os.path.join(_HERE, "rigid_rig_live")

# A sagittal three-joint rig, metre-native, every joint on the WORLD axes:
# local X means the same direction on every bone, which is the whole point
# of the #719 fix (an all-hinges-X rig cannot be built under auto-orient).
JOINTS = [
    {"name": "jnt_pelvis", "position": [0.0, 1.00, 0.0], "orient": [0, 0, 0]},
    {"name": "jnt_torso", "position": [0.0, 1.60, 0.0], "parent": "jnt_pelvis",
     "orient": [0, 0, 0]},
    {"name": "jnt_arm", "position": [0.45, 1.55, 0.0], "parent": "jnt_torso",
     "orient": [0, 0, 0]},
]
POSITION_TOL = 1e-6
AXIS_TOL = 1e-6

# One chunk per joint, rigidly parented - no bind_skin anywhere in this
# file, deliberately. Each is placed in world space first and re-parented
# after, the way a destruction kit is assembled.
CHUNKS = [
    # (name, joint, translate, scale)
    ("chunk_pelvis", "jnt_pelvis", [0.0, 1.00, 0.0], [0.36, 0.34, 0.28]),
    ("chunk_torso", "jnt_torso", [0.0, 1.62, 0.0], [0.40, 0.46, 0.30]),
    ("chunk_arm", "jnt_arm", [0.62, 1.55, 0.0], [0.36, 0.18, 0.18]),
]

# 1.0 s, closes onto its first key: the torso leans and the arm swings.
# Both joints are world-aligned, so these are world Z rotations.
CLIP_NAME = "idle"
CLIP_FPS = 30
CLIP_KEYS = [
    {"time_s": 0.0,
     "rotations": {"jnt_torso": [0, 0, 0], "jnt_arm": [0, 0, 0]}},
    {"time_s": 0.5,
     "rotations": {"jnt_torso": [0, 0, 7], "jnt_arm": [0, 0, -28]}},
    {"time_s": 1.0,
     "rotations": {"jnt_torso": [0, 0, 0], "jnt_arm": [0, 0, 0]}},
]
DISPLACEMENT_MIN = 0.01     # metres; the arm swing is ~0.1 m at the tip

PREVIEW_RESOLUTION = 640
PREVIEW_ZOOM = 1.5
# Same band as clip_live: catches "no figure" and "no shading", not taste.
LIT_THRESHOLD = 18
FIGURE_PIXELS_MIN = 2000
LUMINANCE_BAND = (30.0, 240.0)

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
    error = json.dumps(response.get("error"))
    refused = response.get("status") != "ok" and needle in error
    check(label, refused, error[:200] if response.get("status") != "ok"
          else "the call SUCCEEDED - nothing refused")
    return refused


def py(code, what, timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s),
                             what)


def out(name):
    return os.path.join(OUT_DIR, name)


def lit_stats(png_bytes):
    hist = Image.open(io.BytesIO(png_bytes)).convert("L").histogram()
    lit = sum(hist[LIT_THRESHOLD + 1:])
    total = sum(i * hist[i] for i in range(LIT_THRESHOLD + 1, 256))
    return lit, (total / lit if lit else 0.0)


def take_named(anim, name):
    """Looked up BY NAME: Maya's exporter always writes its own 'Take 001'
    alongside the take named after the clip (measured in phase 6)."""
    for take in (anim or {}).get("takes", []):
        if take.get("name") == name:
            return take
    return None


def main():
    if PORT == 9877:
        print("refusing to run on 9877: this eval discards the open scene "
              "(two-Maya policy). Launch a disposable Maya on 9878.")
        return 2

    os.makedirs(OUT_DIR, exist_ok=True)
    identity = py("import os\n{'pid': os.getpid()}", "identity")
    print("Maya on %d: pid %s, writing to %s\n"
          % (PORT, identity["pid"], OUT_DIR))

    # ---- build: skeleton, then chunks, then parent. No bind_skin.
    ok("new_scene", {"confirm": True})
    skeleton = ok("create_skeleton", {"joints": JOINTS})
    root = skeleton["root"]

    # ---- check 1 (#719): positions and world axes, re-read from the scene
    # rather than trusted from the return value.
    requested = {j["name"]: j["position"] for j in JOINTS}
    probe = py(
        "import maya.cmds as cmds\n"
        "{n: {'p': cmds.xform(n, q=True, ws=True, t=True),\n"
        "     'm': cmds.xform(n, q=True, ws=True, m=True)}\n"
        " for n in %r}" % [j["name"] for j in JOINTS],
        "joint world transforms")
    worst_pos = 0.0
    worst_axis = 0.0
    for name, want in requested.items():
        got = probe[name]["p"]
        worst_pos = max(worst_pos,
                        max(abs(a - b) for a, b in zip(got, want)))
        matrix = probe[name]["m"]
        worst_axis = max(
            worst_axis,
            max(abs(a - b) for a, b in zip(matrix[0:3], (1.0, 0.0, 0.0))),
            max(abs(a - b) for a, b in zip(matrix[4:7], (0.0, 1.0, 0.0))))
    check("1 (#719): every joint sits where it was asked to sit",
          worst_pos <= POSITION_TOL,
          "worst error %.3e m (tol %.0e)" % (worst_pos, POSITION_TOL))
    check("1 (#719): the whole skeleton shares the WORLD axes",
          worst_axis <= AXIS_TOL,
          "worst axis error %.3e (tol %.0e)" % (worst_axis, AXIS_TOL))
    check("1 (#719): create_skeleton REPORTED those same positions",
          all(max(abs(a - b) for a, b in
                  zip(j["position"], requested[j["name"].rsplit("|", 1)[-1]]))
              <= POSITION_TOL for j in skeleton["joints"]))

    for name, joint, translate, scale in CHUNKS:
        ok("create_primitive", {"kind": "cube", "name": name,
                                "translate": translate, "scale": scale})
    # Freeze the scales into the vertices BEFORE parenting: the export byte
    # gate refuses a non-identity node scale outright (#629 - a compensating
    # node scale hides a wrong vertex magnitude), and a destruction kit
    # assembled from scaled primitives would never survive it.
    py("\n".join([
        "import maya.cmds as cmds",
        "for n in %r:" % [c[0] for c in CHUNKS],
        "    cmds.makeIdentity(n, apply=True, translate=False, rotate=True,",
        "                      scale=True, normal=0, preserveNormals=True)",
        "True",
    ]), "freeze the chunk scales")
    for name, joint, translate, scale in CHUNKS:
        ok("parent", {"child": name, "parent": joint})
    parented = py(
        "import maya.cmds as cmds\n"
        "{n: {'parent': (cmds.listRelatives(n, parent=True, fullPath=True) "
        "or [None])[0],\n"
        "     'skin': cmds.ls(type='skinCluster') or [],\n"
        "     'p': cmds.xform(n, q=True, ws=True, t=True)}\n"
        " for n in %r}" % [c[0] for c in CHUNKS],
        "chunk parents")
    check("build: every chunk hangs off its joint, and NOTHING is skinned",
          all(parented[c[0]]["parent"].rsplit("|", 1)[-1] == c[1]
              for c in CHUNKS)
          and not parented[CHUNKS[0][0]]["skin"],
          "skinClusters=%d" % len(parented[CHUNKS[0][0]]["skin"]))
    drift = max(max(abs(a - b) for a, b in zip(parented[c[0]]["p"], c[2]))
                for c in CHUNKS)
    check("build: re-parenting moved no chunk in world space",
          drift <= 1e-6, "worst drift %.3e m" % drift)
    ok("setup_lighting", {"preset": "three_point"})

    # ---- check 2 (#720/#636): the clip measures what it moves
    clip = ok("author_clip", {"root": root, "name": CLIP_NAME,
                              "fps": CLIP_FPS, "interpolation": "smooth",
                              "loop": True, "keys": CLIP_KEYS},
              timeout_s=600.0)
    moved = [k["max_displacement"] for k in clip["per_key"]]
    check("2 (#720): author_clip MEASURED the rigidly-parented chunks",
          moved[0] == 0.0 and moved[1] >= DISPLACEMENT_MIN,
          "per_key=%s (a zero here is the #636 echo)"
          % json.dumps([round(m, 4) for m in moved]))
    check("2 (#720): the loop measurably closes",
          moved[-1] < 1e-3, "closure=%.6f m" % moved[-1])
    check("2 (#720): no warning claims this skeleton moves nothing",
          not [w for w in clip["warnings"] if "moves no mesh" in w],
          json.dumps(clip["warnings"])[:200])

    # ---- check 3 (#720): it previews instead of refusing
    preview = ok("preview_clip", {"root": root, "name": CLIP_NAME,
                                  "angle": "three_quarter",
                                  "resolution": PREVIEW_RESOLUTION,
                                  "zoom": PREVIEW_ZOOM},
                 timeout_s=900.0)
    counts, means = [], []
    for image in preview.get("images", []):
        png = base64.b64decode(image["png_b64"])
        with open(out("preview_%s.png" % image["label"].replace("=", "")
                      .replace(".", "_")), "wb") as fh:
            fh.write(png)
        lit, mean = lit_stats(png)
        counts.append(lit)
        means.append(mean)
    lo, hi = LUMINANCE_BAND
    check("3 (#720): preview_clip rendered the rig instead of refusing",
          len(preview.get("frames", [])) >= 4,
          "frames=%s" % [f["frame"] for f in preview.get("frames", [])])
    check("3 (#720): every cell shows a lit, shaded rig",
          bool(counts) and min(counts) >= FIGURE_PIXELS_MIN
          and all(lo <= m <= hi for m in means),
          "lit_px %d..%d (min %d), mean luminance %.1f..%.1f"
          % (min(counts or [0]), max(counts or [0]), FIGURE_PIXELS_MIN,
             min(means or [0]), max(means or [0])))

    # ---- check 6 (#713): the animated export, byte-gated
    fbx = out("rigid_rig.fbx")
    if os.path.exists(fbx):
        os.unlink(fbx)
    export = ok("export_fbx", {"path": fbx.replace("\\", "/"),
                               "metres_per_unit": 1.0,
                               "include_animation": True}, timeout_s=900.0)
    anim = export.get("animation") or {}
    take = take_named(anim, CLIP_NAME)
    check("6: the animated export passed its own byte gate",
          os.path.exists(fbx) and export["bytes"] > 0
          and export["metres_per_unit"] == 1.0,
          "%d bytes, %d nodes, %d meshes"
          % (export["bytes"], export["node_count"], export["mesh_count"]))
    check("6: the bytes carry a take named %r" % CLIP_NAME, take is not None,
          "takes=%s" % json.dumps([t.get("name")
                                   for t in anim.get("takes", [])]))
    facts = fbxbytes.read_fbx(fbx)
    check("6: the exported file animates the joints",
          len(facts.anim_curves) > 0,
          "curve records=%d" % len(facts.anim_curves))

    # ---- checks 4 and 5 (#722): physics reads the joint chain
    ok("delete_clip", {"root": root})
    physics = ok("author_physics", {"root": "jnt_pelvis"})
    parents = {b["chunk"].rsplit("|", 1)[-1]:
               (b["parent"].rsplit("|", 1)[-1] if b["parent"] else None)
               for b in physics["bodies"]}
    check("4 (#722): chunk ancestry read THROUGH the joints",
          parents.get("chunk_torso") == "chunk_pelvis"
          and parents.get("chunk_arm") == "chunk_torso"
          and parents.get("chunk_pelvis") is None,
          json.dumps(parents))
    limited = ok("author_physics", {
        "root": "jnt_pelvis",
        "overrides": {"chunk_arm": {"hinge_axis": [0, 0, 1],
                                    "hinge_range_deg": [-10, 90]}}})
    arm = [b for b in limited["bodies"]
           if b["chunk"].endswith("chunk_arm")][0]
    check("4 (#722): a hinge override now LANDS on a joint",
          arm["joint"] is not None
          and arm["joint"].get("source") == "override",
          json.dumps(arm["joint"])[:200])
    expect_refusal(
        "author_physics",
        {"root": "jnt_pelvis",
         "overrides": {"chunk_pelvis": {"hinge_axis": [0, 0, 1],
                                        "hinge_range_deg": [0, 90]}}},
        "parentless",
        "5 (#722): a limit on a parentless chunk REFUSES, never vanishes")

    with open(out("baseline.json"), "w") as fh:
        json.dump({
            "joints": {"requested": requested,
                       "measured": {n: probe[n]["p"] for n in requested},
                       "worst_position_error": worst_pos,
                       "worst_axis_error": worst_axis},
            "clip": {"name": CLIP_NAME, "fps": CLIP_FPS,
                     "duration_s": clip["duration_s"],
                     "frames": clip["frames"],
                     "per_key": clip["per_key"]},
            "preview": {"frames": [f["frame"]
                                   for f in preview.get("frames", [])],
                        "lit_pixels": counts, "mean_luminance": means},
            "export": {"bytes": export["bytes"],
                       "node_count": export["node_count"],
                       "mesh_count": export["mesh_count"],
                       "takes": [t.get("name")
                                 for t in anim.get("takes", [])],
                       "anim_curve_records": len(facts.anim_curves)},
            "physics": {"parents": parents,
                        "total_volume": physics["total_volume"],
                        "arm_joint": arm["joint"]},
        }, fh, indent=2, sort_keys=True)
    print("  baseline: %s" % out("baseline.json"))

    print("\n" + "=" * 72)
    print("JUDGE the preview cells in %s:" % OUT_DIR)
    print("  preview_*: three cubes, one per joint. The arm cube must")
    print("  visibly swing away from the torso and come back; the torso")
    print("  must lean with it. Cubes that never move are the #720 failure")
    print("  wearing green numbers - the checks measure the SCENE, the")
    print("  pixels are what prove the preview looked at the right thing.")
    print("=" * 72 + "\n")

    failed = [label for passed, label in CHECKS if not passed]
    print("\n%d/%d passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
