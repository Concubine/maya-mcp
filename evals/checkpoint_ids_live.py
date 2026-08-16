"""Live gate for redmine #649: a checkpoint id must still name its own file
after the op that issued it changed the scene.

Checkpoints live in <dir of the open scene>/checkpoints/, and ids are NNN_label
- unique only inside that one directory. new_scene, open_scene and
restore_checkpoint all hand out an id and then move which directory ids resolve
in, so the documented recovery path ("restore the returned pre_checkpoint")
looked in the wrong place: not found at best, a different scene's checkpoint of
the same number at worst.

No headless test can see this. The defect is entirely in what Maya reports as
the open scene name, so only a real session proves the fix.

DESTRUCTIVE: calls new_scene twice and restores over the open scene. Defaults
to port 9878 (the disposable agent-launched Maya) and refuses 9877 unless
MAYA_MCP_ALLOW_USER_SESSION=1.

Run:  .venv/Scripts/python.exe evals/checkpoint_ids_live.py
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import DEFAULT_PORT, call, structured_result  # noqa: E402

PORT = DEFAULT_PORT
MARKER = "cp649_marker"

SCENE_STATE = """
import maya.cmds as cmds
{'scene': cmds.file(q=True, sceneName=True),
 'marker': bool(cmds.objExists('%s'))}
""" % MARKER

failures = []


def send(command: str, params: dict, timeout_s: float = 120.0) -> dict:
    try:
        response = call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)
    if response.get("status") != "ok":
        print("FAIL: %s: %s" % (command, json.dumps(response.get("error"))[:400]))
        sys.exit(1)
    return response.get("result") or {}


def check(label: str, ok: bool, detail: str) -> None:
    print("%s %s: %s" % ("PASS" if ok else "FAIL", label, detail))
    if not ok:
        failures.append(label)


def main() -> None:
    if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
        print("refusing to run on 9877: this eval discards the open scene. "
              "Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.")
        sys.exit(2)

    identity = structured_result(send("execute_python", {"code":
        "import os\nimport maya.cmds as cmds\n"
        "{'pid': os.getpid(), 'scene': cmds.file(q=True, sceneName=True)}"}, 60.0))
    print("Maya on %d: pid %s, scene=%r" % (PORT, identity["pid"], identity["scene"]))

    work = tempfile.mkdtemp(prefix="mcp649_")
    scene_path = os.path.join(work, "subject.ma").replace("\\", "/")
    expected_dir = os.path.join(work, "checkpoints")
    try:
        send("new_scene", {"confirm": True})
        send("create_primitive", {"kind": "cube", "name": MARKER, "scale": [2, 2, 2]})
        send("save_scene", {"path": scene_path})

        # The op under test: it checkpoints the scene it is about to destroy,
        # returns the id, and then leaves the session untitled - which is what
        # used to move the id out of reach.
        result = send("new_scene", {"confirm": True})
        cp_id, cp_path = result.get("pre_checkpoint"), result.get("pre_checkpoint_path")
        check("new_scene reports both handles", bool(cp_id and cp_path),
              "%s -> %s" % (cp_id, cp_path))
        check("the checkpoint is beside the scene it saved",
              bool(cp_path) and os.path.isfile(cp_path)
              and os.path.dirname(os.path.normpath(cp_path)) == os.path.normpath(expected_dir),
              str(cp_path))

        state = structured_result(send("execute_python", {"code": SCENE_STATE}, 60.0))
        check("the scene really was discarded", not state["marker"],
              "marker present=%s, scene=%r" % (state["marker"], state["scene"]))

        # BY ID, from the untitled scene - the exact call that failed in #649.
        restored = send("restore_checkpoint", {"checkpoint_id": cp_id}, 180.0)
        check("restore by id opened the file that id named",
              os.path.normpath(restored.get("path") or "") == os.path.normpath(cp_path or "x"),
              "%s" % restored.get("path"))

        state = structured_result(send("execute_python", {"code": SCENE_STATE}, 60.0))
        check("the discarded scene came back", state["marker"],
              "marker present=%s, scene=%r" % (state["marker"], state["scene"]))

        # The session is now sitting on a scene INSIDE checkpoints/. The next
        # checkpoint must land beside it, not one level deeper.
        following = send("checkpoint", {"label": "after_restore"})
        check("checkpoints do not nest after a restore",
              os.path.dirname(os.path.normpath(following["path"]))
              == os.path.normpath(expected_dir),
              following["path"])

        # And that fresh id still resolves, from a scene that has moved again.
        send("new_scene", {"confirm": True})
        again = send("restore_checkpoint", {"checkpoint_id": following["checkpoint_id"]}, 180.0)
        check("an id issued inside checkpoints/ survives the next scene change",
              os.path.normpath(again.get("path") or "") == os.path.normpath(following["path"]),
              str(again.get("path")))
    finally:
        send("new_scene", {"confirm": True})
        shutil.rmtree(work, ignore_errors=True)

    if failures:
        print("\n%d FAILED: %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
