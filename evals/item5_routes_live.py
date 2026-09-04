"""#823 LIVE GATE: set_camera, group and capture_viewport angle=back do what
they say, over the wire, against a real Maya - the first functional calls to
the first two (the #818 audit found only refusal sweeps reached them).

  1. set_camera at (5,5,5) look_at (1,0.5,-2) focal 50: the camera's forward
     axis against the vector to look_at reads >= 0.99999; focal read back 50;
     the panel looks through it.
  2. set_camera with focal_length 0 and a new position: refused naming
     focal_length, the camera has NOT moved.
  3. PIXELS: red cube at +Z, blue at -Z. set_camera at +Z then capture
     angles=["current"] -> red dominates; at -Z -> blue.
  4. capture front/back: front red, back blue; the back camera sits at z<0
     with yaw 180.
  5. group two cubes at x=2 and x=4: pivot [3,0,0], children paths; rotate the
     group 90 about Y -> a lands at (3,0,1).
  6. group pivot=origin: pivot [0,0,0]; rotate 90 -> a lands at (0,0,-2).
  7. group |p1|part + |p2|part under a taken name: children [part, part1],
     warnings name the rename, the taken name and the emptied parents; both
     children carry a drift-ledger record (transform on them warns nothing).

No captures kept. DESTRUCTIVE: calls maya_new_scene. Agent Maya on 9878 only;
refuses 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1. Phase 0 asserts the live
Maya imports THIS working tree.

Run:  MAYA_MCP_PORT=9878 python evals/item5_routes_live.py
"""
from __future__ import annotations

import base64
import io
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

OUT = os.path.join(_HERE, "item5_routes_live")
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


def dominant(png_b64):
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(io.BytesIO(base64.b64decode(png_b64))).convert("RGB")).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    red = int(((r > 120) & (g < 90) & (b < 90)).sum())
    blue = int(((b > 120) & (r < 90) & (g < 90)).sum())
    return ("red" if red > blue * 1.5 else "blue" if blue > red * 1.5 else "neither"), red, blue


LIB = '''
import maya.cmds as cmds
import maya.api.OpenMaya as om

def aim(cam, look_at):
    m = om.MMatrix(cmds.xform(cam, q=True, ws=True, m=True))
    fwd = om.MVector(-m[8], -m[9], -m[10]).normal()
    pos = om.MVector(*cmds.xform(cam, q=True, ws=True, t=True))
    return round(fwd * ((om.MVector(*look_at) - pos).normal()), 6)

def red_blue():
    r = cmds.polyCube(name="red", ch=False)[0]; cmds.xform(r, ws=True, t=[0, 0, 1.2])
    b = cmds.polyCube(name="blue", ch=False)[0]; cmds.xform(b, ws=True, t=[0, 0, -1.2])
    for name, col in ((r, (1, 0, 0)), (b, (0, 0, 1))):
        sh = cmds.shadingNode("lambert", asShader=True, name=name + "_mat")
        cmds.setAttr(sh + ".color", *col, type="double3")
        sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=sh + "SG")
        cmds.connectAttr(sh + ".outColor", sg + ".surfaceShader")
        cmds.sets(name, e=True, forceElement=sg)
    return 1

def ws(t):
    return [round(v, 4) for v in cmds.xform(t, q=True, ws=True, t=True)]
'''

# --------------------------------------------------------------- phase 0
print("=== 0. who answered, and whose code is it ===", flush=True)
ident = py("import os, maya_plugin\n{'file': maya_plugin.__file__, 'cwd': os.getcwd()}", "identity")
loaded = os.path.normcase(os.path.abspath(ident["file"]))
expected = os.path.normcase(os.path.join(REPO, "maya_plugin", "__init__.py"))
if loaded != expected:
    print("WRONG CODE: live Maya imports %s, not %s." % (loaded, expected), file=sys.stderr)
    raise SystemExit(2)
has = py("from maya_plugin.handlers import modeling, viewport\nhasattr(modeling, 'GROUP_PIVOT_MODES') and hasattr(viewport, 'CAMERA_MIN_FOCAL_MM')", "loaded")
check("0. the #823 handlers are loaded in the live Maya", has is True)

# --------------------------------------------------------------- phase 1-2
print("\n=== 1-2. set_camera aims, and refuses a bad lens before moving ===", flush=True)
ok("new_scene", {"confirm": True})
py(LIB + "\n1", "lib")
res = ok("set_camera", {"position": [5, 5, 5], "look_at": [1, 0.5, -2], "focal_length": 50})
dot = py("aim(%r, [1, 0.5, -2])" % res["name"], "dot")
focal = py("cmds.getAttr(cmds.listRelatives(%r, s=True, f=True)[0] + '.focalLength')" % res["name"], "focal")
panel = py("[cmds.modelPanel(p, q=True, camera=True) for p in cmds.getPanel(type='modelPanel')]", "panel")
check("1. set_camera aims at look_at (forward.dot >= 0.99999), focal 50, the panel looks through it",
      dot >= 0.99999 and abs(focal - 50) < 1e-6 and any(p.endswith("mcpCam") for p in panel),
      json.dumps({"dot": dot, "focal": focal, "panels": panel, "position": res["position"]}))
r = raw("set_camera", {"position": [0, 0, 20], "focal_length": 0})
pos = py("ws(%r)" % res["name"], "pos")
check("2. focal_length 0 with a new position: refused naming focal_length, camera unmoved",
      r.get("status") != "ok" and "focal_length" in json.dumps(r.get("error")) and pos == [5.0, 5.0, 5.0],
      json.dumps({"pos": pos, "error": json.dumps(r.get("error"))[:140]}))

# --------------------------------------------------------------- phase 3
print("\n=== 3. what the camera sees after set_camera ===", flush=True)
ok("new_scene", {"confirm": True})
py(LIB + "\nred_blue()", "scene")
seen = {}
for label, pos in (("+Z", [0, 0, 8]), ("-Z", [0, 0, -8])):
    ok("set_camera", {"position": pos, "look_at": [0, 0, 0]})
    shot = ok("capture_viewport", {"angles": ["current"], "shading": "flatShaded", "resolution": 256})
    seen[label] = dominant(shot["images"][0]["png_b64"])
check("3. set_camera at +Z then capture current shows the red cube; at -Z the blue one",
      seen["+Z"][0] == "red" and seen["-Z"][0] == "blue", json.dumps(seen))

# --------------------------------------------------------------- phase 4
print("\n=== 4. capture front and back ===", flush=True)
shot = ok("capture_viewport", {"angles": ["front", "back"], "shading": "flatShaded", "resolution": 256})
seen = {img["angle"]: dominant(img["png_b64"]) for img in shot["images"]}
back = [c for c in shot["camera_positions"] if c["angle"] == "back"][0]
check("4. front shows red, back shows blue; the back camera sits at z<0 with yaw 180",
      seen["front"][0] == "red" and seen["back"][0] == "blue" and back["position"][2] < 0 and abs(abs(back["rotation"][1]) - 180) < 1e-3,
      json.dumps({"seen": seen, "back": back["position"], "rot": back["rotation"]}))

# --------------------------------------------------------------- phase 5
print("\n=== 5. group: pivot at the bbox centre, rotate orbits it ===", flush=True)
ok("new_scene", {"confirm": True})
py(LIB + "\n1", "lib")
ok("create_primitive", {"kind": "cube", "name": "a", "translate": [2, 0, 0]})
ok("create_primitive", {"kind": "cube", "name": "b", "translate": [4, 0, 0]})
res = ok("group", {"names": ["|a", "|b"], "group_name": "pair"})
ok("transform", {"names": ["|pair"], "rotate": [0, 90, 0]})
a_ws = py("ws('|pair|a')", "a")
check("5. group reports pivot [3,0,0] and children; rotating the group 90 moves a to (3,0,1)",
      res["pivot"] == [3.0, 0.0, 0.0] and res["children"] == ["|pair|a", "|pair|b"] and res["warnings"] == [] and a_ws == [3.0, 0.0, 1.0],
      json.dumps({"pivot": res["pivot"], "children": res["children"], "a_after": a_ws, "warnings": res["warnings"]}))

# --------------------------------------------------------------- phase 6
print("\n=== 6. group pivot=origin ===", flush=True)
ok("new_scene", {"confirm": True})
py(LIB + "\n1", "lib")
ok("create_primitive", {"kind": "cube", "name": "a", "translate": [2, 0, 0]})
ok("create_primitive", {"kind": "cube", "name": "b", "translate": [4, 0, 0]})
res = ok("group", {"names": ["|a", "|b"], "group_name": "root", "pivot": "origin"})
ok("transform", {"names": ["|root"], "rotate": [0, 90, 0]})
a_ws = py("ws('|root|a')", "a")
check("6. pivot=origin reports [0,0,0]; rotating the group 90 moves a to (0,0,-2)",
      res["pivot"] == [0.0, 0.0, 0.0] and a_ws == [0.0, 0.0, -2.0], json.dumps({"pivot": res["pivot"], "a_after": a_ws}))

# --------------------------------------------------------------- phase 7
print("\n=== 7. group says what Maya did quietly ===", flush=True)
ok("new_scene", {"confirm": True})
py(LIB + '''
p1 = cmds.group(empty=True, name="p1"); p2 = cmds.group(empty=True, name="p2")
x = cmds.polyCube(name="part", ch=False)[0]; cmds.parent(x, p1); cmds.xform("|p1|part", ws=True, t=[2, 0, 0])
y = cmds.polyCube(name="part", ch=False)[0]; cmds.parent(y, p2); cmds.xform("|p2|part", ws=True, t=[4, 0, 0])
cmds.polyCube(name="parts", ch=False)
1''', "scene")
res = ok("group", {"names": ["|p1|part", "|p2|part"], "group_name": "parts"})
w = " | ".join(res["warnings"])
tracked = ok("transform", {"names": res["children"], "translate": [0, 1, 0], "relative": True})
check("7a. children [parts_001|part, parts_001|part1]; warnings name the rename, the taken name and both emptied parents",
      res["name"] == "|parts_001" and res["children"] == ["|parts_001|part", "|parts_001|part1"]
      and "part1" in w and "|parts" in w and "|p1" in w and "|p2" in w and "empty" in w,
      json.dumps({"name": res["name"], "children": res["children"], "warnings": res["warnings"]}))
check("7b. both children carry a drift-ledger record: a later transform on them warns nothing",
      tracked["warnings"] == [] and len(tracked["objects"]) == 2, json.dumps(tracked["warnings"]))

# --------------------------------------------------------------- summary
passed = sum(1 for _, r, _ in RESULTS if r)
print("\n%d / %d passed" % (passed, len(RESULTS)))
with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as fh:
    json.dump([{"check": label, "ok": r, "detail": d} for label, r, d in RESULTS], fh, indent=1)
raise SystemExit(0 if passed == len(RESULTS) else 1)
