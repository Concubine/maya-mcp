"""#815 PROBE: does capture_viewport's shadows=True ever draw a shadow, and if
not, whose fault is it - the tool's capture path, VP2, or the scene?

  T0. which renderer the capture panel runs (legacy OpenGL draws no VP2 shadow)
  T1. tool capture, top view, 512px, high-contrast scene: shadows off vs on
  T2. the same, three_quarter
  T3. a PLAIN playblast of the same panel state (bypassing the tool) off/on
  T4. a spotLight instead of the directional light, tool capture
  T5. a pointLight, tool capture
  T6. the tool's own path with shadows=True: what the modelEditor reports
      DURING the capture (patched _grab_pixels records the panel state)

TAKES CAPTURES - each one shows the agent Maya's window (#765). Agent Maya on
9878 only.  Run:  MAYA_MCP_PORT=9878 python evals/shadows_probe_815.py
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import textwrap

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, _HERE)

from PIL import Image  # noqa: E402

from live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877:
    raise SystemExit("refusing the user's Maya")
OUT = os.path.join(_HERE, "shadows_probe_815")
os.makedirs(OUT, exist_ok=True)
FINDINGS = {}


def ok(command, params, timeout_s=300.0):
    r = call(command, params, timeout_s=timeout_s, port=PORT)
    if r.get("status") != "ok":
        raise SystemExit("%s failed: %s" % (command, json.dumps(r.get("error"), indent=1)))
    return r.get("result") or {}


def py(code, what="r"):
    return structured_result(ok("execute_python", {"code": textwrap.dedent(code).strip()}), what)


def show(label, value):
    FINDINGS[label] = value
    with open(os.path.join(OUT, "findings.json"), "w", encoding="utf-8") as fh:
        json.dump(FINDINGS, fh, indent=1, default=str)
    print("\n--- %s ---" % label)
    print(json.dumps(value, indent=1, sort_keys=True, default=str))


def stats(png):
    img = Image.open(io.BytesIO(png)).convert("RGB")
    px = list(img.getdata())
    lum = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in px]
    mean = sum(lum) / len(lum)
    return {"mean": round(mean, 2), "min": round(min(lum), 1), "max": round(max(lum), 1), "size": img.size}


def diff(p1, p2):
    a = list(Image.open(io.BytesIO(p1)).convert("RGB").getdata())
    b = list(Image.open(io.BytesIO(p2)).convert("RGB").getdata())
    n = sum(1 for x, y in zip(a, b) if max(abs(x[i] - y[i]) for i in range(3)) > 8)
    return {"changed_pixels": n, "of": len(a), "pct": round(100.0 * n / len(a), 2)}


def cap(name, **kw):
    params = {"angles": ["top"], "resolution": 512, "lighting": "scene", "shading": "smoothShaded"}
    params.update(kw)
    res = ok("capture_viewport", params)
    png = base64.b64decode(res["images"][0]["png_b64"])
    open(os.path.join(OUT, name + ".png"), "wb").write(png)
    return png, res.get("warnings") or []


def ab(label, **kw):
    off, _ = cap(label + "_off", shadows=False, **kw)
    on, w = cap(label + "_on", shadows=True, **kw)
    show(label, {"off": stats(off), "on": stats(on), "diff": diff(off, on),
                 "warnings_on": [x for x in w if "window" not in x]})


SCENE = '''
import maya.cmds as cmds
cmds.file(new=True, force=True)
cmds.polyPlane(name="ground", w=10, h=10, sx=1, sy=1)
cmds.polyCube(name="post", w=1, h=3, d=1); cmds.xform("post", t=(0, 1.5, 0))
sh = cmds.shadingNode("lambert", asShader=True, name="grey"); cmds.setAttr(sh + ".color", 0.8, 0.8, 0.8, type="double3")
sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="greySG")
cmds.connectAttr(sh + ".outColor", sg + ".surfaceShader"); cmds.sets("ground", "post", e=True, forceElement=sg)
'''


def scene(light):
    body = {
        "directional": '''
l = cmds.directionalLight(name="sun", intensity=1.5); t = cmds.listRelatives(l, p=True)[0]
cmds.xform(t, ro=(-60, 30, 0), t=(0, 5, 0))''',
        "spot": '''
l = cmds.spotLight(name="spot", intensity=3.0, coneAngle=90); t = cmds.listRelatives(l, p=True)[0]
cmds.xform(t, t=(4, 8, 4)); cmds.setAttr(l + ".decayRate", 0)
import maya.cmds as _c; _c.aimConstraint("post", t, aimVector=(0, 0, -1))''',
        "point": '''
l = cmds.pointLight(name="pt", intensity=3.0); t = cmds.listRelatives(l, p=True)[0]
cmds.xform(t, t=(4, 8, 4)); cmds.setAttr(l + ".decayRate", 0)''',
    }[light]
    py(SCENE + body + '''
cmds.setAttr(l + ".useDepthMapShadows", 1); cmds.setAttr(l + ".dmapResolution", 2048)
cmds.setAttr(l + ".shadowColor", 0, 0, 0, type="double3")
{"light": l, "dmap": cmds.getAttr(l + ".useDepthMapShadows")}
''')


ident = py("import os, maya_plugin\n{'file': maya_plugin.__file__}")
print("live plugin:", ident)

# T0 --------------------------------------------------------------------
show("T0 renderer of every model panel", py('''
import maya.cmds as cmds
{p: {"renderer": cmds.modelEditor(p, q=True, rendererName=True),
     "shadows": cmds.modelEditor(p, q=True, shadows=True),
     "displayLights": cmds.modelEditor(p, q=True, displayLights=True)}
 for p in cmds.getPanel(type="modelPanel")}
'''))

# T1 / T2 -----------------------------------------------------------------
scene("directional")
ab("T1 directional, top, 512")
ab("T2 directional, three_quarter, 512", angles=["three_quarter"])

# T3: a plain playblast of the same panel, bypassing the tool -----------------
raw = py('''
import maya.cmds as cmds, os, base64
panel = [p for p in cmds.getPanel(type="modelPanel")][-1]
cam = cmds.camera(name="probeTop")[0]; cmds.xform(cam, t=(0, 20, 0), ro=(-90, 0, 0))
cmds.select("ground", "post"); cmds.viewFit(cam, fitFactor=0.85); cmds.select(clear=True)
cmds.lookThru(panel, cam)
out = {}
for flag in (False, True):
    cmds.modelEditor(panel, e=True, displayAppearance="smoothShaded", displayLights="all", shadows=flag,
                     grid=False, lights=False, cameras=False, locators=False)
    cmds.refresh(force=True)
    path = os.path.join(%r, "T3_plain_%%s" %% ("on" if flag else "off")).replace("\\\\", "/")
    cmds.playblast(frame=[1], format="image", compression="png", completeFilename=path + ".png",
                   viewer=False, offScreen=True, widthHeight=(512, 512), percent=100, forceOverwrite=True,
                   showOrnaments=False, editorPanelName=panel)
    out["on" if flag else "off"] = {"shadows_readback": cmds.modelEditor(panel, q=True, shadows=True),
                                   "renderer": cmds.modelEditor(panel, q=True, rendererName=True), "path": path + ".png"}
out
''' % OUT.replace("\\", "/"))
show("T3 plain playblast panel state", raw)
p_off = open(raw["off"]["path"], "rb").read()
p_on = open(raw["on"]["path"], "rb").read()
show("T3 plain playblast off vs on", {"off": stats(p_off), "on": stats(p_on), "diff": diff(p_off, p_on)})

# T6: what the tool's panel reports DURING its own capture ----------------------
show("T6 panel state inside the tool's capture (shadows=True)", py('''
import maya.cmds as cmds
from maya_plugin.handlers import capture
seen = {}
_real = capture._grab_pixels
def spy(cmds_, panel, resolution):
    seen["renderer"] = cmds.modelEditor(panel, q=True, rendererName=True)
    seen["shadows"] = cmds.modelEditor(panel, q=True, shadows=True)
    seen["displayLights"] = cmds.modelEditor(panel, q=True, displayLights=True)
    seen["appearance"] = cmds.modelEditor(panel, q=True, displayAppearance=True)
    seen["panel"] = panel
    return _real(cmds_, panel, resolution)
capture._grab_pixels = spy
try:
    capture.capture_viewport({"angles": ["top"], "resolution": 256, "lighting": "scene",
                              "shading": "smoothShaded", "shadows": True})
finally:
    capture._grab_pixels = _real
seen
'''))

# T4 / T5 -----------------------------------------------------------------
scene("spot")
ab("T4 spotLight, top, 512")
scene("point")
ab("T5 pointLight, top, 512")

ok("new_scene", {"confirm": True})
print("\nfindings ->", os.path.join(OUT, "findings.json"))
