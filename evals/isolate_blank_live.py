"""Live gate for #825: a blank ISOLATE frame says WHICH of its two causes
it was, measured against a real Maya.

#825 itself - every isolate capture in a process coming back transparent
while non-isolate captures in that same process draw - did not reproduce in
five agent Maya processes on 2026-09-04, so it is not what this gate can
check. What it checks is the handling that makes that condition legible when
it does happen, and that handling is reachable on demand: any blank isolate
frame now gets a control shot with view-selected switched off, and the
warning reports the answer instead of listing the possibilities.

Three states, all reachable live:

  A  isolate a HIDDEN object while the scene still has a visible one
     -> isolate frame blank, control draws  -> "the isolated view drew nothing"
  B  isolate the only object in the scene and hide it
     -> both blank                          -> "there was nothing to draw"
  C  an ordinary isolate of a visible object
     -> not blank at all, no note, and the isolate STILL WORKS afterwards
        (the control shot toggles view-selected off and back on, so this is
        the regression check that it restores what it borrowed)

Run:  MAYA_MCP_PORT=9879 python evals/isolate_blank_live.py
"""
import base64
import io
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, _HERE)

from live_call import call  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877:
    raise SystemExit("refusing the user's Maya")

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))
    print("%s %s%s" % ("PASS" if ok else "FAIL", label,
                       (" - " + str(detail)) if detail else ""))


def ok(command, params, timeout_s=300.0):
    r = call(command, params, timeout_s=timeout_s, port=PORT)
    if r.get("status") != "ok":
        raise SystemExit("%s failed: %s" % (command, json.dumps(r.get("error"), indent=1)))
    return r.get("result") or {}


def py(code):
    res = ok("execute_python", {"code": code})
    if res.get("traceback"):
        raise SystemExit("execute_python raised:\n" + res["traceback"])
    return res


def pixels(png_b64):
    """Opaque count, plus how much RED and BLUE is in the frame.

    Opaque count alone cannot tell whether isolate is still isolating: a
    non-isolate frame fits BOTH cubes, so each is drawn smaller and the two
    together can cover fewer pixels than one cube filling the frame does
    (measured: whole 11608 vs isolated 15372). Colour answers the question
    that pixel count cannot - "is the other object in this frame at all".
    """
    from PIL import Image
    img = Image.open(io.BytesIO(base64.b64decode(png_b64))).convert("RGBA")
    px = [p for p in img.getdata() if p[3] > 0]
    return {"opaque": len(px),
            "red": sum(1 for p in px if p[0] > 110 and p[0] > p[2] + 40),
            "blue": sum(1 for p in px if p[2] > 110 and p[2] > p[0] + 40)}


def shoot(isolate=None):
    params = {"angles": ["front"], "resolution": 256, "shading": "flatShaded"}
    if isolate:
        params["isolate"] = isolate
    res = ok("capture_viewport", params)
    img = res["images"][0]
    out = pixels(img["png_b64"])
    out["blank"] = img.get("blank")
    out["warnings"] = res.get("warnings") or []
    return out


SCENE = r'''
import maya.cmds as cmds
cmds.file(new=True, force=True)

def colour(t, col, name):
    sh = cmds.shadingNode("lambert", asShader=True, name=name + "_mat")
    cmds.setAttr(sh + ".color", *col, type="double3")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=sh + "SG")
    cmds.connectAttr(sh + ".outColor", sg + ".surfaceShader")
    cmds.sets(t, e=True, forceElement=sg)

a = cmds.polyCube(name="red", w=2, h=2, d=2, ch=False)[0]
b = cmds.polyCube(name="blue", w=2, h=2, d=2, ch=False)[0]
cmds.xform(b, ws=True, t=[4, 0, 0])
colour(a, (1, 0, 0), "red")
colour(b, (0, 0, 1), "blue")
r = 1
'''


def main():
    print("### isolate blank gate (#825) on port %s" % PORT)

    # --- A: isolated object hidden, another object still visible ---------
    py(SCENE)
    py("import maya.cmds as cmds\ncmds.setAttr('red.visibility', 0)\nr = 1")
    a = shoot(isolate=["|red"])
    note = " ".join(a["warnings"])
    check("A1. isolating a hidden object gives a blank frame",
          a["blank"] is True, "opaque %d" % a["opaque"])
    check("A2. ...and the warning says the ISOLATED VIEW drew nothing, "
          "not that the scene may be empty",
          "isolated view" in note and "may be empty" not in note, note[:120])
    check("A3. ...and it names #825 as one of the two causes",
          "825" in note)
    check("A4. ...and it does NOT claim the scene is empty, because it is not",
          "there was nothing to draw" not in note)

    # --- B: the only object in the scene, hidden -------------------------
    py("import maya.cmds as cmds\ncmds.delete('blue')\nr = 1")
    b = shoot(isolate=["|red"])
    bnote = " ".join(b["warnings"])
    check("B1. an isolate of the only object, hidden, is blank",
          b["blank"] is True, "opaque %d" % b["opaque"])
    check("B2. ...and the warning says there was NOTHING TO DRAW",
          "nothing to draw" in bnote, bnote[:120])
    check("B3. ...and it does not blame the isolated view or cite #825",
          "825" not in bnote and "isolated view" not in bnote)

    # --- C: the ordinary case still works, and isolate survives ----------
    py(SCENE)
    c = shoot(isolate=["|red"])
    cnote = " ".join(c["warnings"])
    check("C1. an ordinary isolate of a visible object draws",
          c["blank"] is False and c["opaque"] > 1000, "opaque %d" % c["opaque"])
    check("C2. ...and says nothing about blankness",
          "BLANK" not in cnote and "825" not in cnote, cnote[:120])

    # The control shot toggles view-selected off and back on. Prove it put
    # it back: a second isolate must still exclude the other cube.
    c2 = shoot(isolate=["|red"])
    check("C3. a second isolate still isolates: red drawn, and NO blue in "
          "the frame (the control shot restored view-selected)",
          c2["blank"] is False and c2["red"] > 1000 and c2["blue"] == 0,
          "red %d blue %d" % (c2["red"], c2["blue"]))
    whole = shoot()
    check("C4. ...while a non-isolate frame of the same scene DOES show "
          "blue, so the isolate above really was excluding it",
          whole["blue"] > 500 and whole["red"] > 500,
          "red %d blue %d" % (whole["red"], whole["blue"]))

    failed = [c for c in CHECKS if not c[1]]
    print("\n%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
