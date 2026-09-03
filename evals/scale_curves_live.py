"""Live gate for redmine #810: the bake writes six channels, and delete_clip
reaps what earlier bakes left.

MEASURED before the fix (evals/scale_curves_probe.py, 2026-09-03): a
retarget keyed 45 rotate + 45 translate + 45 SCALE curves on the humanoid,
every scale key exactly 1.0; export_fbx(include_animation=true) wrote 15
"Lcl Scaling" curve nodes per take; delete_clip reported 90 deleted, left
the 45 scale curves, and then refused "no clip exists" on a rig still
keyed; an author_clip on that rig shipped the 15 scale nodes in ITS take.

This gate asserts the fixed shape over the wire and on the bytes:
  A. after a retarget: 45 rotate, 45 translate, 0 scale curves; the export
     carries no "Lcl Scaling" curve node in any take.
  B. leftovers planted the way the old bake left them (constant 1.0 scale
     keys on every slot joint) are reaped by delete_clip and named; a
     scale curve carrying real values is kept and named; a rig whose only
     keys are leftovers no longer refuses.
  C. an author_clip after that exports a take with no scale nodes.

DESTRUCTIVE: calls new_scene. Refuses 9877 (the user's Maya) unless
MAYA_MCP_ALLOW_USER_SESSION=1. The Maya must run this working tree's plugin.

Run:  MAYA_MCP_PORT=9879 MAYA_MCP_EXPECT_PID=<pid> .venv/Scripts/python.exe evals/scale_curves_live.py
Exit: 0 pass, 1 fail, 2 environment.
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, _HERE)
from live_call import call, structured_result  # noqa: E402
from humanoid_live import JOINTS  # noqa: E402
from maya_plugin.handlers import fbxbytes  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9879"))
if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
    print("refusing 9877 (the user's Maya): this gate calls new_scene", file=sys.stderr)
    raise SystemExit(2)

WALK_BVH = os.path.join(_HERE, "mocap_fixtures", "cmu_walk.bvh")
OUT = os.path.join(_HERE, "scale_curves_probe_810")
os.makedirs(OUT, exist_ok=True)
CHECKS = []


def check(label, passed, detail=""):
    CHECKS.append((bool(passed), label))
    print("%-4s %s%s" % ("PASS" if passed else "FAIL", label,
                         ("  [%s]" % detail) if detail else ""))
    return bool(passed)


def send(command, params, timeout_s=600.0):
    try:
        return call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)


def ok(command, params, timeout_s=600.0):
    r = send(command, params, timeout_s)
    if r.get("status") != "ok":
        print("FAIL %s: %s" % (command, json.dumps(r.get("error"))[:600]))
        sys.exit(1)
    return r.get("result") or {}


def py(code, what):
    return structured_result(ok("execute_python", {"code": code}), what)


def census(joints):
    return py(
        "import maya.cmds as cmds\n"
        "joints = %r\n"
        "out = {'rotate': 0, 'translate': 0, 'scale': 0}\n"
        "for j in joints:\n"
        "    for grp in out:\n"
        "        for ax in 'XYZ':\n"
        "            out[grp] += len(cmds.listConnections('%%s.%%s%%s' %% (j, grp, ax), s=True, d=False, type='animCurve') or [])\n"
        "out" % (joints,), "curve census")


def scaling_nodes(name, animation=True):
    path = os.path.join(OUT, name + ".fbx")
    r = send("export_fbx", {"path": path, "metres_per_unit": 1.0,
                            "include_animation": animation, "include_skins": False})
    if r.get("status") != "ok":
        return {"refused": (r.get("error") or {}).get("message", "")[:200]}
    anim = fbxbytes.anim_facts(fbxbytes.read_fbx(path))
    scaling = [t for t in anim["targets"] if "Scaling" in (t["property"] or "")
               and (t["curves"] or 0) > 0]
    return {"takes": [t["name"] for t in anim["takes"]], "curve_nodes": anim["curve_nodes"],
            "scaling_nodes_with_curves": len(scaling)}


def main():
    ident = py("import os, maya_plugin\n{'pid': os.getpid(), 'plugin': maya_plugin.__file__}",
               "identity")
    print("maya on %d: pid %s\nplugin: %s\n" % (PORT, ident["pid"], ident["plugin"]))
    if os.path.normcase(REPO) not in os.path.normcase(ident["plugin"]):
        print("the live Maya runs the plugin at %s, not this working tree" % ident["plugin"])
        sys.exit(2)
    ok("new_scene", {"confirm": True})
    skel = ok("create_skeleton", {"joints": JOINTS})
    root = skel["root"]
    joints = [j["name"] for j in skel["joints"]]

    # ---- A. the bake writes six channels --------------------------------
    walk = ok("retarget_clip", {"file": WALK_BVH, "root": root, "clip": "walk",
                                "start": 1, "end": 121, "fps": 30})
    c = census(joints)
    check("A. after a retarget the rig carries rotate + translate curves and NO "
          "scale curves", c["rotate"] == 45 and c["translate"] == 45 and c["scale"] == 0,
          json.dumps(c))
    check("A. ... and the clip still has its frames", walk.get("frames", 0) > 20,
          "frames %s" % walk.get("frames"))
    ex = scaling_nodes("walk_anim")
    check("A. the animated export carries no scaling curve node in any take",
          ex.get("scaling_nodes_with_curves") == 0 and "walk" in ex.get("takes", []),
          json.dumps(ex))
    deleted = ok("delete_clip", {"root": root})
    check("A. delete_clip after the fixed bake reaps nothing on scale and says "
          "nothing about it",
          deleted.get("reaped_scale_curves") == 0
          and not any("scale" in w for w in deleted.get("warnings", [])),
          json.dumps({"reaped_scale_curves": deleted.get("reaped_scale_curves"),
                      "warnings": deleted.get("warnings")})[:300])
    c = census(joints)
    check("A. ... and the rig is bare", c == {"rotate": 0, "translate": 0, "scale": 0},
          json.dumps(c))

    # ---- B. leftovers of the OLD bake are reaped -------------------------
    slots = py("from maya_plugin.handlers import mocapmath\n"
               "sorted(set(mocapmath.SKELETON_HIK_MAP.values()))", "slot shorts")
    slot_joints = [j for j in joints if j.rsplit("|", 1)[-1] in slots]
    py("import maya.cmds as cmds\n"
       "for j in %r:\n"
       "    for ax in 'XYZ':\n"
       "        for f in range(0, 31):\n"
       "            cmds.setKeyframe(j, attribute='scale' + ax, time=f, value=1.0)\n"
       "len(cmds.ls(type='animCurve'))" % (slot_joints,), "plant leftovers")
    c = census(joints)
    check("B. setup: the old bake's signature planted - %d constant scale curves"
          % (3 * len(slot_joints)), c["scale"] == 3 * len(slot_joints), json.dumps(c))
    # A NON-slot joint, so the real-valued curve sits beside the 45 planted
    # identity curves rather than overwriting one of them.
    real_joint = next(j for j in joints if j not in slot_joints)
    py("import maya.cmds as cmds\n"
       "j = %r\n"
       "for f, v in ((0, 1.0), (10, 1.3), (20, 1.0)):\n"
       "    cmds.setKeyframe(j, attribute='scaleY', time=f, value=v)\n"
       "cmds.keyframe(j + '.scaleY', q=True, valueChange=True)" % (real_joint,),
       "plant a real scale curve on a non-slot joint")
    only = ok("delete_clip", {"root": root})
    c = census(joints)
    check("B. a rig whose only keys are leftovers no longer refuses: delete_clip "
          "reaps the constant scale curves and names them",
          only.get("clip") is None
          and only.get("reaped_scale_curves") == 3 * len(slot_joints)
          and any("constant" in w and "scale" in w for w in only.get("warnings", []))
          and c["scale"] == 1,
          json.dumps({"reaped": only.get("reaped_scale_curves"), "census": c}))
    check("B. the scale curve carrying real values is KEPT and named",
          c["scale"] == 1 and any("kept" in w and "scaleY" in w for w in only.get("warnings", [])),
          json.dumps([w for w in only.get("warnings", []) if "scale" in w])[:300])

    # ---- C. a later authored clip exports no scale nodes -----------------
    # Delete the planted real curve NODE (a cutKey with no range left it
    # standing once): a rig that still carries a real scale curve exports
    # it, correctly - C is about the cleaned rig.
    gone = py("import maya.cmds as cmds\n"
              "crv = cmds.listConnections(%r + '.scaleY', s=True, d=False, type='animCurve') or []\n"
              "cmds.delete(*crv) if crv else None\n"
              # the joint keeps the value the curve last evaluated (1.3 at
              # frame 10) - a non-identity scale the export gate refuses.
              "cmds.setAttr(%r + '.scaleY', 1.0)\n"
              "len(cmds.listConnections(%r + '.scaleY', s=True, d=False, type='animCurve') or [])"
              % (real_joint, real_joint, real_joint), "remove the planted real curve")
    check("C. setup: the planted real scale curve is gone", gone == 0, "left %s" % gone)
    nod = ok("author_clip", {"root": root, "name": "nod", "fps": 30, "keys": [
        {"time_s": 0.0, "rotations": {"neck": [0, 0, 0]}},
        {"time_s": 0.5, "rotations": {"neck": [0, 0, 15]}},
        {"time_s": 1.0, "rotations": {"neck": [0, 0, 0]}}]})
    ex = scaling_nodes("nod_anim")
    check("C. an authored clip on the cleaned rig exports a take with no scaling "
          "curve node", ex.get("scaling_nodes_with_curves") == 0 and "nod" in ex.get("takes", []),
          json.dumps(ex))

    failed = [label for passed, label in CHECKS if not passed]
    print("\n%d checks, %d failed" % (len(CHECKS), len(failed)))
    for label in failed:
        print("  FAIL " + label)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
