"""Live gate for redmine #836: a long bake shows its progress.

The kethran run's bake ran 40 minutes with an empty out_dir and a
BusyError that only knew the elapsed seconds. Now each map is committed
into out_dir the moment it is verified, and every BusyError names the map
the bake is on. This proves both against a real Maya: one connection runs
a bake slow enough to be watched (a dense sphere, two maps at 1024 through
Arnold), a second polls the plugin every 0.2 s and records the busy hints
and what out_dir holds at each poll.

  1  at least one BusyError hint while the bake runs names the stage
     ("at 'map N of 2: ...'") and how long it has stood
  2  the first map's final file is in out_dir BEFORE the bake returns
  3  the bake returns ok with both maps, no .part left behind
  4  the stage is gone once the bake has returned (a later hint would not
     carry it) - checked directly: no stale stage on a plain ping

Defaults to port 9878 and refuses 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1
(it replaces the open scene). Needs mtoa on that Maya.

Run:  .venv/Scripts/python.exe evals/bake_progress_live.py
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import DEFAULT_PORT, call  # noqa: E402

PORT = DEFAULT_PORT

SETUP = """
import maya.cmds as cmds
sphere = cmds.polySphere(name="denseSphere", radius=50, sx=200, sy=200)[0]
mat = cmds.shadingNode("standardSurface", asShader=True, name="denseMat")
sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=mat + "SG")
cmds.connectAttr(mat + ".outColor", sg + ".surfaceShader", force=True)
cmds.sets(sphere, edit=True, forceElement=sg)
cmds.select(clear=True)
cmds.polyEvaluate(sphere, triangle=True)
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


def main() -> None:
    if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
        print("refusing to run on 9877: this eval replaces the open scene. "
              "Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.")
        sys.exit(2)
    out_dir = tempfile.mkdtemp(prefix="mcp836_")
    ok("new_scene", {"confirm": True})
    tris = ok("execute_python", {"code": SETUP}).get("result_repr")
    print("sphere: %s tris" % tris)

    bake_result: dict = {}
    polls: list = []
    done = threading.Event()

    def bake() -> None:
        t0 = time.monotonic()
        bake_result["response"] = send("bake_mesh_maps", {
            "meshes": ["|denseSphere"], "out_dir": out_dir,
            "maps": ["ao", "curvature"], "resolution": 1024,
            "apply_ao": False}, 600.0)
        bake_result["took"] = time.monotonic() - t0
        done.set()

    threading.Thread(target=bake, daemon=True).start()
    time.sleep(0.5)
    while not done.is_set():
        try:
            resp = call("ping", {}, timeout_s=10.0, port=PORT)
        except OSError as exc:
            resp = {"status": "error", "error": {"type": type(exc).__name__, "hint": str(exc)}}
        polls.append({"t": time.monotonic(), "status": resp.get("status"),
                      "type": (resp.get("error") or {}).get("type"),
                      "hint": (resp.get("error") or {}).get("hint", ""),
                      "files": sorted(os.listdir(out_dir))})
        time.sleep(0.2)
    done.wait()

    resp = bake_result["response"]
    took = bake_result["took"]
    busy = [p for p in polls if p["type"] == "BusyError"]
    staged = [p for p in busy if "at 'map " in p["hint"]]
    print("bake took %.1f s; %d polls, %d busy, %d naming a stage"
          % (took, len(polls), len(busy), len(staged)))
    for p in staged[:1] + staged[-1:]:
        print("  hint: %s" % p["hint"][:200])

    check("a BusyError during the bake names the stage and its age",
          bool(staged) and all(" for " in p["hint"].split("at '", 1)[1] for p in staged),
          "%d of %d busy hints carried a stage" % (len(staged), len(busy)))
    first_seen = [p for p in polls if "denseSphere_ao.png" in p["files"]]
    check("the first map is in out_dir before the bake returns", bool(first_seen),
          "seen in %d polls while the bake ran" % len(first_seen) if first_seen
          else "never seen during the bake (files at the last poll: %s)" % (
              polls[-1]["files"] if polls else "no polls"))
    both = resp.get("status") == "ok" and [b["map"] for b in (resp.get("result") or {}).get("baked", [])] == ["ao", "curvature"]
    check("the bake returns ok with both maps", both,
          json.dumps(resp.get("error"))[:200] if resp.get("status") != "ok" else "ok")
    check("no .part left behind", not [f for f in os.listdir(out_dir) if ".part" in f],
          str(sorted(os.listdir(out_dir))))
    stale = ok("execute_python", {"code": "from maya_plugin import progress\nprogress.current()\n"})
    check("no stage stands once the bake has returned", stale.get("result_repr") in (None, "None"),
          str(stale.get("result_repr")))

    if failures:
        print("\n%d FAILED: %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
