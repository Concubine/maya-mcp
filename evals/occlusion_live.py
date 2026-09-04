"""#824 LIVE GATE: capture_viewport says when the target it framed is hidden
behind another mesh - over the wire, against a real Maya, with the pixels as
the referee (the red/blue dominance method from #823).

  1. K2 (#823): red cube at +Z, blue at -Z, back + target=|red -> the frame
     is all blue and the warning says |red is hidden behind blue, all 9.
  2. front + target=|red -> red pixels, no occlusion warning.
  3. blue shifted x=0.5: partly hidden, N of 9, red pixels roughly halved.
  4. a cube on a floor plane, three_quarter + target -> no warning: the
     corner rays graze the floor exactly at the corners (tolerance).
  5. target = a group of two cubes with a wall in front: front hidden, back
     not; the group's own members are never the occluder.
  6. isolate=[red] + target=|red from the back: red pixels, no warning -
     the hidden blue cannot occlude.
  7. blue hidden (visibility off): no warning.
  8. a SKINNED cube in front of the target: named once, as "skinned", never
     its ShapeOrig.
  9. capture_turntable with target still works and carries no occlusion note.

No captures kept. DESTRUCTIVE: calls maya_new_scene. Agent Maya on 9878 only;
refuses 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1. Phase 0 asserts the live
Maya imports THIS working tree and has the #824 handler.

Run:  MAYA_MCP_PORT=9878 python evals/occlusion_live.py
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

OUT = os.path.join(_HERE, "occlusion_live")
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


def pixels(png_b64):
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(io.BytesIO(base64.b64decode(png_b64))).convert("RGB")).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    red = int(((r > 120) & (g < 90) & (b < 90)).sum())
    blue = int(((b > 120) & (r < 90) & (g < 90)).sum())
    return red, blue


def shoot(params):
    res = ok("capture_viewport", dict(params, resolution=256, shading="flatShaded"))
    red, blue = pixels(res["images"][0]["png_b64"])
    hidden = [w for w in res["warnings"] if "hidden" in w]
    # `blank` is carried so a #765-class empty frame (measured once on
    # 2026-09-04: every ISOLATE view of one agent Maya process drew nothing
    # while its main window stayed hidden; the next process was fine) reads
    # as what it is, not as an occlusion defect.
    return {"red": red, "blue": blue, "hidden": hidden, "warnings": res["warnings"],
            "blank": res["images"][0].get("blank")}


LIB = '''
import maya.cmds as cmds

def colour(t, col, name):
    sh = cmds.shadingNode("lambert", asShader=True, name=name + "_mat")
    cmds.setAttr(sh + ".color", *col, type="double3")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=sh + "SG")
    cmds.connectAttr(sh + ".outColor", sg + ".surfaceShader")
    cmds.sets(t, e=True, forceElement=sg)

def red_blue(blue_x=0.0):
    r = cmds.polyCube(name="red", ch=False)[0]; cmds.xform(r, ws=True, t=[0, 0, 1.2])
    b = cmds.polyCube(name="blue", ch=False)[0]; cmds.xform(b, ws=True, t=[blue_x, 0, -1.2])
    colour(r, (1, 0, 0), "red"); colour(b, (0, 0, 1), "blue")
    return 1
'''

# --------------------------------------------------------------- phase 0
print("=== 0. who answered, and whose code is it ===", flush=True)
ident = py("import os, maya_plugin\n{'file': maya_plugin.__file__, 'cwd': os.getcwd()}", "identity")
loaded = os.path.normcase(os.path.abspath(ident["file"]))
expected = os.path.normcase(os.path.join(REPO, "maya_plugin", "__init__.py"))
if loaded != expected:
    print("WRONG CODE: live Maya imports %s, not %s." % (loaded, expected), file=sys.stderr)
    raise SystemExit(2)
has = py("from maya_plugin.handlers import capture\nhasattr(capture, 'target_occlusion')", "loaded")
check("0. the #824 capture handler is loaded in the live Maya", has is True)

# --------------------------------------------------------------- phase 1-2
print("\n=== 1-2. the K2 scene: back is hidden, front is not ===", flush=True)
ok("new_scene", {"confirm": True})
py(LIB + "\nred_blue()", "scene")
back = shoot({"angles": ["back"], "target": ["|red"]})
check("1a. back + target=|red draws no red pixel", back["red"] == 0 and back["blue"] > 60000,
      "red %d blue %d" % (back["red"], back["blue"]))
check("1b. ...and the warning says |red is hidden behind blue, all 9 samples",
      len(back["hidden"]) == 1 and "|red" in back["hidden"][0] and "blue" in back["hidden"][0]
      and "all 9" in back["hidden"][0] and "isolate" in back["hidden"][0] and back["hidden"][0].startswith("back:"),
      json.dumps(back["hidden"]))
front = shoot({"angles": ["front"], "target": ["|red"]})
check("2. front + target=|red draws red and warns nothing about hiding",
      front["red"] > 10000 and front["hidden"] == [], "red %d hidden %s" % (front["red"], front["hidden"]))

# --------------------------------------------------------------- phase 3
print("\n=== 3. half cover is partly hidden ===", flush=True)
ok("new_scene", {"confirm": True})
py(LIB + "\nred_blue(blue_x=0.5)", "scene")
half = shoot({"angles": ["back"], "target": ["|red"]})
check("3. blue at x=0.5: 'partly hidden', N of 9, red pixels between 25%% and 75%% of the clear view (%d)" % front["red"],
      len(half["hidden"]) == 1 and "partly" in half["hidden"][0] and "of 9" in half["hidden"][0]
      and 0.25 * front["red"] < half["red"] < 0.75 * front["red"],
      "red %d %s" % (half["red"], json.dumps(half["hidden"])))

# --------------------------------------------------------------- phase 4
print("\n=== 4. a floor the target stands on is not an occluder ===", flush=True)
ok("new_scene", {"confirm": True})
py(LIB + '''
c = cmds.polyCube(name="red", ch=False)[0]; colour(c, (1, 0, 0), "red")
f = cmds.polyPlane(name="floor", w=10, h=10, sx=1, sy=1, ch=False)[0]
cmds.xform(f, ws=True, t=[0, -0.5, 0]); colour(f, (0, 0, 1), "floor")
1''', "scene")
floor = {a: shoot({"angles": [a], "target": ["|red"]}) for a in ("three_quarter", "front", "top")}
check("4. three_quarter / front / top on a cube standing on a plane: red drawn, no hiding warning",
      all(v["red"] > 5000 and v["hidden"] == [] for v in floor.values()),
      json.dumps({a: {"red": v["red"], "hidden": v["hidden"]} for a, v in floor.items()}))

# --------------------------------------------------------------- phase 5
print("\n=== 5. a grouped target behind a wall ===", flush=True)
ok("new_scene", {"confirm": True})
py(LIB + '''
a = cmds.polyCube(name="a", ch=False)[0]; cmds.xform(a, ws=True, t=[-1, 0, 0]); colour(a, (1, 0, 0), "ra")
b = cmds.polyCube(name="b", ch=False)[0]; cmds.xform(b, ws=True, t=[1, 0, 0]); colour(b, (1, 0, 0), "rb")
cmds.group(a, b, name="pair")
w = cmds.polyCube(name="wall", w=4, h=2, d=0.2, ch=False)[0]; cmds.xform(w, ws=True, t=[0, 0, 2]); colour(w, (0, 0, 1), "wall")
1''', "scene")
g_front = shoot({"angles": ["front"], "target": ["|pair"]})
g_back = shoot({"angles": ["back"], "target": ["|pair"]})
check("5a. front + target=|pair: no red, hidden behind wall (all 9)",
      g_front["red"] == 0 and len(g_front["hidden"]) == 1 and "wall" in g_front["hidden"][0] and "all 9" in g_front["hidden"][0],
      "red %d %s" % (g_front["red"], json.dumps(g_front["hidden"])))
check("5b. back + target=|pair: red drawn, no warning - the group's own members are not occluders",
      g_back["red"] > 5000 and g_back["hidden"] == [], "red %d %s" % (g_back["red"], json.dumps(g_back["hidden"])))

# --------------------------------------------------------------- phase 6-7
print("\n=== 6-7. what is not drawn cannot hide the target ===", flush=True)
ok("new_scene", {"confirm": True})
py(LIB + "\nred_blue()", "scene")
iso = shoot({"angles": ["back"], "target": ["|red"], "isolate": ["|red"]})
check("6a. isolate=[|red] + target=|red from the back: no hiding warning (blue is not drawn)",
      iso["hidden"] == [], json.dumps(iso["hidden"]))
# The PIXELS of an isolate capture are a separate, pre-existing question:
# measured 2026-09-04, two of three agent-launched Maya processes drew 0
# opaque px for EVERY isolate view (a hand-rolled isolate + playblast too,
# and with the #824 code monkeypatched out) while non-isolate captures drew
# 65536; the third process drew 14884 red for this very call (probe part 2,
# I_isolate). The blank guard names it. Tracked as redmine #825; here it is
# reported, and only a NON-blank frame that lacks red fails.
check("6b. ...and when the isolate view draws at all, it draws red (a BLANK frame is #825, not this)",
      iso["blank"] is True or iso["red"] > 10000,
      "red %d blank %s" % (iso["red"], iso["blank"]))
py("cmds.setAttr('|blue.visibility', False)\n1", "hide")
hid = shoot({"angles": ["back"], "target": ["|red"]})
check("7. blue hidden: red drawn, no warning", hid["red"] > 10000 and hid["hidden"] == [],
      "red %d %s" % (hid["red"], json.dumps(hid["hidden"])))

# --------------------------------------------------------------- phase 8
print("\n=== 8. a skinned occluder is named once, by its transform ===", flush=True)
ok("new_scene", {"confirm": True})
py(LIB + '''
r = cmds.polyCube(name="red", ch=False)[0]; cmds.xform(r, ws=True, t=[0, 0, -1.2]); colour(r, (1, 0, 0), "red")
s = cmds.polyCube(name="skinned", ch=False)[0]; cmds.xform(s, ws=True, t=[0, 0, 1.2]); colour(s, (0, 0, 1), "skinned")
j = cmds.joint(p=(0, 0, 1.2)); cmds.skinCluster(j, s)
1''', "scene")
sk = shoot({"angles": ["front"], "target": ["|red"]})
check("8. front + target=|red behind a skinned cube: hidden behind 'skinned' (not its Orig), all 9",
      len(sk["hidden"]) == 1 and "behind skinned from" in sk["hidden"][0] and "Orig" not in sk["hidden"][0]
      and "all 9" in sk["hidden"][0] and sk["red"] == 0,
      "red %d %s" % (sk["red"], json.dumps(sk["hidden"])))

# --------------------------------------------------------------- phase 9
print("\n=== 9. the turntable is untouched ===", flush=True)
ok("new_scene", {"confirm": True})
py(LIB + "\nred_blue()", "scene")
tt = ok("capture_turntable", {"target": "|red", "n_frames": 4, "resolution": 128})
check("9. capture_turntable target=|red: 4 frames, no hiding note",
      tt["n_frames"] == 4 and len(tt["images"]) == 4 and not [w for w in tt["warnings"] if "hidden" in w],
      json.dumps(tt["warnings"]))

# --------------------------------------------------------------- summary
passed = sum(1 for _, r, _ in RESULTS if r)
print("\n%d / %d passed" % (passed, len(RESULTS)))
with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as fh:
    json.dump([{"check": label, "ok": r, "detail": d} for label, r, d in RESULTS], fh, indent=1)
raise SystemExit(0 if passed == len(RESULTS) else 1)
