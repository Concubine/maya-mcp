"""Throwaway probe for redmine #847: which ingredient of an isolate + scene
lighting capture makes the next file-new spin forever?

One VARIANT per process - a hang costs a Maya restart, so this script runs the
variants it is given, in order, and stops at the first one whose new_scene
does not return. Every variant starts from a fresh new_scene and the same lit
plane, then does its thing, then calls the handler's new_scene with a 45 s
timeout and reports ok / hang.

  raw_nopb        isolateSelect on + displayLights all + refresh; restore
                  (lights back first, then isolate off - the handler's order);
                  no playblast
  raw_pb          the same with an offscreen playblast in between (the grab
                  _grab_pixels makes)
  raw_pb_rev      the same playblast, restore in the OPPOSITE order (isolate
                  off first, then lights back)
  raw_pb_lightsonly  playblast under displayLights all WITHOUT isolate
  raw_pb_isoonly  playblast under isolate WITHOUT scene lighting
  handler         the real capture_viewport(isolate, lighting=scene) - the
                  known poison, as a control
  handler_ogs     the real capture, then cmds.ogs(reset=True) before new_scene
  handler_dellight  the real capture, then delete the light before new_scene
  handler_pyfilenew the real capture, then cmds.file(new=True, force=True)
                  from execute_python instead of the handler's new_scene
  handler_open    the real capture, then open_scene of a saved tiny scene

Run:  MAYA_MCP_PORT=9879 MAYA_MCP_EXPECT_PID=<pid> .venv/Scripts/python.exe evals/newscene_spin_probe_847.py raw_nopb,raw_pb

MUTATES THE ANSWERING MAYA'S SCENE. Refuses 9877.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
from live_call import call  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9879"))
if PORT == 9877:
    raise SystemExit("refusing 9877 - that is the user's Maya")
OUT = os.path.join(_HERE, "newscene_spin_probe_847")
os.makedirs(OUT, exist_ok=True)
HANG_S = 45.0

SETUP = '''
import maya.cmds as cmds, math
probe = cmds.directionalLight(name="calibLight", intensity=math.pi)
cmds.xform(cmds.listRelatives(probe, parent=True, fullPath=True)[0], rotation=(-90, 0, 0), worldSpace=True)
plane = cmds.polyPlane(name="calibPlane", width=20, height=20, sx=1, sy=1)[0]
cmds.xform(plane, translation=(120, 20, 0), worldSpace=True)
mat = cmds.shadingNode("standardSurface", asShader=True, name="calibMat")
cmds.setAttr(mat + ".baseColor", 0.5, 0.5, 0.5, type="double3"); cmds.setAttr(mat + ".base", 1.0); cmds.setAttr(mat + ".specular", 0.0)
sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=mat + "SG")
cmds.connectAttr(mat + ".outColor", sg + ".surfaceShader", force=True)
cmds.sets(plane, edit=True, forceElement=sg)
cmds.select(clear=True)
'''

RAW = '''
import maya.cmds as cmds, os, tempfile
ISOLATE = %(isolate)r; LIGHTS = %(lights)r; PLAYBLAST = %(playblast)r; REVERSE = %(reverse)r
EXTRA = %(extra)r   # subset of: camera, undo, cm, flags
p = cmds.getPanel(withFocus=True)
if not p or cmds.getPanel(typeOf=p) != "modelPanel":
    p = [q for q in cmds.getPanel(type="modelPanel") if q in (cmds.getPanel(visiblePanels=True) or [])][0]
lights_before = cmds.modelEditor(p, q=True, displayLights=True)
undo_before = cmds.undoInfo(q=True, stateWithoutFlush=True)
if "undo" in EXTRA:
    cmds.undoInfo(stateWithoutFlush=False)
cam_before = cmds.modelPanel(p, q=True, camera=True)
temp_cam = None
if "camera" in EXTRA:
    temp_cam = cmds.camera(name="mcpTempCam847")[0]
    cmds.lookThru(p, temp_cam)
    cmds.setAttr(temp_cam + ".translate", 120, 200, 0, type="double3")
    cmds.setAttr(temp_cam + ".rotate", -90, 0, 0, type="double3")
    cmds.select("|calibPlane", replace=True)
    cmds.viewFit(temp_cam, fitFactor=0.9)
    cmds.select(clear=True)
flags_before = {}
if "flags" in EXTRA:
    for f in ("displayAppearance", "wireframeOnShaded", "displayTextures", "grid", "lights",
              "cameras", "locators", "manipulators", "textures", "shadows"):
        flags_before[f] = cmds.modelEditor(p, q=True, **{f: True})
    cmds.modelEditor(p, e=True, displayAppearance="smoothShaded", wireframeOnShaded=True,
                     displayTextures=False, grid=False, lights=False, cameras=False,
                     locators=False, manipulators=False, textures=False, shadows=False)
    ssao_before = cmds.getAttr("hardwareRenderingGlobals.ssaoEnable")
    cmds.setAttr("hardwareRenderingGlobals.ssaoEnable", False)
cm_before = None
if "cm" in EXTRA:
    cm_before = (cmds.modelEditor(p, q=True, cmEnabled=True),
                 cmds.colorManagementPrefs(q=True, viewTransformName=True))
    cmds.modelEditor(p, e=True, cmEnabled=True)
    cmds.colorManagementPrefs(e=True, viewTransformName="Un-tone-mapped (sRGB)")
if ISOLATE:
    cmds.isolateSelect(p, state=1)
    cmds.isolateSelect(p, addDagObject="|calibPlane")
if LIGHTS:
    cmds.modelEditor(p, e=True, displayLights="all")
cmds.refresh(force=True)
wrote = None
if PLAYBLAST:
    fd, path = tempfile.mkstemp(suffix=".png", prefix="p847_"); os.close(fd); os.unlink(path)
    cmds.setFocus(p)
    wrote = cmds.playblast(frame=[cmds.currentTime(q=True)], format="image", compression="png",
                           completeFilename=path, offScreen=True, viewer=False, showOrnaments=False,
                           widthHeight=[128, 128], percent=100, quality=100, forceOverwrite=True)
    wrote = bool(wrote) and os.path.exists(path)
def lights_back():
    cmds.modelEditor(p, e=True, displayLights=lights_before)
def isolate_off():
    if ISOLATE:
        cmds.isolateSelect(p, removeDagObject="|calibPlane")
        cmds.isolateSelect(p, state=0)
if REVERSE:
    isolate_off(); lights_back()
else:
    lights_back(); isolate_off()
if "flags" in EXTRA:
    cmds.modelEditor(p, e=True, **flags_before)
    cmds.setAttr("hardwareRenderingGlobals.ssaoEnable", ssao_before)
if cm_before is not None:
    cmds.colorManagementPrefs(e=True, viewTransformName=cm_before[1])
    cmds.modelEditor(p, e=True, cmEnabled=cm_before[0])
if temp_cam is not None:
    cmds.lookThru(p, cam_before)
    cmds.delete(temp_cam)
if "undo" in EXTRA:
    cmds.undoInfo(stateWithoutFlush=undo_before)
r = {"panel": p, "playblast_wrote": wrote,
     "isolate_now": cmds.modelEditor(p, q=True, viewSelected=True),
     "lights_now": cmds.modelEditor(p, q=True, displayLights=True)}
r
'''


def step(label, cmd, params, t=60.0):
    t0 = time.monotonic()
    f = call(cmd, params, timeout_s=t, port=PORT)
    dt = time.monotonic() - t0
    res = f.get("result") or {}
    err = (f.get("error") or {}).get("message", "")
    print("  %-38s %-5s %5.1fs %s" % (label, f.get("status"), dt,
                                      (res.get("result_repr") or err or "")[:160]), flush=True)
    return f


def fresh_scene():
    return step("new_scene (fresh)", "new_scene", {"confirm": True}, HANG_S).get("status") == "ok"


def capture_poison():
    return step("capture isolate+scene", "capture_viewport",
                {"isolate": ["calibPlane"], "angles": ["top"], "lighting": "scene",
                 "resolution": 128}, 120).get("status") == "ok"


def raw(isolate, lights, playblast, reverse=False, extra=()):
    code = RAW % {"isolate": isolate, "lights": lights, "playblast": playblast,
                  "reverse": reverse, "extra": tuple(extra)}
    return step("raw iso=%s lights=%s pb=%s rev=%s +%s" % (isolate, lights, playblast, reverse,
                                                           ",".join(extra) or "-"),
                "execute_python", {"code": code}).get("status") == "ok"


def finish(label="new_scene after"):
    f = step(label, "new_scene", {"confirm": True}, HANG_S)
    return f.get("status") == "ok"


VARIANTS = {
    "raw_nopb": lambda: raw(True, True, False) and finish(),
    "raw_pb": lambda: raw(True, True, True) and finish(),
    "raw_pb_rev": lambda: raw(True, True, True, reverse=True) and finish(),
    "raw_pb_lightsonly": lambda: raw(False, True, True) and finish(),
    "raw_pb_isoonly": lambda: raw(True, False, True) and finish(),
    "raw_pb_camera": lambda: raw(True, True, True, extra=("camera",)) and finish(),
    "raw_pb_undo": lambda: raw(True, True, True, extra=("undo",)) and finish(),
    "raw_pb_cm": lambda: raw(True, True, True, extra=("cm",)) and finish(),
    "raw_pb_flags": lambda: raw(True, True, True, extra=("flags",)) and finish(),
    "raw_pb_all": lambda: raw(True, True, True, extra=("camera", "undo", "cm", "flags")) and finish(),
    "handler": lambda: capture_poison() and finish(),
    "handler_ogs": lambda: capture_poison()
    and step("ogs reset", "execute_python", {"code": "import maya.cmds as cmds\nr = cmds.ogs(reset=True)\nr"}).get("status") == "ok"
    and finish(),
    "handler_dellight": lambda: capture_poison()
    and step("delete light", "execute_python", {"code": "import maya.cmds as cmds\ncmds.delete('calibLight')\nr = cmds.ls(type='light')\nr"}).get("status") == "ok"
    and finish(),
    "handler_pyfilenew": lambda: capture_poison()
    and step("cmds.file(new) via execute_python", "execute_python",
             {"code": "import maya.cmds as cmds\ncmds.file(new=True, force=True)\nr = cmds.file(q=True, sceneName=True)\nr"}, HANG_S).get("status") == "ok",
    "handler_open": lambda: capture_poison()
    and step("open_scene tiny", "open_scene", {"path": TINY, "confirm": True}, HANG_S).get("status") == "ok",
}

TINY = os.path.join(OUT, "tiny.ma").replace("\\", "/")


def main(names):
    results = {}
    if "handler_open" in names and not os.path.exists(TINY):
        step("new_scene for tiny", "new_scene", {"confirm": True}, HANG_S)
        step("save tiny", "save_scene", {"path": TINY})
    for name in names:
        print("\n=== %s ===" % name, flush=True)
        if not fresh_scene():
            results[name] = "NO FRESH SCENE (process already poisoned)"
            break
        step("setup", "execute_python", {"code": SETUP})
        ok = VARIANTS[name]()
        results[name] = "ok" if ok else "HANG"
        print("  -> %s" % results[name], flush=True)
        if not ok:
            break
    with open(os.path.join(OUT, "results_%s.json" % "_".join(names)), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1)
    print("\nRESULTS", json.dumps(results))


if __name__ == "__main__":
    main([n for n in (sys.argv[1] if len(sys.argv) > 1 else "raw_nopb,raw_pb").split(",") if n in VARIANTS])
