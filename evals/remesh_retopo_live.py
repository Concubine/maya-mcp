"""#819 LIVE GATE: remesh_retopo, measured for the first time.

  1. a 400-face sphere with UVs -> target 200: polyRetopo ran, the face count
     lands within polyRetopo's 10 % tolerance of the target, `faces` and
     `faces_before` are reported, the UVs the retopo destroyed are TRANSFERRED
     back from the kept original (uvs.after > 0, transferred), transform /
     pivot / shading group / shell count survive, history is gone, and a
     warning names the hidden original as something an export will ship.
  2. the same with keep_original=false: no original to transfer from, so
     uvs.after is 0 and a warning says so, naming maya_uv_atlas.
  3. MEASURED claim behind the warning: export_fbx of the scene from (1)
     writes TWO meshes - the hidden original travels.
  4. a two-shell combine -> 300: shells stay 2, faces within tolerance.

No captures. DESTRUCTIVE: calls maya_new_scene. Agent Maya on 9878 only;
refuses 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1. Phase 0 asserts the live
Maya imports THIS working tree.

Run:  MAYA_MCP_PORT=9878 python evals/remesh_retopo_live.py
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

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
    print("refusing to run against port 9877 (the user's Maya): this gate "
          "calls new_scene. Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.",
          file=sys.stderr)
    raise SystemExit(2)

OUT = os.path.join(_HERE, "remesh_retopo_live")
os.makedirs(OUT, exist_ok=True)
RESULTS = []
TOL = 0.10  # polyRetopo's own targetFaceCountTolerance (measured 10 on the node)


def check(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    print("%-4s %-72s %s" % ("PASS" if ok else "FAIL", label, detail), flush=True)


def ok(command, params, timeout_s=300.0):
    response = call(command, params, timeout_s=timeout_s, port=PORT)
    if response.get("status") != "ok":
        raise SystemExit("%s failed: %s" % (command, response.get("error")))
    return response.get("result") or {}


def py(code, what, timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s), what)


STATE = r'''
import maya.cmds as cmds
t = %r
sh = (cmds.listRelatives(t, s=True, f=True, ni=True) or [None])[0]
{"faces": cmds.polyEvaluate(t, f=True), "uvs": cmds.polyEvaluate(t, uv=True), "shells": cmds.polyEvaluate(t, shell=True),
 "sg": sorted(cmds.listSets(object=sh, type=1) or []), "translate": cmds.xform(t, q=True, ws=True, t=True),
 "pivot": [round(v, 3) for v in cmds.xform(t, q=True, ws=True, rp=True)],
 "history": [n for n in (cmds.listHistory(t, pdo=True) or []) if cmds.nodeType(n) != "mesh"],
 "meshes": sorted(cmds.ls(type="mesh"))}
'''


def state(t):
    return py(STATE % t, "state")


def within(faces, target):
    return abs(faces - target) <= TOL * target


def sphere_scene():
    ok("new_scene", {"confirm": True})
    py("import maya.cmds as cmds\ncmds.polySphere(name='ball', r=1, sx=20, sy=20)\n"
       "cmds.xform('ball', t=(2, 1, -3)); cmds.xform('ball', ws=True, rp=(2, 0, -3))\n"
       "sh = cmds.shadingNode('lambert', asShader=True, name='red'); sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name='redSG')\n"
       "cmds.connectAttr(sh + '.outColor', sg + '.surfaceShader'); cmds.sets('ball', e=True, forceElement=sg)\nTrue", "scene")


# --------------------------------------------------------------- phase 0
print("=== 0. who answered, and whose code is it ===", flush=True)
ident = py("import os, maya_plugin\n{'file': maya_plugin.__file__, 'cwd': os.getcwd()}", "identity")
loaded = os.path.normcase(os.path.abspath(ident["file"]))
expected = os.path.normcase(os.path.join(REPO, "maya_plugin", "__init__.py"))
if loaded != expected:
    print("WRONG CODE: live Maya imports %s, not %s." % (loaded, expected), file=sys.stderr)
    raise SystemExit(2)
has = py("import inspect\nfrom maya_plugin.handlers import modeling\n'transferAttributes' in inspect.getsource(modeling.remesh_retopo)", "loaded")
check("0. the #819 remesh handler is loaded in the live Maya", has is True)

# --------------------------------------------------------------- phase 1
print("\n=== 1. sphere with UVs, keep_original (default) ===", flush=True)
sphere_scene()
before = state("|ball")
res = ok("remesh_retopo", {"mesh": "|ball", "target_polycount": 200})
after = state("|ball")
check("1a. polyRetopo ran and the face count is within 10% of the target",
      res.get("method") == "polyRetopo" and within(after["faces"], 200) and res.get("faces") == after["faces"],
      "method %r faces %r (target 200)" % (res.get("method"), res.get("faces")))
check("1b. faces_before and target_polycount are reported alongside",
      res.get("faces_before") == before["faces"] == 400 and res.get("target_polycount") == 200,
      json.dumps({k: res.get(k) for k in ("faces_before", "target_polycount", "tris")}))
uv = res.get("uvs") or {}
check("1c. the UVs polyRetopo destroyed were transferred back from the kept original",
      uv.get("before") == before["uvs"] and uv.get("transferred") is True and (uv.get("after") or 0) > 0
      and after["uvs"] == uv.get("after"),
      json.dumps(uv))
check("1d. transform, pivot, shading group and shell survive; history is gone",
      after["translate"] == before["translate"] and after["pivot"] == before["pivot"]
      and after["sg"] == ["redSG"] and after["shells"] == 1 and after["history"] == [],
      json.dumps({k: after[k] for k in ("translate", "pivot", "sg", "history")}))
check("1e. a warning names the hidden original as something an export ships",
      any("ball_orig" in w and "export" in w for w in res.get("warnings", [])),
      json.dumps(res.get("warnings")))
check("1f. no UV warning when the transfer succeeded",
      not any("UV" in w and "uv_atlas" in w for w in res.get("warnings", [])), json.dumps(res.get("warnings")))

# --------------------------------------------------------------- phase 3 (same scene)
print("\n=== 3. the claim behind 1e: export ships the hidden original ===", flush=True)
path = os.path.join(OUT, "ball.fbx").replace("\\", "/")
exp = ok("export_fbx", {"path": path, "metres_per_unit": 1.0})
check("3. export_fbx of the scene writes TWO meshes - the hidden original travels",
      exp.get("mesh_count") == 2, "mesh_count %r" % exp.get("mesh_count"))

# --------------------------------------------------------------- phase 2
print("\n=== 2. keep_original=false ===", flush=True)
sphere_scene()
res2 = ok("remesh_retopo", {"mesh": "|ball", "target_polycount": 200, "keep_original": False})
after2 = state("|ball")
uv2 = res2.get("uvs") or {}
check("2a. no original: UVs are gone and the result says 0, not transferred",
      res2.get("original") is None and uv2.get("after") == 0 and uv2.get("transferred") is False
      and after2["uvs"] == 0 and after2["meshes"] == ["ballShape"],
      json.dumps(uv2))
check("2b. ... and a warning names the loss and maya_uv_atlas",
      any("UV" in w and "uv_atlas" in w for w in res2.get("warnings", [])), json.dumps(res2.get("warnings")))
check("2c. ... and no hidden-original warning", not any("export" in w for w in res2.get("warnings", [])))

# --------------------------------------------------------------- phase 4
print("\n=== 4. two-shell combine ===", flush=True)
ok("new_scene", {"confirm": True})
py("import maya.cmds as cmds\ncmds.polyCube(name='a'); cmds.polyCube(name='b'); cmds.xform('b', t=(3, 0, 0))\nTrue", "pair")
ok("combine", {"names": ["|a", "|b"], "name": "pair"})
res4 = ok("remesh_retopo", {"mesh": "|pair", "target_polycount": 300})
after4 = state("|pair")
check("4. two shells stay two; faces within tolerance; UVs transferred",
      after4["shells"] == 2 and within(after4["faces"], 300) and (res4.get("uvs") or {}).get("after", 0) > 0,
      "shells %r faces %r uvs %r" % (after4["shells"], after4["faces"], res4.get("uvs")))

# --------------------------------------------------------------- summary
ok("new_scene", {"confirm": True})
passed = sum(1 for _, r, _ in RESULTS if r)
print("\n%d / %d passed" % (passed, len(RESULTS)))
with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as fh:
    json.dump([{"check": label, "ok": r, "detail": d} for label, r, d in RESULTS], fh, indent=1)
raise SystemExit(0 if passed == len(RESULTS) else 1)
