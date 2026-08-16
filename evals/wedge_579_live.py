"""Live gate for redmine #579: an isolate-captured boolean mesh must not wedge new_scene.

#579 recorded @maya_new_scene@ spinning Maya's main thread forever - 3/3 - once
the scene held a boolean-produced (etched) mesh that had been isolate-captured.
The recovery was killing the process. Re-run 2026-08-16 against the same Maya
build (27.2.0.1859, unchanged since 2026-07-20) and an unchanged isolate path,
it did not reproduce: seven arms, zero wedges, on both a non-drawing
agent-launched Maya and the user's rendering session.

That makes this a GUARD, not a repro. It runs the documented trigger and fails
if new_scene ever stops returning again. A wedge here is not a slow machine:
the ceiling is 45s for a call that measures well under two seconds even with
every core saturated.

DESTRUCTIVE: builds a cube, etches it, then calls new_scene - which discards
the scene. It defaults to port 9878 (the disposable agent-launched Maya) and
refuses to touch 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1 is set, because on
the user's session this eval throws their open scene away by design.

Run:  .venv/Scripts/python.exe evals/wedge_579_live.py
Exit: 0 pass, 1 WEDGED (or the trigger could not be built), 2 no connection.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import DEFAULT_PORT, call, structured_result  # noqa: E402

# A wedge is an infinite busy loop, so any finite ceiling separates it from
# slowness. 45s is ~25x the slowest new_scene measured under a fully saturated
# 32-core box, which keeps a loaded machine from reading as a defect.
CEILING_S = 45.0

IDENTITY = """
import os
import maya.cmds as cmds
{'pid': os.getpid(),
 'scene': cmds.file(q=True, sceneName=True),
 'drawing': bool(cmds.getPanel(visiblePanels=True))}
"""

PANEL_STATE = """
import maya.cmds as cmds
panels = cmds.getPanel(type='modelPanel') or []
{p: {'viewSelected': bool(cmds.modelEditor(p, q=True, viewSelected=True)),
     'viewObjects': cmds.modelEditor(p, q=True, viewObjects=True)} for p in panels}
"""


def fail(message: str) -> None:
    print("FAIL: %s" % message)
    sys.exit(1)


def send(command: str, params: dict, timeout_s: float = 180.0) -> dict:
    try:
        response = call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)
    if response.get("status") != "ok":
        fail("%s: %s" % (command, json.dumps(response.get("error"))[:400]))
    return response.get("result") or {}


PORT = DEFAULT_PORT


def main() -> None:
    if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
        print("refusing to run on 9877: this eval calls new_scene and discards the "
              "open scene. Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.")
        sys.exit(2)

    identity = structured_result(send("execute_python", {"code": IDENTITY}, 60.0))
    print("Maya on %d: pid %s, drawing=%s, scene=%r"
          % (PORT, identity["pid"], identity["drawing"], identity["scene"]))

    host = send("create_primitive", {"kind": "cube", "name": "wedge579_host",
                                     "scale": [4, 4, 4], "translate": [0, 500, 0]})["name"]
    subject = send("etch_text", {"mesh": host, "text": "A", "face": 0,
                                 "width": 2.0, "depth": 0.2,
                                 "new_name": "wedge579_subject"}, 300.0)["name"]

    started = time.time()
    send("capture_viewport", {"angles": ["three_quarter"], "resolution": 512,
                              "isolate": [subject]}, 300.0)
    capture_s = time.time() - started
    residue = {panel: state for panel, state
               in structured_result(send("execute_python", {"code": PANEL_STATE}, 60.0)).items()
               if state["viewSelected"] or state["viewObjects"]}
    print("isolate capture of %s: %.2fs, panel residue: %s"
          % (subject, capture_s, residue or "none"))

    started = time.time()
    try:
        result = call("new_scene", {"confirm": True},
                      timeout_s=CEILING_S - 30.0, port=PORT)
    except (socket.timeout, TimeoutError):
        fail("new_scene did not return within %.0fs - #579 is back. Maya's main "
             "thread is spinning; the process must be killed." % (time.time() - started))
        return
    elapsed = time.time() - started
    if result.get("status") != "ok":
        fail("new_scene: %s" % json.dumps(result.get("error"))[:400])
    print("PASS: new_scene returned in %.2fs (pre_checkpoint %s)"
          % (elapsed, (result.get("result") or {}).get("pre_checkpoint")))
    print("note: that pre_checkpoint id is not resolvable by restore_checkpoint "
          "after new_scene - see redmine #649.")


if __name__ == "__main__":
    main()
