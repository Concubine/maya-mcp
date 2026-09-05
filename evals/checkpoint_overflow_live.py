"""Live gate for redmine #835: the checkpoint counter must survive 999.

Between 2026-08-15 and 2026-09-05 every checkpoint written in an untitled
scene on this machine was id 1000: the numbering pattern matched exactly three
digits, so once 1000_<label>.ma existed the maximum stayed at 999 and every
later save was numbered 1000 again, overwriting the same-label file - the
recovery point sculpt_ops promises was one slot per label. 38 such files were
found in the default project's checkpoints dir.

The unit tests prove the arithmetic; this proves it against a real Maya's
file writes, and that each id restores ITS OWN state:

  1  a dir seeded at 999 hands out 1000, then 1001 - two different ids
  2  both files exist, beside the scene, and are not empty
  3  restore(1000_*) brings back the state at 1000, not at 1001
  4  restore(1001_*) brings back the state at 1001

DESTRUCTIVE: calls new_scene and restores over the open scene. Defaults to
port 9878 (the disposable agent-launched Maya) and refuses 9877 unless
MAYA_MCP_ALLOW_USER_SESSION=1.

Run:  .venv/Scripts/python.exe evals/checkpoint_overflow_live.py
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

SCENE_STATE = """
import maya.cmds as cmds
{'scene': cmds.file(q=True, sceneName=True),
 'a': bool(cmds.objExists('cp835_a')),
 'b': bool(cmds.objExists('cp835_b')),
 'c': bool(cmds.objExists('cp835_c'))}
"""

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


def state() -> dict:
    return structured_result(send("execute_python", {"code": SCENE_STATE}, 60.0))


def main() -> None:
    if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
        print("refusing to run on 9877: this eval discards the open scene. "
              "Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.")
        sys.exit(2)

    identity = structured_result(send("execute_python", {"code":
        "import os\nimport maya.cmds as cmds\n"
        "{'pid': os.getpid(), 'scene': cmds.file(q=True, sceneName=True)}"}, 60.0))
    print("Maya on %d: pid %s, scene=%r" % (PORT, identity["pid"], identity["scene"]))

    work = tempfile.mkdtemp(prefix="mcp835_")
    scene_path = os.path.join(work, "subject.ma").replace("\\", "/")
    cp_dir = os.path.join(work, "checkpoints")
    try:
        send("new_scene", {"confirm": True})
        send("create_primitive", {"kind": "cube", "name": "cp835_a", "scale": [2, 2, 2]})
        send("save_scene", {"path": scene_path})
        os.makedirs(cp_dir, exist_ok=True)
        with open(os.path.join(cp_dir, "999_seed.ma"), "w", encoding="utf-8") as fh:
            fh.write("// seed: the counter's last three-digit value\n")

        first = send("checkpoint", {"label": "first"})
        check("a dir at 999 hands out 1000", first["checkpoint_id"] == "1000_first",
              first["checkpoint_id"])

        send("create_primitive", {"kind": "cube", "name": "cp835_b", "scale": [2, 2, 2]})
        second = send("checkpoint", {"label": "second"})
        check("and then 1001, not 1000 again", second["checkpoint_id"] == "1001_second",
              second["checkpoint_id"])
        check("the two ids differ", first["checkpoint_id"] != second["checkpoint_id"],
              "%s vs %s" % (first["checkpoint_id"], second["checkpoint_id"]))

        for result in (first, second):
            path = result["path"]
            check("%s is a real file beside the scene" % result["checkpoint_id"],
                  os.path.isfile(path) and os.path.getsize(path) > 0
                  and os.path.dirname(os.path.normpath(path)) == os.path.normpath(cp_dir),
                  "%s (%d bytes)" % (path, os.path.getsize(path) if os.path.isfile(path) else -1))

        send("create_primitive", {"kind": "cube", "name": "cp835_c", "scale": [2, 2, 2]})
        send("restore_checkpoint", {"checkpoint_id": first["checkpoint_id"]}, 180.0)
        s = state()
        check("restoring 1000 gives the state AT 1000 (a only)",
              s["a"] and not s["b"] and not s["c"], json.dumps(s))

        send("restore_checkpoint", {"checkpoint_id": second["checkpoint_id"]}, 180.0)
        s = state()
        check("restoring 1001 gives the state AT 1001 (a and b)",
              s["a"] and s["b"] and not s["c"], json.dumps(s))

        listing = sorted(os.listdir(cp_dir))
        check("the ring sees four-digit files (no orphan 1000 slot)",
              "1000_first.ma" in listing and "1001_second.ma" in listing,
              ", ".join(listing))
    finally:
        send("new_scene", {"confirm": True})
        shutil.rmtree(work, ignore_errors=True)

    if failures:
        print("\n%d FAILED: %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
