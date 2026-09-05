"""Live gate for redmine #847: after a capture that isolates under scene
lighting, the scene-lifecycle handlers still return.

MEASURED on Maya 2027: on a fresh process, capture_viewport(isolate=[...],
lighting='scene') returns fine, and the next new_scene never does - Maya's
file-new spins one core forever inside its own undo flush. The queue then
holds nothing but Maya's own entries (identical to a healthy capture's), and
emptying it first lets file-new return in 0.1 s - but ONLY when the flush is
issued as its own request; the same flush inside the handler, in every order
tried, still spins. So the dispatcher gives the scene-replacing handlers a
separate main-thread hop for the flush before they run. This proves it
against a real Maya, where a hang shows up as a timeout on a process that
then has to be killed.

  1  first capture of the process, isolate + scene lighting, then new_scene
     returns within HANG_S  (LANDED: the dispatcher's flush hop, measured 0.1 s)
  2  the same capture, save_scene, the capture again, then open_scene returns
  3  the same capture again, then restore_checkpoint returns

Claims 2 and 3 are OPEN on #847 and run only with MCP847_ALL=1: measured
2026-09-05, claim 2 still spins - a save_scene issued while the residue is
present, then another capture, then open_scene. Whether the save, the second
capture, or file-open itself is the ingredient is the next one-variable
experiment; a process this spins on must be killed.

DESTRUCTIVE: replaces the open scene three times. Defaults to port 9878 and
refuses 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1. RUN IT ON A FRESH MAYA:
the poison is per process and a process this gate hangs must be killed.

Run:  .venv/Scripts/python.exe evals/newscene_after_capture_live.py
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import DEFAULT_PORT, call  # noqa: E402

PORT = DEFAULT_PORT
HANG_S = 30.0

SETUP = """
import maya.cmds as cmds, math
probe = cmds.directionalLight(name="calibLight", intensity=math.pi)
cmds.xform(cmds.listRelatives(probe, parent=True, fullPath=True)[0],
           rotation=(-90, 0, 0), worldSpace=True)
plane = cmds.polyPlane(name="calibPlane", width=20, height=20, sx=1, sy=1)[0]
cmds.xform(plane, translation=(120, 20, 0), worldSpace=True)
mat = cmds.shadingNode("standardSurface", asShader=True, name="calibMat")
cmds.setAttr(mat + ".baseColor", 0.5, 0.5, 0.5, type="double3")
sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=mat + "SG")
cmds.connectAttr(mat + ".outColor", sg + ".surfaceShader", force=True)
cmds.sets(plane, edit=True, forceElement=sg)
cmds.select(clear=True)
"""

failures = []


def send(command: str, params: dict, timeout_s: float = 120.0) -> dict:
    try:
        return call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)


def ok(command: str, params: dict, timeout_s: float = 120.0) -> dict:
    response = send(command, params, timeout_s)
    if response.get("status") != "ok":
        print("FAIL: %s: %s" % (command, json.dumps(response.get("error"))[:400]))
        sys.exit(1)
    return response.get("result") or {}


def check(label: str, passed: bool, detail: str) -> None:
    print("%s %s: %s" % ("PASS" if passed else "FAIL", label, detail))
    if not passed:
        failures.append(label)


def poison() -> None:
    ok("execute_python", {"code": SETUP})
    ok("capture_viewport", {"isolate": ["calibPlane"], "angles": ["top"],
                            "lighting": "scene", "resolution": 128})


def timed(label: str, command: str, params: dict) -> None:
    t0 = time.monotonic()
    response = send(command, params, HANG_S)
    took = time.monotonic() - t0
    check("%s returns after an isolate+scene capture" % label,
          response.get("status") == "ok", "%.1f s%s" % (
              took, "" if response.get("status") == "ok"
              else " - " + json.dumps((response.get("error") or {}).get("message"))[:160]))
    if response.get("status") != "ok":
        print("the Maya on %d is now spinning in file-new and must be killed" % PORT)
        sys.exit(1)


def main() -> None:
    if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
        print("refusing to run on 9877: this eval replaces the open scene. "
              "Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.")
        sys.exit(2)
    work = tempfile.mkdtemp(prefix="mcp847_")
    saved = os.path.join(work, "subject.ma").replace("\\", "/")
    try:
        ok("new_scene", {"confirm": True})
        poison()
        timed("new_scene", "new_scene", {"confirm": True})
        if os.environ.get("MCP847_ALL") != "1":
            print("claims 2 and 3 are open on #847 - set MCP847_ALL=1 to run them "
                  "(the process will need killing if they spin)")
            return

        poison()
        ok("save_scene", {"path": saved})
        poison()  # a second capture on the now-titled scene
        timed("open_scene", "open_scene", {"path": saved, "confirm": True})

        cp = ok("checkpoint", {"label": "before_847"})
        poison()
        timed("restore_checkpoint", "restore_checkpoint",
              {"checkpoint_id": cp["checkpoint_id"]})
    finally:
        pass  # a final new_scene is exactly the call under test; leave the process as it is

    if failures:
        print("\n%d FAILED: %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
