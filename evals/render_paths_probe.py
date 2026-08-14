"""Probes every route to pixels from an AGENT-LAUNCHED Maya (redmine #584).

RESULT 2026-08-14: cmds.render WORKS headless - 9416 opaque px of 65536.
playblast was the wrong tool, not the environment. M3dView is a dead end
(active3dView is 1x1 with no mapped window). ogsRender is still UNTESTED -
this script passes a bad enableSSAO flag and errors before rendering; fix
that flag to evaluate it as a faster hardware route.

Run against a disposable: MAYA_MCP_PORT=9878 .venv/Scripts/python.exe evals/render_paths_probe.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import call

CODE = r"""
import json as _j, os, tempfile
import maya.cmds as cmds

out = {}
tmp = tempfile.gettempdir()

# a lit, coloured subject so a real render is unmistakable
cmds.file(new=True, force=True)
cmds.polySphere(name="probeBall", radius=3, subdivisionsAxis=24, subdivisionsHeight=24)
mat = cmds.shadingNode("lambert", asShader=True, name="probeMat")
cmds.setAttr(mat + ".color", 0.9, 0.2, 0.1, type="double3")
sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="probeSG")
cmds.connectAttr(mat + ".outColor", sg + ".surfaceShader", force=True)
cmds.sets("probeBall", edit=True, forceElement=sg)
light = cmds.directionalLight(name="probeKey", intensity=2.0)
cmds.xform(cmds.listRelatives(light, parent=True)[0], rotation=[-35, 25, 0])
cam = cmds.camera()[0]
cmds.setAttr(cam + ".translate", 0, 0, 14, type="double3")

out["window_visible"] = cmds.window("MayaWindow", query=True, visible=True)
out["visible_panels"] = cmds.getPanel(visiblePanels=True) or []
out["batch_mode"] = cmds.about(query=True, batch=True)

# ---- route 1: ogsRender (Viewport 2.0 offscreen batch render)
try:
    p = os.path.join(tmp, "probe_ogs")
    r = cmds.ogsRender(camera=cam, width=256, height=256, currentFrame=True,
                       enableSSAO=False)
    out["ogsRender"] = {"ok": True, "returned": str(r)[:200]}
except Exception as exc:
    out["ogsRender"] = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}

# ---- route 2: M3dView.readColorBuffer
try:
    import maya.OpenMayaUI as omui
    view = omui.M3dView.active3dView()
    out["m3dview"] = {"ok": True, "w": view.portWidth(), "h": view.portHeight()}
except Exception as exc:
    out["m3dview"] = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}

# ---- route 3: software render via cmds.render
try:
    cmds.setAttr("defaultRenderGlobals.imageFormat", 32)  # png
    path = cmds.render(cam, x=256, y=256)
    out["cmds_render"] = {"ok": True, "path": str(path),
                          "exists": bool(path) and os.path.exists(str(path)),
                          "bytes": os.path.getsize(path) if path and os.path.exists(str(path)) else 0}
except Exception as exc:
    out["cmds_render"] = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}

# ---- route 4: what renderers are even available
try:
    out["renderers"] = cmds.renderer(query=True, namesOfAvailableRenderers=True)
except Exception as exc:
    out["renderers"] = "ERR %s" % exc

# ---- save the scene so a batch Render.exe run can be tried from outside
scene = os.path.join(tmp, "probe_scene.ma")
cmds.file(rename=scene)
cmds.file(save=True, type="mayaAscii", force=True)
out["scene_saved"] = scene
out["camera"] = cam

print(_j.dumps(out, indent=1))
"""

resp = call("execute_python", {"code": CODE}, 180.0)
if resp.get("status") != "ok":
    print(json.dumps(resp, indent=2)); sys.exit(1)
print(resp["result"]["stdout"])
if resp["result"].get("stderr"):
    print("STDERR:", resp["result"]["stderr"][:800])
if resp["result"].get("traceback"):
    print(resp["result"]["traceback"])
