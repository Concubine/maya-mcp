"""Live gate for redmine #798: the clip guards' remaining edges, measured.

Four findings #796 left open, each one turning on what REAL Maya does with
a driven key, a lock, or a bake - none of which a headless suite can settle
(the fake certifies its author's belief, #799's lesson):

A. clean_clip's filter pass smoothed a set-driven key at frame NUMBERS. The
   probe measured: getAttr(time=f) on such a plug answers the driver's
   constant at every f, the re-key returns 0 every time, and the pass
   counted the channel anyway. The CLIP partition now.
B. retarget_clip ran no #718 self-contained pass and registered `joints:
   []`. Measured: the walk's slot joints held its LAST pose across the
   whole idle take authored after it, and idle's back-fill of a slot joint
   with no recorded rest wrote the walk's FIRST value over its last frame.
   The pass is one function now (`clip.make_self_contained`), both
   producers run it, and the rest is captured at stance before the bake.
C. A locked root.translateY under author_clip's root_position: the
   lost-write note pointed at "the note naming what drives it" (there was
   none), and worse - `xform` drops a locked child WITHOUT raising and
   setKeyframe on it returns 0, so the clip reported root_position keyed
   with one of three channels never written. Refused before the
   checkpoint now; a locked PAD channel is skipped and named.
D. The blend walk's cost inside cut_replaced_range, on a 60-joint rig -
   recorded, not fixed (48 ms measured by the probe).

DESTRUCTIVE: calls new_scene. Runs against the disposable agent Maya on 9878
and REFUSES 9877 (the user's session) unless MAYA_MCP_ALLOW_USER_SESSION=1.
The live Maya must be launched with the repo as its working directory so it
imports THIS working tree's plugin (phase 0 asserts it).

Run:  MAYA_MCP_PORT=9878 MAYA_MCP_EXPECT_PID=<pid> .venv/Scripts/python.exe evals/clip_edges_live.py
Exit: 0 pass, 1 fail, 2 environment (nothing listening / wrong code loaded).
"""

from __future__ import annotations

import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402
from humanoid_live import JOINTS  # noqa: E402
from maya_plugin.handlers import mocapmath  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
    print("refusing to run against port 9877 (the user's Maya): this gate "
          "calls new_scene. Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.")
    raise SystemExit(2)

WALK_BVH = os.path.join(_HERE, "mocap_fixtures", "cmu_walk.bvh")
SLOT_SHORTS = sorted(mocapmath.SKELETON_HIK_MAP.values())
CHECKS = []


def check(label, passed, detail=""):
    CHECKS.append((bool(passed), label))
    print("%-4s %s%s" % ("PASS" if passed else "FAIL", label,
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
        print("FAIL: %s: %s" % (command, json.dumps(response.get("error"))[:800]))
        sys.exit(1)
    return response.get("result") or {}


def refusal(command, params, timeout_s=300.0):
    response = send(command, params, timeout_s)
    if response.get("status") == "ok":
        return None
    return response.get("error") or {}


def py(code, what, timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s),
                             what)


def keys_at(plug, frames):
    return py("import maya.cmds as cmds\n"
              "plug, frames = %r, %r\n"
              "times = set(cmds.keyframe(plug, q=True) or [])\n"
              "{f: (float(f) in times, cmds.getAttr(plug, time=f)) "
              "for f in frames}" % (plug, list(frames)), "keys at %s" % plug)


def main():
    # ---- 0. who answered, and WHOSE code is it -------------------------
    ident = py("import os, maya_plugin\n"
               "{'pid': os.getpid(), 'plugin': maya_plugin.__file__}",
               "identity")
    print("maya on %d: pid %s\nplugin: %s\n" % (PORT, ident["pid"],
                                                ident["plugin"]))
    if os.path.normcase(REPO) not in os.path.normcase(ident["plugin"]):
        print("the live Maya is running the plugin at %s, NOT this working "
              "tree (%s). Relaunch Maya with the repo as its working "
              "directory." % (ident["plugin"], REPO))
        sys.exit(2)

    # ==================================================================
    # A + C: a four-joint chain with a clip, a driven key, and locks
    # ==================================================================
    ok("new_scene", {"confirm": True})
    skel = ok("create_skeleton", {
        "chain": [[0, 0, 0], [0, 1, 0], [0, 2, 0], [0, 3, 0]],
        "chain_prefix": "g"})
    root = skel["root"]
    names = [j["name"] for j in skel["joints"]]
    # `third` carries the LOCK in section C; `leaf` carries section A's
    # driven key, and a clip declaring a driven channel is refused (#796).
    mid, third, leaf = names[1], names[2], names[3]

    def chain_clip(name, joint, angle, **extra):
        keys = [{"time_s": 0.0, "rotations": {joint: [0, 0, 0]}},
                {"time_s": 0.5, "rotations": {joint: [0, 0, angle]}},
                {"time_s": 1.0, "rotations": {joint: [0, 0, 0]}}]
        for k, pos in zip(keys, extra.get("root_positions", [])):
            k["root_position"] = pos
        return send("author_clip", {"root": root, "name": name, "fps": 30,
                                    "interpolation": "smooth", "keys": keys})

    sway = chain_clip("sway", mid, 20)
    check("setup: 'sway' authored on the chain", sway.get("status") == "ok")

    # ---- A. clean_clip vs a set-driven key ------------------------------
    sdk = py(
        "import maya.cmds as cmds\n"
        "root, leaf = %r, %r\n"
        "cmds.addAttr(root, ln='sdk_drv', at='double', dv=0.0, k=True)\n"
        "cmds.setDrivenKeyframe(leaf + '.rotateX', cd=root + '.sdk_drv', "
        "dv=0.0, v=0.0)\n"
        "cmds.setDrivenKeyframe(leaf + '.rotateX', cd=root + '.sdk_drv', "
        "dv=10.0, v=35.0)\n"
        "cmds.setAttr(root + '.sdk_drv', 4.0)\n"
        "src = cmds.listConnections(leaf + '.rotateX', s=True, d=False)[0]\n"
        "{'curve': src, 'type': cmds.nodeType(src),\n"
        " 'keys': cmds.keyframe(src, q=True, valueChange=True),\n"
        " 'floats': cmds.keyframe(src, q=True, floatChange=True),\n"
        " 'getattr_at_frames': sorted({round(cmds.getAttr(leaf + "
        "'.rotateX', time=f), 6) for f in (0, 5, 10, 30)})}"
        % (root, leaf), "set-driven key")
    check("setup: the driven key is a U-typed curve",
          str(sdk["type"]).startswith("animCurveU"), sdk["type"])
    check("MEASURED: getAttr(time=f) on the driven plug answers ONE value at "
          "every frame (the driver's, not a frame's)",
          len(sdk["getattr_at_frames"]) == 1,
          json.dumps(sdk["getattr_at_frames"]))
    cleaned = ok("clean_clip", {"root": root, "clip": "sway",
                                "filter": True, "lock_contacts": False})
    smoothed = [w for w in cleaned.get("warnings", [])
                if w.startswith("filter: smoothed")]
    check("clean_clip's filter pass smooths the 3 clip channels, not the "
          "driven key's plug",
          any("smoothed 3 channel" in w for w in smoothed),
          "; ".join(smoothed) or "no filter note")
    after = py(
        "import maya.cmds as cmds\n"
        "src = %r\n"
        "{'alive': cmds.objExists(src),\n"
        " 'keys': cmds.keyframe(src, q=True, valueChange=True),\n"
        " 'floats': cmds.keyframe(src, q=True, floatChange=True)}"
        % sdk["curve"], "sdk after clean")
    check("the driven key's driver-indexed keys survive clean_clip",
          after["alive"] and after["keys"] == sdk["keys"]
          and after["floats"] == sdk["floats"],
          "before %s@%s after %s@%s" % (sdk["keys"], sdk["floats"],
                                        after["keys"], after["floats"]))
    check("and no write is reported lost on a clean rig",
          not any("did NOT land" in w for w in cleaned.get("warnings", [])))

    # ---- C. locks -------------------------------------------------------
    py("import maya.cmds as cmds\ncmds.setAttr(%r + '.translateY', lock=True)\n"
       "cmds.getAttr(%r + '.translateY', lock=True)" % (root, root), "lock")
    err = refusal("author_clip", {
        "root": root, "name": "hop", "fps": 30,
        "keys": [{"time_s": 0.0, "rotations": {mid: [0, 0, 0]},
                  "root_position": [0, 0, 0]},
                 {"time_s": 0.5, "rotations": {mid: [0, 0, 5]},
                  "root_position": [0, 0.3, 0]},
                 {"time_s": 1.0, "rotations": {mid: [0, 0, 0]},
                  "root_position": [0, 0, 0]}]})
    check("author_clip REFUSES a root_position clip on a locked "
          "root.translateY", err is not None,
          (err or {}).get("message", "")[:160])
    check("the refusal names the locked plug",
          err is not None and "translateY is locked" in err.get("message", ""))
    check("and the hint says to unlock it",
          err is not None and "unlock" in (err.get("hint") or ""))
    state = py(
        "import maya.cmds as cmds\n"
        "root = %r\n"
        "{'clips': [r['name'] for r in __import__('maya_plugin.handlers.clip', "
        "fromlist=['clip']).clip_meta(cmds, root)],\n"
        " 'tx_keyed': bool(cmds.keyframe(root + '.translateX', q=True))}"
        % root, "after refusal")
    check("nothing was written by the refused call",
          state["clips"] == ["sway"] and not state["tx_keyed"],
          json.dumps(state))
    py("import maya.cmds as cmds\ncmds.setAttr(%r + '.translateY', lock=False)\n"
       "0" % root, "unlock")

    wave = chain_clip("wave", third, 25)
    check("setup: 'wave' declares the third joint", wave.get("status") == "ok",
          json.dumps(wave.get("error"))[:200] if wave.get("status") != "ok"
          else "")
    py("import maya.cmds as cmds\ncmds.setAttr(%r + '.rotateX', lock=True)\n"
       "0" % third, "lock third.rotateX")
    idle = chain_clip("idle", mid, 12)
    check("a clip on the OTHER joints is still accepted with a locked pad "
          "channel on the rig", idle.get("status") == "ok",
          json.dumps(idle.get("error"))[:200] if idle.get("status") != "ok"
          else "")
    if idle.get("status") == "ok":
        res = idle["result"]
        skipped = [w for w in res["warnings"]
                   if third + ".rotateX" in w and "SKIPPED" in w]
        check("the locked pad channel is SKIPPED and named as locked",
              any("is locked" in w for w in skipped),
              skipped[0][:160] if skipped else "no skip note")
        sib = keys_at(third + ".rotateY", [res["start_frame"], res["end_frame"]])
        check("the free sibling on the same joint is still pinned at rest",
              all(v[0] and abs(v[1]) < 1e-9 for v in sib.values()),
              json.dumps(sib))
        lockd = keys_at(third + ".rotateX", [res["start_frame"]])
        check("and the locked plug really got no pin (Maya, not the fake)",
              not lockd[res["start_frame"]][0], json.dumps(lockd))
        cleaned2 = ok("clean_clip", {"root": root, "clip": "wave",
                                     "filter": True, "lock_contacts": False})
        lost = [w for w in cleaned2["warnings"]
                if third + ".rotateX" in w and "did NOT land" in w]
        check("clean_clip reports the locked channel's vanished re-key, "
              "naming the lock", any("is locked" in w for w in lost),
              lost[0][:160] if lost else "no lost-write note")
    py("import maya.cmds as cmds\ncmds.setAttr(%r + '.rotateX', lock=False)\n"
       "0" % third, "unlock third")

    # ---- D. the blend walk's cost, recorded --------------------------
    ok("new_scene", {"confirm": True})
    big = ok("create_skeleton", {
        "chain": [[0, i * 0.1, 0] for i in range(60)], "chain_prefix": "b"})
    broot = big["root"]
    bnames = [j["name"] for j in big["joints"]]

    def big_clip():
        return ok("author_clip", {
            "root": broot, "name": "a", "fps": 30,
            "keys": [{"time_s": 0.0, "rotations": {bnames[5]: [0, 0, 0]}},
                     {"time_s": 1.0, "rotations": {bnames[5]: [0, 0, 15]}}]})

    big_clip()
    t0 = time.perf_counter()
    big_clip()
    wire_s = time.perf_counter() - t0
    timing = py(
        "import time\n"
        "import maya.cmds as cmds\n"
        "from maya_plugin.handlers import clip, rigging\n"
        "root = %r\n"
        "joints = rigging._hierarchy_joints(cmds, root)\n"
        "rec = clip.clip_meta(cmds, root)[0]\n"
        "orig = cmds.listConnections\n"
        "count = [0]\n"
        "def counting(*a, **k):\n"
        "    count[0] += 1\n"
        "    return orig(*a, **k)\n"
        "cmds.listConnections = counting\n"
        "try:\n"
        "    t = time.perf_counter()\n"
        "    clip.cut_replaced_range(cmds, joints, rec)\n"
        "    out = {'s': time.perf_counter() - t, 'queries': count[0]}\n"
        "finally:\n"
        "    cmds.listConnections = orig\n"
        "out" % broot, "timing")
    check("MEASURED: cut_replaced_range on 60 joints - %d connection "
          "queries in %.3fs, whole re-author %.3fs over the wire"
          % (timing["queries"], timing["s"], wire_s),
          timing["s"] < 1.0)

    # ==================================================================
    # B. retarget_clip is self-contained, both directions
    # ==================================================================
    ok("new_scene", {"confirm": True})
    skel = ok("create_skeleton", {"joints": JOINTS})
    hroot = skel["root"]
    by_short = {j["name"].rsplit("|", 1)[-1]: j["name"]
                for j in skel["joints"]}

    def neck_clip(name):
        return ok("author_clip", {
            "root": hroot, "name": name, "fps": 30,
            "keys": [{"time_s": 0.0, "rotations": {"neck": [0, 0, 0]}},
                     {"time_s": 0.5, "rotations": {"neck": [0, 0, 15]}},
                     {"time_s": 1.0, "rotations": {"neck": [0, 0, 0]}}]})

    idle = neck_clip("idle")
    check("setup: 'idle' (neck only) authored first - the ordering the "
          "back-fill half is about", idle["end_frame"] > 0)
    walk = ok("retarget_clip", {"file": WALK_BVH, "root": hroot,
                                "clip": "walk01", "start": 1, "end": 301,
                                "fps": 30}, 600.0)
    check("setup: walk01 retargeted after idle", walk["frames"] > 0,
          "frames %s fps %s" % (walk["frames"], walk["fps"]))
    check("the old NOT-self-contained warning is gone",
          not any("NOT self-contained" in w for w in walk["warnings"]))
    check("retarget_clip pads the neighbour's channel (neck) at its own "
          "boundaries", walk.get("padded_channels") == ["neck"],
          json.dumps(walk.get("padded_channels")))
    rec = py("import maya.cmds as cmds\nfrom maya_plugin.handlers import clip\n"
             "[r for r in clip.clip_meta(cmds, %r) if r['name'] == 'walk01'][0]"
             % hroot, "walk01 record")
    check("the record declares the 15 slot joints the bake keyed",
          rec["joints"] == SLOT_SHORTS, json.dumps(rec["joints"]))
    check("and the root's translation", rec["root_position_used"] is True)
    ws, we = rec["start_frame"], rec["end_frame"]
    neck = keys_at(by_short["neck"] + ".rotateZ", [ws, we])
    check("neck is keyed at rest at walk01's first and last frame",
          all(v[0] and abs(v[1]) < 1e-6 for v in neck.values()),
          json.dumps(neck))
    bf = walk.get("back_filled") or {}
    check("walk01 back-fills its joints across idle",
          bf.get("clips") == ["idle"]
          and sorted(bf.get("channels", [])) == sorted(SLOT_SHORTS
                                                       + ["root_position"]),
          json.dumps(bf)[:300])
    pel = keys_at(by_short["pelvis"] + ".rotateY",
                  [idle["start_frame"], idle["end_frame"],
                   (idle["start_frame"] + idle["end_frame"]) // 2])
    check("idle's range holds the pelvis at STANCE (the bake's rest), not "
          "the walk's first pose",
          pel[idle["start_frame"]][0] and pel[idle["end_frame"]][0]
          and all(abs(v[1]) < 1e-6 for v in pel.values()),
          json.dumps(pel))
    hip_before = py("import maya.cmds as cmds\n"
                    "cmds.getAttr(%r + '.rotateY', time=%d)"
                    % (by_short["L_hip"], we), "L_hip at walk end")

    # The ticket's exact scenario, the other way round: a clip AFTER the
    # retargeted take, declaring nothing the bake covers.
    bob = neck_clip("bob")
    check("author_clip after the retarget pads every slot joint and the "
          "root position",
          sorted(bob["padded_channels"]) == sorted(SLOT_SHORTS
                                                   + ["root_position"]),
          json.dumps(bob["padded_channels"])[:300])
    hip = keys_at(by_short["L_hip"] + ".rotateY",
                  [bob["start_frame"], bob["end_frame"],
                   (bob["start_frame"] + bob["end_frame"]) // 2])
    check("the walk's LAST pose no longer bleeds into bob: L_hip.rotateY "
          "is at rest across it (walk end held %.3f)" % hip_before,
          all(abs(v[1]) < 1e-6 for v in hip.values())
          and hip[bob["start_frame"]][0] and hip[bob["end_frame"]][0],
          json.dumps(hip))
    hip_after = py("import maya.cmds as cmds\n"
                   "cmds.getAttr(%r + '.rotateY', time=%d)"
                   % (by_short["L_hip"], we), "L_hip at walk end, after")
    check("and walk01's own last frame is untouched by bob",
          abs(hip_after - hip_before) < 1e-9,
          "%.6f -> %.6f" % (hip_before, hip_after))

    # The replace path on REAL Maya (the fake had this wrong until the
    # review): re-retargeting the same name cuts the old bake, appends the
    # new one at the tail, and re-pads the neighbours at the NEW boundaries.
    walk2 = ok("retarget_clip", {"file": WALK_BVH, "root": hroot,
                                 "clip": "walk01", "start": 1, "end": 301,
                                 "fps": 30}, 600.0)
    recs = py("import maya.cmds as cmds\nfrom maya_plugin.handlers import clip\n"
              "[(r['name'], r['start_frame'], r['end_frame'], len(r['joints']))"
              " for r in clip.clip_meta(cmds, %r)]" % hroot, "records")
    check("a re-retarget of 'walk01' replaces it at the tail, declaring its "
          "joints again",
          [r[0] for r in recs] == ["idle", "bob", "walk01"]
          and recs[-1][1] > bob["end_frame"] and recs[-1][3] == 15,
          json.dumps(recs))
    check("and re-pads the neighbours' neck at the NEW boundaries",
          walk2.get("padded_channels") == ["neck"]
          and all(v[0] and abs(v[1]) < 1e-6 for v in keys_at(
              by_short["neck"] + ".rotateZ",
              [recs[-1][1], recs[-1][2]]).values()),
          json.dumps(walk2.get("padded_channels")))

    # ---- verdict --------------------------------------------------------
    failed = [label for passed, label in CHECKS if not passed]
    print("\n%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
