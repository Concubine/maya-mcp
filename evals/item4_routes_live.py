"""#822 LIVE GATE: the three value-selected routes the #818 audit found no gate
had ever sent - boolean_op intersection, uv_atlas planar, deform sine - do
what they say, over the wire, against a real Maya.

  1. intersection of two overlapping unit cubes: a 0.5-cube (volume 0.125),
     watertight, a's pivot and material carried.
  2. intersection of two DISJOINT cubes: refused with "do not overlap", both
     operands untouched (nothing consumed, no checkpoint spent).
  3. difference with a inside b (an empty result the boxes cannot foresee):
     refused with "empty", the checkpoint named, no empty mesh left behind.
  4. union of disjoint cubes stays legal: two shells, volume 2.
  5. uv_atlas planar on a sheet facing +X and one facing +Z (both frozen):
     no collapsed faces, no warnings, inside the patch.
  6. planar on a cube: warnings name the 4 collapsed faces; on a sphere: the
     200 mirrored faces.
  7. deform sine amplitude 0.2 on a 2-tall AND a 10-tall cylinder: both move
     0.2 (scene units); wave on the 10-tall cylinder moves < 0.5 (it moved
     0.97 before).
  8. sine with delete_history_after: no deformer, handle or Orig shape left.

No captures. DESTRUCTIVE: calls maya_new_scene. Agent Maya on 9878 only;
refuses 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1. Phase 0 asserts the live
Maya imports THIS working tree.

Run:  MAYA_MCP_PORT=9878 python evals/item4_routes_live.py
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

OUT = os.path.join(_HERE, "item4_routes_live")
os.makedirs(OUT, exist_ok=True)
RESULTS = []


def check(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    print("%-4s %-78s %s" % ("PASS" if ok else "FAIL", label, detail), flush=True)


def raw(command, params, timeout_s=300.0):
    return call(command, params, timeout_s=timeout_s, port=PORT)


def ok(command, params, timeout_s=300.0):
    response = raw(command, params, timeout_s=timeout_s)
    if response.get("status") != "ok":
        raise SystemExit("%s failed: %s" % (command, response.get("error")))
    return response.get("result") or {}


def py(code, what, timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s), what)


def error_text(response):
    return json.dumps(response.get("error") or {})


LIB = '''
import maya.cmds as cmds
import maya.api.OpenMaya as om

def volume(t):
    sh = cmds.listRelatives(t, s=True, f=True, ni=True)[0]
    sel = om.MSelectionList(); sel.add(sh)
    fn = om.MFnMesh(sel.getDagPath(0))
    pts = fn.getPoints(om.MSpace.kWorld)
    _, ids = fn.getTriangles()
    v = 0.0
    for i in range(0, len(ids), 3):
        a, b, c = pts[ids[i]], pts[ids[i+1]], pts[ids[i+2]]
        v += (a.x*(b.y*c.z - b.z*c.y) - a.y*(b.x*c.z - b.z*c.x) + a.z*(b.x*c.y - b.y*c.x)) / 6.0
    return round(v, 5)

def empty_meshes():
    return [m for m in cmds.ls(type="mesh", long=True) if cmds.polyEvaluate(m, v=True) == 0]

def sg_of(t):
    sh = cmds.listRelatives(t, s=True, f=True, ni=True)[0]
    return cmds.listConnections(sh + ".instObjGroups", type="shadingEngine") or []

def uv_face_stats(t):
    sh = cmds.listRelatives(t, s=True, f=True, ni=True)[0]
    sel = om.MSelectionList(); sel.add(sh)
    fn = om.MFnMesh(sel.getDagPath(0))
    zero = 0; pos = 0; neg = 0
    for f in range(fn.numPolygons):
        uvs = [fn.getPolygonUV(f, i) for i in range(fn.polygonVertexCount(f))]
        a = 0.0
        for i in range(len(uvs)):
            u1, v1 = uvs[i]; u2, v2 = uvs[(i + 1) % len(uvs)]
            a += u1 * v2 - u2 * v1
        if abs(a) < 2e-9: zero += 1
        elif a > 0: pos += 1
        else: neg += 1
    return {"faces": fn.numPolygons, "zero": zero, "mirrored": min(pos, neg)}

def cylinder(name, h):
    m = cmds.polyCylinder(name=name, radius=0.2, height=h, subdivisionsY=40, subdivisionsX=12, ch=False)[0]
    cmds.xform(m, ws=True, t=[0, h / 2.0, 0]); cmds.makeIdentity(m, apply=True, t=1, r=1, s=1)
    return cmds.ls(m, long=True)[0]

def sheet(name, ro):
    p = cmds.polyPlane(name=name, w=2, h=2, sx=4, sy=4, ch=False)[0]
    cmds.xform(p, ro=ro); cmds.makeIdentity(p, apply=True, t=1, r=1, s=1)
    return cmds.ls(p, long=True)[0]
'''


def cubes(b_offset, b_scale=1.0):
    ok("new_scene", {"confirm": True})
    py(LIB + "\n1", "lib")
    ok("create_primitive", {"kind": "cube", "name": "a"})
    ok("create_primitive", {"kind": "cube", "name": "b", "translate": b_offset, "scale": [b_scale] * 3})
    ok("assign_material", {"mesh": "|a", "shader": "lambert", "name": "red", "params": {"color": [1, 0, 0]}})


# --------------------------------------------------------------- phase 0
print("=== 0. who answered, and whose code is it ===", flush=True)
ident = py("import os, maya_plugin\n{'file': maya_plugin.__file__, 'cwd': os.getcwd()}", "identity")
loaded = os.path.normcase(os.path.abspath(ident["file"]))
expected = os.path.normcase(os.path.join(REPO, "maya_plugin", "__init__.py"))
if loaded != expected:
    print("WRONG CODE: live Maya imports %s, not %s." % (loaded, expected), file=sys.stderr)
    raise SystemExit(2)
has = py("from maya_plugin.handlers import sculpt, uvmath\nhasattr(sculpt, 'HANDLE_LENGTH_PARAMS') and hasattr(uvmath, 'thinnest_axis')", "loaded")
check("0. the #822 handlers are loaded in the live Maya", has is True)

# --------------------------------------------------------------- phase 1
print("\n=== 1. intersection of overlapping cubes ===", flush=True)
cubes([0.5, 0.5, 0.5])
res = ok("boolean_op", {"a": "|a", "b": "|b", "op": "intersection", "new_name": "cut"})
vol = py("volume('|cut')", "vol")
sg = py("sg_of('|cut')", "sg")
check("1. a 0.5-cube (volume 0.125), watertight, a's pivot and material carried",
      abs(vol - 0.125) < 1e-4 and res["watertight"] and res["pivot"] == [0.0, 0.0, 0.0] and sg == ["redSG"],
      json.dumps({"volume": vol, "tris": res["tris"], "pivot": res["pivot"], "sg": sg}))

# --------------------------------------------------------------- phase 2
print("\n=== 2. intersection of disjoint cubes ===", flush=True)
cubes([3, 0, 0])
r = raw("boolean_op", {"a": "|a", "b": "|b", "op": "intersection", "new_name": "cut"})
after = py("{'a': cmds.objExists('|a'), 'b': cmds.objExists('|b'), 'cut': cmds.objExists('|cut'), 'faces_a': cmds.polyEvaluate('|a', f=True)}", "after")
check("2. refused with 'do not overlap'; both operands untouched, no result made",
      r.get("status") != "ok" and "do not overlap" in error_text(r) and after["a"] and after["b"] and not after["cut"] and after["faces_a"] == 6,
      json.dumps(after) + " " + error_text(r)[:160])

# --------------------------------------------------------------- phase 3
print("\n=== 3. difference with a inside b ===", flush=True)
cubes([0, 0, 0], 3.0)
r = raw("boolean_op", {"a": "|a", "b": "|b", "op": "difference", "new_name": "gone"})
after = py("{'empty': empty_meshes(), 'gone': cmds.objExists('|gone'), 'bool_nodes': cmds.ls(type='polyCBoolOp')}", "after")
err = error_text(r)
check("3. refused with 'empty', the checkpoint named, no empty mesh or boolean node left",
      r.get("status") != "ok" and "empty" in err and "checkpoint" in err.lower() and after["empty"] == [] and not after["gone"] and after["bool_nodes"] == [],
      json.dumps(after) + " " + err[:200])

# --------------------------------------------------------------- phase 4
print("\n=== 4. union of disjoint cubes ===", flush=True)
cubes([3, 0, 0])
res = ok("boolean_op", {"a": "|a", "b": "|b", "op": "union", "new_name": "pair"})
vol = py("volume('|pair')", "vol")
check("4. union of disjoint cubes is a legal two-shell result, volume 2", abs(vol - 2.0) < 1e-4 and res["tris"] == 24,
      json.dumps({"volume": vol, "tris": res["tris"]}))

# --------------------------------------------------------------- phase 5
print("\n=== 5. planar on sheets facing +X and +Z ===", flush=True)
ok("new_scene", {"confirm": True})
py(LIB + "\n1", "lib")
names = py("[sheet('wallX', [0, 0, 90]), sheet('wallZ', [90, 0, 0]), sheet('floor', [0, 0, 0])]", "names")
all_ok, detail = True, []
for name in names:
    res = ok("uv_atlas", {"names": [name], "project": "planar"})
    st = py("uv_face_stats(%r)" % name, "st")
    good = res["warnings"] == [] and st["zero"] == 0 and st["mirrored"] == 0 and res["meshes"][0]["inside_patch"]
    all_ok &= good
    detail.append("%s:%s" % (name.split("|")[-1], "ok" if good else json.dumps({"w": res["warnings"], "st": st})))
check("5. sheets facing X, Z and Y: no collapsed or mirrored faces, no warnings, inside the patch", all_ok, " ".join(detail))

# --------------------------------------------------------------- phase 6
print("\n=== 6. planar on solids says what it did ===", flush=True)
ok("new_scene", {"confirm": True})
py(LIB + "\n1", "lib")
ok("create_primitive", {"kind": "cube", "name": "solid"})
ok("create_primitive", {"kind": "sphere", "name": "ball"})
cube_res = ok("uv_atlas", {"names": ["|solid"], "project": "planar"})
ball_res = ok("uv_atlas", {"names": ["|ball"], "project": "planar"})
check("6a. cube: a warning names 4 of 6 faces with zero UV area",
      any("4 of 6" in w and "zero UV area" in w for w in cube_res["warnings"]), json.dumps(cube_res["warnings"]))
check("6b. sphere: a warning names 200 of 400 mirrored faces",
      any("200 of 400" in w and "mirrored" in w for w in ball_res["warnings"]), json.dumps(ball_res["warnings"]))

# --------------------------------------------------------------- phase 7
print("\n=== 7. sine amplitude is scene units on any mesh ===", flush=True)
moves = {}
for h in (2.0, 10.0):
    ok("new_scene", {"confirm": True})
    py(LIB + "\n1", "lib")
    mesh = py("cylinder('tube', %r)" % h, "mesh")
    res = ok("deform", {"mesh": mesh, "deformer": "sine", "params": {"amplitude": 0.2, "wavelength": 1.0}})
    moves[h] = res["max_displacement"]
check("7a. sine amplitude 0.2 moves a 2-tall AND a 10-tall cylinder by 0.2",
      all(abs(m - 0.2) < 0.02 for m in moves.values()), json.dumps(moves))
ok("new_scene", {"confirm": True})
py(LIB + "\n1", "lib")
mesh = py("cylinder('tube', 10.0)", "mesh")
res = ok("deform", {"mesh": mesh, "deformer": "wave", "params": {"amplitude": 0.2, "wavelength": 1.0}})
check("7b. wave amplitude 0.2 on the 10-tall cylinder moves less than 0.5 (was 0.97)",
      res["max_displacement"] < 0.5, "max_displacement %.4f" % res["max_displacement"])

# --------------------------------------------------------------- phase 8
print("\n=== 8. a baked sine leaves nothing behind ===", flush=True)
ok("new_scene", {"confirm": True})
py(LIB + "\n1", "lib")
mesh = py("cylinder('tube', 2.0)", "mesh")
before = py("set(cmds.ls())\nBEFORE = set(cmds.ls())\nlen(BEFORE)", "n")
res = ok("deform", {"mesh": mesh, "deformer": "sine", "params": {"amplitude": 0.2, "wavelength": 1.0}, "delete_history_after": True})
left = py("sorted(set(cmds.ls()) - BEFORE)", "left")
check("8. baked sine: max_displacement 0.2, no new nodes in the scene",
      abs(res["max_displacement"] - 0.2) < 0.02 and res["baked"] and left == [], json.dumps({"left": left, "moved": res["max_displacement"]}))

# --------------------------------------------------------------- summary
passed = sum(1 for _, r, _ in RESULTS if r)
print("\n%d / %d passed" % (passed, len(RESULTS)))
with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as fh:
    json.dump([{"check": label, "ok": r, "detail": d} for label, r, d in RESULTS], fh, indent=1)
raise SystemExit(0 if passed == len(RESULTS) else 1)
