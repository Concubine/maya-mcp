"""Live gate for redmine #847: a scene replace right after a capture returns.

MEASURED on Maya 2027 (evals/newscene_spin_probe_847/, three identical native
stack samples from three spinning processes): a capture changes what is
visible - isolate, displayLights, the temp camera and its deletion - and
Maya's Evaluation Manager invisibility evaluator starts monitoring that with
a delayed notification. A file -new / -open within ~100 ms of the capture,
before an idle turn delivered it, tears the evaluator down
(AnimUISlice!TinvisibilityEvaluator::endMonitoring) into an access violation,
after which Maya's own crash handler spins one core forever and only a
process kill recovers. The plugin's capture brackets the frame with the
evaluator off (handlers/capture.py). This proves it against a real Maya.

EVERY claim runs at ZERO client gap - a request sent the instant the capture
returns. Any gap of 0.1 s or more hid the defect for a day (a flush hop
landed on that artefact and was removed), so this gate never sleeps, and it
is only evidence when run while the user is at the machine: with the user
away the race did not reproduce in 17 processes, cause unknown.

  1  first capture of the process, isolate + scene lighting, then new_scene
  2  the same capture, save_scene, the capture again, then open_scene
  3  the same capture again, then restore_checkpoint
  4  a turntable (the other caller of the capture path), then new_scene

DESTRUCTIVE: replaces the open scene four times. Defaults to port 9878 and
refuses 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1. RUN IT ON A FRESH MAYA
each time: evals/newscene_spin_probe_847/run.ps1 -Script does the launch/stop
pair; a process this gate hangs must be killed.

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

EVALUATOR_STATE = """
import maya.cmds as cmds
cmds.evaluator(query=True, name="invisibility", enable=True)
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
    check("%s returns at zero gap after a capture" % label,
          response.get("status") == "ok", "%.1f s%s" % (
              took, "" if response.get("status") == "ok"
              else " - " + json.dumps((response.get("error") or {}).get("message"))[:160]))
    if response.get("status") != "ok":
        print("the Maya on %d is now spinning in its crash handler and must be killed" % PORT)
        sys.exit(1)


def main() -> None:
    if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
        print("refusing to run on 9877: this eval replaces the open scene. "
              "Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.")
        sys.exit(2)
    work = tempfile.mkdtemp(prefix="mcp847_")
    saved = os.path.join(work, "subject.ma").replace("\\", "/")

    before = ok("execute_python", {"code": EVALUATOR_STATE}).get("result_repr")
    ok("new_scene", {"confirm": True})
    poison()
    timed("new_scene", "new_scene", {"confirm": True})

    poison()
    ok("save_scene", {"path": saved})
    poison()  # a second capture on the now-titled scene
    timed("open_scene", "open_scene", {"path": saved, "confirm": True})

    cp = ok("checkpoint", {"label": "before_847"})
    poison()
    timed("restore_checkpoint", "restore_checkpoint",
          {"checkpoint_id": cp["checkpoint_id"]})

    ok("new_scene", {"confirm": True})
    ok("execute_python", {"code": SETUP})
    ok("capture_turntable", {"target": "calibPlane", "n_frames": 4,
                             "lighting": "scene", "resolution": 128})
    timed("new_scene after a turntable", "new_scene", {"confirm": True})

    after = ok("execute_python", {"code": EVALUATOR_STATE}).get("result_repr")
    check("the invisibility evaluator is back to what it was", before == after,
          "before %s, after %s" % (before, after))

    if failures:
        print("\n%d FAILED: %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
