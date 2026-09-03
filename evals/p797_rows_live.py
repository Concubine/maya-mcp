"""#814 LIVE GATE: the three rows the #797 probes settled, over the wire.

  1. deform sculpt with params.rotate is REFUSED before anything is built:
     no sculpt node, mesh untouched. Control: translate alone deforms.
  2. pose_ik on a straight chain with no pole warns naming world +Z and the
     default pole vector; the knee lands on +Z; a -Z pole puts it on -Z.
  3. retarget_clip's .fbx route onto a rig whose joint NAMES the file shares
     (the ordinary case): the take lands as a real bake at the file's own
     rate - 158 frames at 60 fps in a scene that started at 24 - the source
     skeleton is imported as NEW nodes and reaped, the target rig's joint
     set is unchanged (no merge onto it, no `pelvis1`), and measure_clip
     agrees with the BVH take it was exported from. A refused call (fps on
     the .fbx route) leaves the rig without a single key.

No captures - this gate never shows a Maya window.
DESTRUCTIVE: calls maya_new_scene. Agent Maya on 9878 only; refuses 9877
unless MAYA_MCP_ALLOW_USER_SESSION=1. The live Maya must import THIS working
tree (repo cwd) - phase 0 asserts it.

Run:  MAYA_MCP_PORT=9878 python evals/p797_rows_live.py
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
import humanoid_live  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
    print("refusing to run against port 9877 (the user's Maya): this gate "
          "calls new_scene. Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.",
          file=sys.stderr)
    raise SystemExit(2)

OUT = os.path.join(_HERE, "p797_rows_live")
os.makedirs(OUT, exist_ok=True)
WALK_BVH = os.path.join(_HERE, "mocap_fixtures", "cmu_walk.bvh").replace("\\", "/")
RESULTS = []


def check(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    print("%-4s %-72s %s" % ("PASS" if ok else "FAIL", label, detail), flush=True)


def send(command, params, timeout_s=600.0):
    return call(command, params, timeout_s=timeout_s, port=PORT)


def ok(command, params, timeout_s=600.0):
    response = send(command, params, timeout_s)
    if response.get("status") != "ok":
        raise SystemExit("%s failed: %s" % (command, response.get("error")))
    return response.get("result") or {}


def refusal(command, params, timeout_s=600.0):
    response = send(command, params, timeout_s)
    return None if response.get("status") == "ok" else (response.get("error") or {})


def py(code, what, timeout_s=600.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s), what)


def fresh():
    ok("new_scene", {"confirm": True})


# --------------------------------------------------------------- phase 0
print("=== 0. who answered, and whose code is it ===", flush=True)
ident = py("import os, maya_plugin\n{'file': maya_plugin.__file__, 'cwd': os.getcwd()}", "identity")
loaded = os.path.normcase(os.path.abspath(ident["file"]))
expected = os.path.normcase(os.path.join(REPO, "maya_plugin", "__init__.py"))
if loaded != expected:
    print("WRONG CODE: live Maya imports %s, not %s." % (loaded, expected), file=sys.stderr)
    raise SystemExit(2)
has = py("from maya_plugin.handlers import retarget\n"
         "hasattr(retarget, '_import_fbx_source') and hasattr(retarget, '_fbx_source_fps')", "loaded")
check("0. the #814 retarget helpers are loaded in the live Maya", has is True)

# --------------------------------------------------------------- phase 1
print("\n=== 1. sculpt rotate is refused before anything is built ===", flush=True)
fresh()
py("import maya.cmds as cmds\ncmds.polyPlane(name='slab', w=4, h=4, sx=20, sy=20)\nTrue", "slab")
err = refusal("deform", {"mesh": "|slab", "deformer": "sculpt",
                         "params": {"translate": [0, 0.3, 0], "rotate": [45, 30, 0]}})
state = py("import maya.cmds as cmds\n"
           "{'sculpts': cmds.ls(type='sculpt'), 'maxy': max(cmds.xform('|slab.vtx[%d]' % i, q=True, ws=True, t=True)[1] "
           "for i in range(cmds.polyEvaluate('|slab', v=True)))}", "state")
check("1a. refused, naming rotate, sculpt and the sphere",
      err is not None and "does not use" in err.get("message", "") and "rotate" in err.get("message", "")
      and "sphere" in err.get("message", ""), json.dumps(err)[:160])
check("1b. ... nothing built, mesh untouched", state["sculpts"] == [] and abs(state["maxy"]) < 1e-9,
      json.dumps(state))
ctl = ok("deform", {"mesh": "|slab", "deformer": "sculpt", "params": {"translate": [0, 0.3, 0]}})
check("1c. CONTROL: translate alone deforms", (ctl.get("max_displacement") or 0) > 0.5,
      "max_displacement %r" % ctl.get("max_displacement"))

# --------------------------------------------------------------- phase 2
print("\n=== 2. pose_ik straight chain: the warning names the measured default ===", flush=True)


def solve(pole):
    fresh()
    sk = ok("create_skeleton", {"chain": [[0, 1, 0], [0, 0.5, 0], [0, 0, 0]], "chain_prefix": "leg"})
    joints = [j["name"] for j in sk["joints"]]
    params = {"root": sk["root"], "joint": joints[-1], "target": [0, 0.3, 0]}
    if pole is not None:
        params["pole"] = pole
    res = ok("pose_ik", params)
    knee = py("import maya.cmds as cmds\n[round(v, 4) for v in cmds.xform(%r, q=True, ws=True, t=True)]"
              % joints[1], "knee")
    return res, knee


res, knee = solve(None)
straight = [w for w in res.get("warnings", []) if "STRAIGHT" in w]
check("2a. no pole: the STRAIGHT warning names +Z and the default pole vector",
      len(straight) == 1 and "+Z" in straight[0] and "default pole vector" in straight[0],
      straight[0] if straight else json.dumps(res.get("warnings")))
check("2b. ... and the knee did go to +Z", knee[2] > 0.3, "knee %r" % knee)
res, knee = solve([0, 0.5, -1.0])
check("2c. pole -Z: no STRAIGHT warning, knee on -Z",
      not any("STRAIGHT" in w for w in res.get("warnings", [])) and knee[2] < -0.3, "knee %r" % knee)

# --------------------------------------------------------------- phase 3
print("\n=== 3. the .fbx route onto a same-named rig ===", flush=True)
fresh()
rig_a = ok("create_skeleton", {"joints": humanoid_live.JOINTS})["root"]
bvh = ok("retarget_clip", {"file": WALK_BVH, "root": rig_a, "clip": "walk", "start": 1}, 900)
m_bvh = ok("measure_clip", {"root": rig_a, "name": "walk"})
fbx_path = os.path.join(OUT, "walk_take.fbx").replace("\\", "/")
ok("export_fbx", {"path": fbx_path, "include_animation": True, "include_skins": False,
                  "metres_per_unit": 1.0, "nodes": [rig_a]})

fresh()
py("import maya.cmds as cmds\ncmds.currentUnit(time='film')\nTrue", "film")
rig_b = ok("create_skeleton", {"joints": humanoid_live.JOINTS})["root"]
RIG_STATE = r'''
import maya.cmds as cmds
js = cmds.ls(type="joint", long=True)
{"joints": sorted(js), "n_joints": len(js), "keys": len(cmds.keyframe(%r, q=True, hierarchy="below") or []),
 "unit": cmds.currentUnit(q=True, time=True),
 "namespaces": sorted(n for n in cmds.namespaceInfo(listOnlyNamespaces=True) if n not in ("UI", "shared")),
 "anim_curves": len(cmds.ls(type="animCurve"))}
''' % rig_b
before = py(RIG_STATE, "before")
err = refusal("retarget_clip", {"file": fbx_path, "root": rig_b, "clip": "walk", "fps": 24}, 900)
after_refusal = py(RIG_STATE, "after_refusal")
check("3a. fps on the .fbx route is refused (row 25 stands) ...",
      err is not None and "does not use" in err.get("message", ""), json.dumps(err)[:120])
check("3b. ... and the rig is exactly as it was: no keys, no merge, unit untouched",
      after_refusal == before, json.dumps({"before": before["keys"], "after": after_refusal["keys"],
                                           "unit": after_refusal["unit"]}))
take = ok("retarget_clip", {"file": fbx_path, "root": rig_b, "clip": "walk"}, 900)
after = py(RIG_STATE, "after")
check("3c. the take landed at the FILE's rate: 60 fps, 158 frames, scene unit now ntscf",
      take.get("fps") == 60 and take.get("frames") == 158 and after["unit"] == "ntscf",
      "fps %r frames %r unit %r" % (take.get("fps"), take.get("frames"), after["unit"]))
check("3d. the rig's joint set is unchanged - no merge onto it, no renamed import left",
      after["joints"] == before["joints"], "n_joints %d -> %d" % (before["n_joints"], after["n_joints"]))
check("3e. the source namespace and skeleton were reaped",
      after["namespaces"] == [] , json.dumps(after["namespaces"]))
check("3f. the rig carries the bake (keys on it now) and only the bake's curves",
      after["keys"] > 0 and after["anim_curves"] > 0 and after["anim_curves"] <= 15 * 6 + 20,
      "keys %d curves %d" % (after["keys"], after["anim_curves"]))
m_fbx = ok("measure_clip", {"root": rig_b, "name": "walk"})
ja, jb = m_bvh["joints"], m_fbx["joints"]
worst = max(abs(ja[j]["path_length"] - jb[j]["path_length"]) / max(ja[j]["path_length"], 1e-9) for j in ja)
check("3g. measure_clip agrees with the BVH take (path length per joint within 5%)",
      m_fbx["frames_sampled"] == m_bvh["frames_sampled"] and worst < 0.05,
      "frames %r vs %r, worst path-length deviation %.1f%%" % (m_fbx["frames_sampled"], m_bvh["frames_sampled"], worst * 100))
check("3h. the scene time unit change is reported in warnings",
      any("time unit changed" in w and "ntscf" in w for w in take.get("warnings", [])),
      json.dumps(take.get("warnings"))[:200])

# --------------------------------------------------------------- summary
fresh()
passed = sum(1 for _, r, _ in RESULTS if r)
print("\n%d / %d passed" % (passed, len(RESULTS)))
with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as fh:
    json.dump([{"check": label, "ok": r, "detail": d} for label, r, d in RESULTS], fh, indent=1)
raise SystemExit(0 if passed == len(RESULTS) else 1)
