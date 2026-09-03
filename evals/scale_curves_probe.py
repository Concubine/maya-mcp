"""#810 PROBE - measure before designing (the #796 rule).

retarget_clip bakes with `cmds.bakeResults` and no `-attribute` flag, which
(#798 measured) keys rotate, translate AND scale on every slot joint. Every
clip tool walks `clip._joint_plugs` = rotate + translate. So:

  1. after delete_clip, how many scale animCurves survive on the rig, and
     does a second delete_clip claim "no clip exists" on a rig still keyed?
  2. does a re-retarget after the delete proceed, refuse, or double them?
  3. does export_fbx(include_animation=true) carry the constant scale curves
     into the take (fbxbytes: curve nodes on "Lcl Scaling"), and does
     include_animation=false stay free of them?
  4. does author_clip after the delete notice them, and does ITS take then
     carry scale records?

Run:  MAYA_MCP_PORT=9879 MAYA_MCP_EXPECT_PID=<pid> .venv/Scripts/python.exe evals/scale_curves_probe.py
DESTRUCTIVE: calls new_scene. Refuses 9877 (the user's Maya).
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
    print("refusing 9877 (the user's Maya): this probe calls new_scene", file=sys.stderr)
    raise SystemExit(2)

WALK_BVH = os.path.join(_HERE, "mocap_fixtures", "cmu_walk.bvh")
OUT = os.path.join(_HERE, "scale_curves_probe_810")
os.makedirs(OUT, exist_ok=True)
FINDINGS = {}


def send(command, params, timeout_s=600.0):
    return call(command, params, timeout_s=timeout_s, port=PORT)


def ok(command, params, timeout_s=600.0):
    r = send(command, params, timeout_s)
    if r.get("status") != "ok":
        print("FAIL %s: %s" % (command, json.dumps(r.get("error"))[:600]))
        sys.exit(1)
    return r.get("result") or {}


def py(code, what):
    return structured_result(ok("execute_python", {"code": code}), what)


def curve_census(joints):
    return py(
        "import maya.cmds as cmds\n"
        "joints = %r\n"
        "out = {'rotate': 0, 'translate': 0, 'scale': 0, 'scale_nonconst': 0, 'scale_values': set()}\n"
        "for j in joints:\n"
        "    for grp, attrs in (('rotate', 'XYZ'), ('translate', 'XYZ'), ('scale', 'XYZ')):\n"
        "        for ax in attrs:\n"
        "            plug = '%%s.%%s%%s' %% (j, grp, ax)\n"
        "            srcs = cmds.listConnections(plug, s=True, d=False, type='animCurve') or []\n"
        "            out[grp] += len(srcs)\n"
        "            if grp == 'scale' and srcs:\n"
        "                vals = cmds.keyframe(srcs[0], q=True, valueChange=True) or []\n"
        "                out['scale_values'].update(round(v, 6) for v in vals)\n"
        "                if len(set(round(v, 6) for v in vals)) > 1:\n"
        "                    out['scale_nonconst'] += 1\n"
        "out['scale_values'] = sorted(out['scale_values'])[:5]\n"
        "out['total_animcurves_in_scene'] = len(cmds.ls(type='animCurve'))\n"
        "out" % (joints,), "curve census")


def export(name, animation):
    path = os.path.join(OUT, name + ".fbx")
    r = send("export_fbx", {"path": path, "metres_per_unit": 1.0,
                            "include_animation": animation, "include_skins": False})
    if r.get("status") != "ok":
        return {"refused": (r.get("error") or {}).get("message", "")[:300]}
    facts = fbxbytes.read_fbx(path)
    anim = fbxbytes.anim_facts(facts)
    scaling = [t for t in anim["targets"] if "Scaling" in (t["property"] or "")]
    return {"takes": [t["name"] for t in anim["takes"]],
            "curve_nodes": anim["curve_nodes"], "curves": anim["curves"],
            "scaling_nodes": len(scaling),
            "scaling_by_take": sorted({(t["take"], t["key_count"]) for t in scaling},
                                      key=str),
            "unavailable": anim["unavailable_reason"]}


def main():
    ident = py("import os, maya_plugin\n{'pid': os.getpid(), 'plugin': maya_plugin.__file__}",
               "identity")
    print("maya on %d: pid %s plugin %s" % (PORT, ident["pid"], ident["plugin"]))
    if os.path.normcase(REPO) not in os.path.normcase(ident["plugin"]):
        print("wrong plugin loaded (not this working tree)"); sys.exit(2)

    ok("new_scene", {"confirm": True})
    skel = ok("create_skeleton", {"joints": JOINTS})
    root = skel["root"]
    joints = [j["name"] for j in skel["joints"]]
    FINDINGS["0_clean"] = curve_census(joints)
    FINDINGS["0_clean_export_static"] = export("clean_static", False)

    # 1. retarget, then delete
    walk = ok("retarget_clip", {"file": WALK_BVH, "root": root, "clip": "walk",
                                "start": 1, "end": 121, "fps": 30})
    FINDINGS["1_after_retarget"] = dict(curve_census(joints), frames=walk.get("frames"),
                                        warnings=[w for w in walk.get("warnings", []) if "scale" in w.lower()])
    FINDINGS["1_export_anim"] = export("walk_anim", True)
    FINDINGS["1_export_static"] = export("walk_static", False)

    deleted = ok("delete_clip", {"root": root})
    FINDINGS["2_after_delete"] = dict(curve_census(joints),
                                      delete_result={k: v for k, v in deleted.items()
                                                     if k in ("deleted_curves", "removed", "curves", "warnings", "clips")})
    again = send("delete_clip", {"root": root})
    FINDINGS["2_second_delete"] = {"status": again.get("status"),
                                   "message": (again.get("error") or {}).get("message", "")[:200]}
    FINDINGS["2_export_static_after_delete"] = export("deleted_static", False)
    FINDINGS["2_export_anim_after_delete"] = export("deleted_anim", True)

    # 3. re-retarget after the delete, same clip name
    walk2 = send("retarget_clip", {"file": WALK_BVH, "root": root, "clip": "walk",
                                   "start": 1, "end": 121, "fps": 30})
    FINDINGS["3_reretarget"] = {"status": walk2.get("status"),
                                "message": (walk2.get("error") or {}).get("message", "")[:300],
                                "census": curve_census(joints)}
    if walk2.get("status") == "ok":
        ok("delete_clip", {"root": root})

    # 4. author_clip on the rig that still carries scale curves
    nod = send("author_clip", {"root": root, "name": "nod", "fps": 30, "keys": [
        {"time_s": 0.0, "rotations": {"neck": [0, 0, 0]}},
        {"time_s": 0.5, "rotations": {"neck": [0, 0, 15]}},
        {"time_s": 1.0, "rotations": {"neck": [0, 0, 0]}}]})
    FINDINGS["4_author_after_delete"] = {
        "status": nod.get("status"),
        "message": (nod.get("error") or {}).get("message", "")[:300],
        "warnings": [w for w in (nod.get("result") or {}).get("warnings", [])][:6],
        "census": curve_census(joints)}
    FINDINGS["4_export_anim_nod"] = export("nod_anim", True)

    path = os.path.join(OUT, "findings.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(FINDINGS, fh, indent=1, default=str)
    print(json.dumps(FINDINGS, indent=1, default=str))
    print("\nwritten:", path)


if __name__ == "__main__":
    main()
