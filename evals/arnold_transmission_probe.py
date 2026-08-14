"""Proves a real renderer shows tinted/refracting transmission where VP2 cannot
(redmine #584, following #583's transmission support).

RESULT 2026-08-14, headless on an agent-launched Maya: two identical octahedra
differing only in transmission render structurally differently under Arnold -
the transmissive one refracts the backdrop with a ruby band. VP2 draws both as
near-identical grey. See arnold_transmission_probe.png.

TRAP: cmds.render writes to a FIXED path in the project images dir and
overwrites it every call - both renders here landed on the same untitled.png.
Any wrapper must move or rename each result.

Run against a disposable: MAYA_MCP_PORT=9878 .venv/Scripts/python.exe evals/arnold_transmission_probe.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import call

CODE = r"""
import json as _j, os
import maya.cmds as cmds

out = {}
cmds.file(new=True, force=True)

# backdrop so refraction has something to bend
cmds.polyPlane(name="bg", width=40, height=40, subdivisionsX=1, subdivisionsY=1)
cmds.xform("bg", translation=[0, -3, 0])
bgm = cmds.shadingNode("lambert", asShader=True, name="bgm")
cmds.setAttr(bgm + ".color", 0.55, 0.55, 0.6, type="double3")
bgsg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="bgsg")
cmds.connectAttr(bgm + ".outColor", bgsg + ".surfaceShader", force=True)
cmds.sets("bg", edit=True, forceElement=bgsg)

def gem(name, x, transmission):
    cmds.polyPlatonicSolid(name=name, radius=2.0, solidType=2)  # octahedron
    cmds.xform(name, translation=[x, 0, 0], rotation=[0, 20, 0])
    sh = cmds.shadingNode("standardSurface", asShader=True, name=name + "_m")
    cmds.setAttr(sh + ".baseColor", 0.72, 0.05, 0.14, type="double3")
    cmds.setAttr(sh + ".specularRoughness", 0.02)
    if transmission:
        cmds.setAttr(sh + ".transmission", 1.0)
        cmds.setAttr(sh + ".transmissionColor", 0.72, 0.05, 0.14, type="double3")
        cmds.setAttr(sh + ".specularIOR", 2.42)
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=name + "_sg")
    cmds.connectAttr(sh + ".outColor", sg + ".surfaceShader", force=True)
    cmds.sets(name, edit=True, forceElement=sg)

gem("gemOpaque", -3.0, False)
gem("gemGlass",   3.0, True)

key = cmds.directionalLight(name="key", intensity=3.0)
cmds.xform(cmds.listRelatives(key, parent=True)[0], rotation=[-40, 25, 0])
cam = cmds.camera()[0]
cmds.setAttr(cam + ".translate", 0, 1.5, 17, type="double3")
cmds.setAttr(cam + ".rotateX", -4)

results = {}
for renderer in ("mayaHardware2", "arnold"):
    try:
        cmds.setAttr("defaultRenderGlobals.currentRenderer", renderer, type="string")
        cmds.setAttr("defaultRenderGlobals.imageFormat", 32)
        path = cmds.render(cam, x=420, y=280)
        results[renderer] = {"path": str(path),
                             "exists": bool(path) and os.path.exists(str(path))}
    except Exception as exc:
        results[renderer] = {"error": "%s: %s" % (type(exc).__name__, exc)}
out["renders"] = results
print(_j.dumps(out, indent=1))
"""

resp = call("execute_python", {"code": CODE}, 600.0)
if resp.get("status") != "ok":
    print(json.dumps(resp, indent=2)); sys.exit(1)
print(resp["result"]["stdout"])
if resp["result"].get("traceback"):
    print(resp["result"]["traceback"])
