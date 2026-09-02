"""Throwaway probe for redmine #798 - MEASURE the four findings before
designing any fix (the process rule #796 earned: three review rounds argued
Maya behaviours one probe settled).

  A. clean_clip's filter pass on a rig carrying a set-driven key: does the
     pass sample and re-key the DRIVEN plug, what does getAttr(time=) answer
     on it, what does setKeyframe return, and do the driver-indexed keys
     survive?
  B. retarget_clip then author_clip: does the retargeted take's pose bleed
     into the authored take's range (no boundary pin on the slot joints),
     what channels did the bake actually create curves on, and what does
     the registered record declare?
  C. a LOCKED root.translateY under author_clip's root_position: which
     notes come back, and does any of them name the lock? Plus what
     setKeyframe and xform do against a locked plug.
  D. the cost of the blend walk inside cut_replaced_range on a 60-joint
     rig: wall time and listConnections count, with and without the walk.

DESTRUCTIVE (new_scene). Refuses 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1.
Run:  MAYA_MCP_PORT=9878 MAYA_MCP_EXPECT_PID=<pid> .venv/Scripts/python.exe evals/clip_edges_probe_798.py [A|B|C|D ...]
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

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
    print("refusing 9877 (the user's Maya): this probe calls new_scene")
    raise SystemExit(2)

OUT_DIR = os.path.join(_HERE, "clip_edges_probe_798")
os.makedirs(OUT_DIR, exist_ok=True)
WALK_BVH = os.path.join(_HERE, "mocap_fixtures", "cmu_walk.bvh")
FINDINGS = {}
ONLY = [a.upper() for a in sys.argv[1:]]


def want(tag):
    return not ONLY or tag in ONLY


def send(command, params, timeout_s=300.0):
    return call(command, params, timeout_s=timeout_s, port=PORT)


def ok(command, params, timeout_s=300.0):
    r = send(command, params, timeout_s)
    if r.get("status") != "ok":
        print("FAIL %s: %s" % (command, json.dumps(r.get("error"))[:1500]))
        sys.exit(1)
    return r.get("result") or {}


def py(code, what, timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s),
                             what)


def section(title):
    print("\n==== %s ====" % title)


def main():
    ident = py("import os, maya_plugin\n"
               "{'pid': os.getpid(), 'plugin': maya_plugin.__file__}", "id")
    print("maya on %d: pid %s plugin %s" % (PORT, ident["pid"],
                                            ident["plugin"]))
    if os.path.normcase(REPO) not in os.path.normcase(ident["plugin"]):
        print("NOT this working tree's plugin - relaunch with the repo cwd")
        sys.exit(2)

    if want("A") or want("C"):
        probe_a_c()
    if want("D"):
        probe_d()
    if want("B"):
        probe_b()
    with open(os.path.join(OUT_DIR, "findings.json"), "w") as f:
        json.dump(FINDINGS, f, indent=1)
    print("\nwrote", os.path.join(OUT_DIR, "findings.json"))


def probe_a_c():
    # ------------------------------------------------------------------ A
    ok("new_scene", {"confirm": True})
    section("A. clean_clip filter pass vs a set-driven key")
    skel = ok("create_skeleton", {
        "chain": [[0, 0, 0], [0, 1, 0], [0, 2, 0], [0, 3, 0]],
        "chain_prefix": "g"})
    root = skel["root"]
    names = [j["name"] for j in skel["joints"]]
    mid, leaf = names[1], names[3]
    ok("author_clip", {
        "root": root, "name": "sway", "fps": 30, "interpolation": "smooth",
        "keys": [{"time_s": 0.0, "rotations": {mid: [0, 0, 0]}},
                 {"time_s": 0.5, "rotations": {mid: [0, 0, 20]}},
                 {"time_s": 1.0, "rotations": {mid: [0, 0, 0]}}]})
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
        "from maya_plugin.handlers import cleanclip, clip, rigging\n"
        "joints = rigging._hierarchy_joints(cmds, root)\n"
        "{'curve': src, 'type': cmds.nodeType(src),\n"
        " 'keys': cmds.keyframe(src, q=True, valueChange=True),\n"
        " 'floats': cmds.keyframe(src, q=True, floatChange=True),\n"
        " 'keyed_plugs': cleanclip._keyed_plugs(cmds, joints),\n"
        " 'getattr_at_frames': [cmds.getAttr(leaf + '.rotateX', time=f) "
        "for f in (0, 5, 10, 30)],\n"
        " 'setkey_return': cmds.setKeyframe(leaf, at='rotateX', t=7, v=1.0),\n"
        " 'keys_after_setkey': cmds.keyframe(src, q=True, valueChange=True),\n"
        " 'floats_after_setkey': cmds.keyframe(src, q=True, "
        "floatChange=True),\n"
        " 'value_now': cmds.getAttr(leaf + '.rotateX')}" % (root, leaf),
        "sdk setup")
    print(json.dumps(sdk, indent=1))
    FINDINGS["A_before"] = sdk
    cleaned = ok("clean_clip", {"root": root, "clip": "sway",
                                "filter": True, "lock_contacts": False})
    print("clean_clip warnings:")
    for w in cleaned.get("warnings", []):
        print("  -", w)
    after = py(
        "import maya.cmds as cmds\n"
        "src, leaf = %r, %r\n"
        "{'alive': cmds.objExists(src),\n"
        " 'keys': cmds.keyframe(src, q=True, valueChange=True),\n"
        " 'floats': cmds.keyframe(src, q=True, floatChange=True),\n"
        " 'value_now': cmds.getAttr(leaf + '.rotateX'),\n"
        " 'time_curves_on_leaf': cmds.listConnections(leaf + '.rotateX', "
        "s=True, d=False, type='animCurve')}" % (sdk["curve"], leaf),
        "sdk after clean")
    print(json.dumps(after, indent=1))
    FINDINGS["A_after"] = after
    FINDINGS["A_clean_warnings"] = cleaned.get("warnings")

    # ------------------------------------------------------------------ C
    section("C. a LOCKED root.translateY under author_clip root_position")
    py("import maya.cmds as cmds\ncmds.setAttr(%r + '.translateY', lock=True)\n"
       "cmds.getAttr(%r + '.translateY', lock=True)" % (root, root), "lock")
    hop = send("author_clip", {
        "root": root, "name": "hop", "fps": 30,
        "keys": [{"time_s": 0.0, "rotations": {mid: [0, 0, 0]},
                  "root_position": [0, 0, 0]},
                 {"time_s": 0.5, "rotations": {mid: [0, 0, 5]},
                  "root_position": [0, 0.3, 0]},
                 {"time_s": 1.0, "rotations": {mid: [0, 0, 0]},
                  "root_position": [0, 0, 0]}]})
    print("status:", hop.get("status"))
    if hop.get("status") == "ok":
        res = hop["result"]
        print("root_position_keyed:", res.get("root_position_keyed"))
        for w in res.get("warnings", []):
            print("  -", w)
        FINDINGS["C"] = {"status": "ok",
                         "root_position_keyed": res.get("root_position_keyed"),
                         "warnings": res.get("warnings")}
    else:
        print(json.dumps(hop.get("error"), indent=1)[:2000])
        FINDINGS["C"] = {"status": "refused", "error": hop.get("error")}
    locked = py(
        "import maya.cmds as cmds\n"
        "root, leaf = %r, %r\n"
        "cmds.setAttr(leaf + '.rotateZ', lock=True)\n"
        "before = cmds.getAttr(root + '.translate')[0]\n"
        "try:\n"
        "    cmds.xform(root, ws=True, t=[1.0, 2.0, 3.0]); xf = 'no raise'\n"
        "except Exception as exc:\n"
        "    xf = 'raised: %%s' %% exc\n"
        "{'setkey_locked_rotateZ': cmds.setKeyframe(leaf, at='rotateZ', "
        "t=3, v=9.0),\n"
        " 'setkey_locked_translateY': cmds.setKeyframe(root, "
        "at='translateY', t=99, v=9.0),\n"
        " 'setkey_free_rotateY': cmds.setKeyframe(leaf, at='rotateY', t=3, "
        "v=9.0),\n"
        " 'xform_on_locked_y': xf,\n"
        " 'translate_before': before,\n"
        " 'translate_after': cmds.getAttr(root + '.translate')[0],\n"
        " 'lock_query_compound': cmds.getAttr(root + '.translate', "
        "lock=True),\n"
        " 'lock_query_child': cmds.getAttr(root + '.translateY', "
        "lock=True)}" % (root, leaf), "locked plug writes")
    print(json.dumps(locked, indent=1))
    FINDINGS["C_locked_writes"] = locked


def probe_d():
    # ------------------------------------------------------------------ D
    section("D. blend-walk cost of cut_replaced_range on a 60-joint rig")
    ok("new_scene", {"confirm": True})
    big = ok("create_skeleton", {
        "chain": [[0, i * 0.1, 0] for i in range(60)], "chain_prefix": "b"})
    broot = big["root"]
    bnames = [j["name"] for j in big["joints"]]
    j5, j30 = bnames[5], bnames[30]

    def big_clip():
        return ok("author_clip", {
            "root": broot, "name": "a", "fps": 30,
            "keys": [{"time_s": 0.0, "rotations": {j5: [0, 0, 0],
                                                    j30: [0, 0, 0]}},
                     {"time_s": 0.5, "rotations": {j5: [0, 0, 15],
                                                    j30: [0, 10, 0]}},
                     {"time_s": 1.0, "rotations": {j5: [0, 0, 0],
                                                    j30: [0, 0, 0]}}]})

    big_clip()
    t0 = time.perf_counter()
    big_clip()
    reauthor_s = time.perf_counter() - t0
    print("re-author wall time over the wire: %.3fs" % reauthor_s)
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
        "out = {}\n"
        "try:\n"
        "    cmds.listConnections = counting\n"
        "    count[0] = 0\n"
        "    t = time.perf_counter()\n"
        "    notes = clip.cut_replaced_range(cmds, joints, rec)\n"
        "    out['with_walk'] = {'s': time.perf_counter() - t, "
        "'listConnections': count[0], 'notes': len(notes)}\n"
        "    saved = clip._curve_behind_a_blend\n"
        "    clip._curve_behind_a_blend = lambda c, p: (None, None)\n"
        "    try:\n"
        "        count[0] = 0\n"
        "        t = time.perf_counter()\n"
        "        notes = clip.cut_replaced_range(cmds, joints, rec)\n"
        "        out['without_walk'] = {'s': time.perf_counter() - t, "
        "'listConnections': count[0], 'notes': len(notes)}\n"
        "    finally:\n"
        "        clip._curve_behind_a_blend = saved\n"
        "finally:\n"
        "    cmds.listConnections = orig\n"
        "out['joints'] = len(joints)\n"
        "out" % broot, "timing")
    print(json.dumps(timing, indent=1))
    FINDINGS["D"] = dict(timing, reauthor_wire_s=reauthor_s)


def probe_b():
    # ------------------------------------------------------------------ B
    section("B. retarget_clip then author_clip: does the walk bleed?")
    ok("new_scene", {"confirm": True})
    skel = ok("create_skeleton", {"joints": JOINTS})
    hroot = skel["root"]
    walk = ok("retarget_clip", {"file": WALK_BVH, "root": hroot,
                                "clip": "walk01", "start": 1, "end": 301},
              600.0)
    print("walk01: frames=%s fps=%s" % (walk["frames"], walk["fps"]))
    for w in walk.get("warnings", []):
        print("  -", w[:300])
    baked = py(
        "import maya.cmds as cmds\n"
        "from maya_plugin.handlers import clip, rigging, mocapmath\n"
        "root = %r\n"
        "joints = rigging._hierarchy_joints(cmds, root)\n"
        "by_short = {clip._short(j): j for j in joints}\n"
        "slots = [by_short[s] for s in mocapmath.SKELETON_HIK_MAP.values()]\n"
        "per_attr = {}\n"
        "for j in slots:\n"
        "    for a in cmds.listAttr(j, keyable=True) or []:\n"
        "        cs = cmds.listConnections('%%s.%%s' %% (j, a), s=True, "
        "d=False, type='animCurve') or []\n"
        "        if cs:\n"
        "            per_attr.setdefault(a, []).append(clip._short(j))\n"
        "recs = clip.clip_meta(cmds, root)\n"
        "pelvis = by_short['pelvis']\n"
        "pk = cmds.keyframe(pelvis + '.rotateX', q=True) or []\n"
        "def spread(j, a):\n"
        "    vs = cmds.keyframe(j + '.' + a, q=True, vc=True) or [0]\n"
        "    return max(vs) - min(vs)\n"
        "{'curves_per_attr': {a: len(v) for a, v in per_attr.items()},\n"
        " 'records': recs,\n"
        " 'pelvis_keys': len(pk),\n"
        " 'pelvis_key_range': [min(pk), max(pk)] if pk else None,\n"
        " 'non_root_translate_spread': {clip._short(j): spread(j, "
        "'translateX') for j in slots if j != root and "
        "cmds.keyframe(j + '.translateX', q=True)},\n"
        " 'scale_spread': {clip._short(j): spread(j, 'scaleX') for j in "
        "slots if cmds.keyframe(j + '.scaleX', q=True)},\n"
        " 'root_is_slot': root in slots}" % hroot, "baked channels")
    print(json.dumps(baked, indent=1)[:3000])
    FINDINGS["B_after_retarget"] = baked
    walk_rec = baked["records"][0]
    idle = ok("author_clip", {
        "root": hroot, "name": "idle", "fps": walk["fps"],
        "keys": [{"time_s": 0.0, "rotations": {"head": [10, 0, 0]}},
                 {"time_s": 0.5, "rotations": {"head": [0, 0, 20]}},
                 {"time_s": 1.0, "rotations": {"head": [10, 0, 0]}}]})
    print("idle: frames %s-%s padded=%s held=%s back_filled=%s"
          % (idle["start_frame"], idle["end_frame"], idle["padded_channels"],
             idle["held_channels"], idle["back_filled"]))
    for w in idle.get("warnings", []):
        print("  -", w[:300])
    bleed = py(
        "import maya.cmds as cmds\n"
        "from maya_plugin.handlers import clip, rigging, mocapmath\n"
        "root = %r\n"
        "s, e, ws, we = %d, %d, %d, %d\n"
        "joints = rigging._hierarchy_joints(cmds, root)\n"
        "by_short = {clip._short(j): j for j in joints}\n"
        "out = {}\n"
        "for slot in ('pelvis', 'L_hip', 'L_knee', 'spine_01', "
        "'L_shoulder'):\n"
        "    j = by_short[slot]\n"
        "    for a in ('rotateX', 'rotateY', 'rotateZ', 'translateX', "
        "'translateY'):\n"
        "        plug = '%%s.%%s' %% (j, a)\n"
        "        times = cmds.keyframe(plug, q=True) or []\n"
        "        if not times:\n"
        "            continue\n"
        "        out['%%s.%%s' %% (slot, a)] = {\n"
        "            'key_at_idle_start': float(s) in times,\n"
        "            'key_at_idle_end': float(e) in times,\n"
        "            'walk_last': cmds.getAttr(plug, time=we),\n"
        "            'at_idle_start': cmds.getAttr(plug, time=s),\n"
        "            'at_idle_mid': cmds.getAttr(plug, time=(s + e) // 2),\n"
        "            'at_idle_end': cmds.getAttr(plug, time=e),\n"
        "            'static_rest': cmds.getAttr(plug, time=-50)}\n"
        "head = by_short['head'] + '.rotateX'\n"
        "out['head.rotateX'] = {'at_walk_start': cmds.getAttr(head, "
        "time=ws), 'at_walk_end': cmds.getAttr(head, time=we), "
        "'times': cmds.keyframe(head, q=True)}\n"
        "out['records'] = clip.clip_meta(cmds, root)\n"
        "out" % (hroot, idle["start_frame"], idle["end_frame"],
                 walk_rec["start_frame"], walk_rec["end_frame"]),
        "bleed")
    print(json.dumps(bleed, indent=1))
    FINDINGS["B_bleed"] = bleed


if __name__ == "__main__":
    main()
