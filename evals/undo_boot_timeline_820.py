"""#820 PROBE: the boot window. Plants one request chunk every two seconds
from the moment the plugin's port listens and counts how many survive -
MEASURED: Maya's deferred plugin autoloads (16 -> 53 plugins in the first
~7 s) FLUSH the undo queue as they load, so every chunk recorded before
~8 s is gone; from then on all survive. That is why start_server now waits
for the autoloads to settle before it binds.

Run right after launching the agent Maya:
  MAYA_MCP_PORT=9878 python evals/undo_boot_timeline_820.py
"""
import json
import os
import sys
import textwrap
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
from live_call import call, structured_result  # noqa: E402

P = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if P == 9877:
    raise SystemExit("refusing the user's Maya")
T0 = time.time()


def ok(c, p):
    r = call(c, p, timeout_s=300, port=P)
    if r.get("status") != "ok":
        raise SystemExit(json.dumps(r.get("error"), indent=1))
    return r.get("result") or {}


def py(code):
    return structured_result(ok("execute_python", {"code": textwrap.dedent(code).strip()}), "r")


# plant a marker chunk; on the next poll, is it still on the queue?
POLL = '''
import maya.cmds as cmds
names = []
while cmds.undoInfo(q=True, undoName=True) != "":
    names.append(cmds.undoInfo(q=True, undoName=True))
    cmds.undo()
for _ in names:
    cmds.redo()
markers = sum(1 for n in names if n == "maya-mcp")   # each poll request IS one chunk
if not cmds.objExists("markerNode"):
    cmds.createNode("transform", name="markerNode")
cmds.undoInfo(openChunk=True, chunkName="marker")
cmds.setAttr("markerNode.tx", cmds.getAttr("markerNode.tx") + 1.0)
cmds.undoInfo(closeChunk=True)
{"queue": names, "markers_surviving": markers, "plugins": len(cmds.pluginInfo(q=True, listPlugins=True) or [])}
'''
ok("new_scene", {"confirm": True})
planted = 0
last = None
for i in range(45):
    t = time.time() - T0
    try:
        r = py(POLL)
    except Exception as exc:  # noqa: BLE001 - a boot-window failure is itself a datum
        print("t=%5.1fs poll FAILED: %s" % (t, str(exc)[:160]), flush=True)
        time.sleep(2.0)
        continue
    lost = planted - r["markers_surviving"]
    line = "t=%5.1fs plugins=%3d markers planted=%2d surviving=%2d %s" % (
        t, r["plugins"], planted, r["markers_surviving"], "FLUSHED" if lost > 0 and planted else "")
    others = [n for n in r["queue"] if n not in ("marker", "maya-mcp")]
    if others != last:
        line += "  other entries: %s" % others
        last = others
    print(line, flush=True)
    if lost > 0:
        planted = r["markers_surviving"]
    planted += 1
    time.sleep(2.0)
