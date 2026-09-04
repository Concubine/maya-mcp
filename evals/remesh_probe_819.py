"""#819 PROBE: what remesh_retopo actually does to a mesh on Maya 2027 - it has
never run against a real Maya. Records, does not assert.

  P0. which of polyRetopo / polyRemesh / polyReduce exist, and polyRetopo's flags
  P1. closed quad mesh (polySphere 20x20 = 400 faces) -> target 200 and 800:
      faces/tris/verts/shells before and after, result.tris vs polyEvaluate,
      UV count, shading group, transform, history, the _orig duplicate, time
  P2. polyCube (6 faces) -> target 400: what does retopo do to a box
  P3. open plane 10x10 -> target 50
  P4. two-shell combine (two cubes united) -> target 300
  P5. keep_original=False
  P6. target above the current count (sphere 400 -> 2000)
  P7. a mesh with a translate/rotate/scale and a pivot: is the transform kept
  P8. the same sphere through cmds.polyRetopo DIRECTLY, to see the raw shape
      polyRetopo produces (does it replace the shape? keep the name?)

No captures. Agent Maya on 9878 only, repo cwd.
Run:  MAYA_MCP_PORT=9878 python evals/remesh_probe_819.py
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877:
    raise SystemExit("refusing the user's Maya")
OUT = os.path.join(_HERE, "remesh_probe_819")
os.makedirs(OUT, exist_ok=True)
FINDINGS = {}


def ok(command, params, timeout_s=600.0):
    r = call(command, params, timeout_s=timeout_s, port=PORT)
    if r.get("status") != "ok":
        raise SystemExit("%s failed: %s" % (command, json.dumps(r.get("error"), indent=1)))
    return r.get("result") or {}


def result_or_error(command, params, timeout_s=600.0):
    r = call(command, params, timeout_s=timeout_s, port=PORT)
    return (r.get("result") or {}) if r.get("status") == "ok" else {"ERROR": r.get("error")}


def py(code, what="r", timeout_s=600.0):
    return structured_result(ok("execute_python", {"code": textwrap.dedent(code).strip()}, timeout_s), what)


def show(label, value):
    FINDINGS[label] = value
    with open(os.path.join(OUT, "findings.json"), "w", encoding="utf-8") as fh:
        json.dump(FINDINGS, fh, indent=1, default=str)
    print("\n--- %s ---" % label)
    print(json.dumps(value, indent=1, sort_keys=True, default=str))


STATE = '''
import maya.cmds as cmds
def state(t):
    if not cmds.objExists(t):
        return {"exists": False}
    shapes = cmds.listRelatives(t, s=True, f=True, ni=True) or []
    sh = shapes[0] if shapes else None
    sgs = sorted(cmds.listSets(object=sh, type=1) or []) if sh else None
    bb = cmds.exactWorldBoundingBox(t)
    return {"exists": True, "shapes": [s.split("|")[-1] for s in shapes],
            "faces": cmds.polyEvaluate(t, f=True), "tris": cmds.polyEvaluate(t, t=True),
            "verts": cmds.polyEvaluate(t, v=True), "shells": cmds.polyEvaluate(t, shell=True),
            "uvs": cmds.polyEvaluate(t, uv=True), "sg": sgs,
            "history": [n for n in (cmds.listHistory(t, pdo=True) or []) if cmds.nodeType(n) != "mesh"],
            "bbox": [round(v, 3) for v in bb], "translate": cmds.xform(t, q=True, ws=True, t=True),
            "rotate": cmds.xform(t, q=True, ws=True, ro=True), "scale": cmds.xform(t, q=True, r=True, s=True),
            "pivot": [round(v, 3) for v in cmds.xform(t, q=True, ws=True, rp=True)], "visible": cmds.getAttr(t + ".visibility"),
            "nonmanifold_edges": len(cmds.polyInfo(t, nonManifoldEdges=True) or []),
            "lamina": len(cmds.polyInfo(t, laminaFaces=True) or [])}
'''


def state(t):
    return py(STATE + "\nstate(%r)" % t, "state")


def fresh():
    ok("new_scene", {"confirm": True})


def run(label, mesh, target, **extra):
    before = state(mesh)
    t0 = time.time()
    res = result_or_error("remesh_retopo", {"mesh": mesh, "target_polycount": target, **extra})
    elapsed = round(time.time() - t0, 2)
    after = state(mesh)
    orig = state(res["original"]) if isinstance(res.get("original"), str) else None
    show(label, {"target": target, "result": res, "before": before, "after": after,
                 "orig_dup": orig, "elapsed_s": elapsed,
                 "scene_meshes": py("import maya.cmds as cmds\nsorted(cmds.ls(type='mesh'))", "meshes")})


ident = py("import os, maya_plugin\n{'file': maya_plugin.__file__}")
print("live plugin:", ident)

show("P0 which commands exist, polyRetopo flags", py('''
import maya.cmds as cmds, maya.mel as mel
have = {n: hasattr(cmds, n) for n in ("polyRetopo", "polyRemesh", "polyReduce")}
flags = None
try:
    flags = mel.eval("help polyRetopo")
except Exception as e:
    flags = "help failed: %s" % e
{"have": have, "plugins": [p for p in (cmds.pluginInfo(q=True, listPlugins=True) or []) if "retopo" in p.lower() or "remesh" in p.lower() or "modeling" in p.lower()],
 "polyRetopo_help": flags}
'''))

fresh()
py("import maya.cmds as cmds\ncmds.polySphere(name='ball', r=1, sx=20, sy=20)\nTrue")
run("P1a sphere 400 faces -> 200", "|ball", 200)
fresh()
py("import maya.cmds as cmds\ncmds.polySphere(name='ball', r=1, sx=20, sy=20)\nTrue")
run("P1b sphere 400 faces -> 800", "|ball", 800)

fresh()
py("import maya.cmds as cmds\ncmds.polyCube(name='box')\nTrue")
run("P2 cube 6 faces -> 400", "|box", 400)

fresh()
py("import maya.cmds as cmds\ncmds.polyPlane(name='slab', w=4, h=4, sx=10, sy=10)\nTrue")
run("P3 open plane 100 faces -> 100 (the minimum)", "|slab", 100)

fresh()
py("import maya.cmds as cmds\ncmds.polyCube(name='a'); cmds.polyCube(name='b'); cmds.xform('b', t=(3, 0, 0))\nTrue")
ok("combine", {"names": ["|a", "|b"], "name": "pair"})
run("P4 two-shell combine 12 faces -> 300", "|pair", 300)

fresh()
py("import maya.cmds as cmds\ncmds.polySphere(name='ball', r=1, sx=20, sy=20)\nTrue")
run("P5 keep_original=False", "|ball", 200, keep_original=False)

fresh()
py("import maya.cmds as cmds\ncmds.polySphere(name='ball', r=1, sx=20, sy=20)\nTrue")
run("P6 sphere 400 -> 2000 (above current)", "|ball", 2000)

fresh()
py("import maya.cmds as cmds\ncmds.polySphere(name='ball', r=1, sx=20, sy=20)\n"
   "cmds.xform('ball', t=(2, 1, -3), ro=(10, 20, 30), s=(1, 2, 1)); cmds.xform('ball', ws=True, rp=(2, 0, -3))\n"
   "sh = cmds.shadingNode('lambert', asShader=True, name='red'); sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name='redSG')\n"
   "cmds.connectAttr(sh + '.outColor', sg + '.surfaceShader'); cmds.sets('ball', e=True, forceElement=sg)\nTrue")
run("P7 transformed, pivoted, shaded sphere -> 200", "|ball", 200)

fresh()
show("P8 raw cmds.polyRetopo on a sphere", py('''
import maya.cmds as cmds, time
cmds.polySphere(name="ball", r=1, sx=20, sy=20)
shapes_before = cmds.listRelatives("ball", s=True, f=True)
t0 = time.time()
out = cmds.polyRetopo("ball", targetFaceCount=200)
el = time.time() - t0
shapes_after = cmds.listRelatives("ball", s=True, f=True)
hist = [n for n in (cmds.listHistory("ball", pdo=True) or []) if cmds.nodeType(n) != "mesh"]
{"returned": out, "elapsed_s": round(el, 2), "shapes_before": shapes_before, "shapes_after": shapes_after,
 "faces": cmds.polyEvaluate("ball", f=True), "tris": cmds.polyEvaluate("ball", t=True), "history": hist,
 "retopo_attrs": {a: cmds.getAttr(hist[0] + "." + a) for a in ("targetFaceCount", "targetFaceCountTolerance", "preserveHardEdges", "topologyRegularity", "faceUniformity", "anisotropy", "preprocessMesh") if hist and cmds.attributeQuery(a, node=hist[0], exists=True)} if hist else None}
'''))

fresh()
print("\nfindings ->", os.path.join(OUT, "findings.json"))
