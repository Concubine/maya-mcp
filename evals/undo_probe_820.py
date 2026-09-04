"""#820 PROBE: is one tool call one undo step, and does redo restore it?
undo/redo have never been sent to a real Maya. Records, does not assert.

  U1. a sequence of mutating tool calls; after each, the scene state and
      Maya's own undo-queue head (undoInfo -q -undoName).
  U2. undo(steps=1) N times: after each, does the scene equal the state
      BEFORE the matching call? (one chunk per call = yes every time)
  U3. redo(steps=1) N times: does the scene equal the state AFTER each call?
  U4. execute_python that makes THREE objects: one undo, or three?
  U5. undo with steps beyond the queue: undone vs requested.
  U6. a call that auto-checkpoints (deform): does the checkpoint save leave
      anything on the queue?
  U7. new_scene: what the queue holds afterwards, what undo does.
  U8. ONE capture_viewport (128 px - this SHOWS the agent Maya's window once):
      does it spend a step, and does undo after it revert the last real edit?

Agent Maya on 9878 only, repo cwd.
Run:  MAYA_MCP_PORT=9878 python evals/undo_probe_820.py
"""
from __future__ import annotations

import json
import os
import sys
import textwrap

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877:
    raise SystemExit("refusing the user's Maya")
OUT = os.path.join(_HERE, "undo_probe_820")
os.makedirs(OUT, exist_ok=True)
FINDINGS = {}


def ok(command, params, timeout_s=300.0):
    r = call(command, params, timeout_s=timeout_s, port=PORT)
    if r.get("status") != "ok":
        raise SystemExit("%s failed: %s" % (command, json.dumps(r.get("error"), indent=1)))
    return r.get("result") or {}


def py(code, what="r", timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": textwrap.dedent(code).strip()}, timeout_s), what)


def show(label, value):
    FINDINGS[label] = value
    with open(os.path.join(OUT, "findings.json"), "w", encoding="utf-8") as fh:
        json.dump(FINDINGS, fh, indent=1, default=str)
    print("\n--- %s ---" % label)
    print(json.dumps(value, indent=1, sort_keys=True, default=str))


STATE = '''
import maya.cmds as cmds
out = {}
for t in sorted(cmds.ls(type="transform", long=True)):
    if cmds.listRelatives(t, s=True, type="camera"):
        continue
    shapes = cmds.listRelatives(t, s=True, f=True, ni=True) or []
    mesh = [s for s in shapes if cmds.nodeType(s) == "mesh"]
    entry = {"t": [round(v, 4) for v in cmds.xform(t, q=True, ws=True, t=True)]}
    if mesh:
        entry["faces"] = cmds.polyEvaluate(t, f=True)
        entry["sg"] = sorted(cmds.listSets(object=mesh[0], type=1) or [])
        entry["bbox_y"] = round(cmds.exactWorldBoundingBox(t)[4], 4)
    out[t] = entry
{"scene": out, "undo_head": cmds.undoInfo(q=True, undoName=True), "redo_head": cmds.undoInfo(q=True, redoName=True),
 "undo_on": cmds.undoInfo(q=True, state=True)}
'''


def state():
    return py(STATE, "state")


def same(a, b):
    return a["scene"] == b["scene"]


ident = py("import os, maya_plugin\n{'file': maya_plugin.__file__}")
print("live plugin:", ident)
ok("new_scene", {"confirm": True})
show("U0 queue after new_scene", state())

# U1 ------------------------------------------------------------------------
calls = [
    ("create_primitive", {"kind": "cube", "name": "a"}),
    ("transform", {"names": ["|a"], "translate": [2, 0, 0]}),
    ("create_primitive", {"kind": "sphere", "name": "b"}),
    ("assign_material", {"mesh": "|a", "shader": "lambert", "name": "red", "params": {"color": [1, 0, 0]}}),
    ("combine", {"names": ["|a", "|b"], "name": "ab"}),
    ("deform", {"mesh": "|ab", "deformer": "bend", "params": {"curvature": 40}}),
    ("execute_python", {"code": "import maya.cmds as cmds\nfor i in range(3): cmds.polyCube(name='py%d' % i)\nTrue"}),
    ("delete_objects", {"names": ["|py1"]}),
]
states = [state()]
heads = []
for cmd, params in calls:
    ok(cmd, params)
    s = state()
    states.append(s)
    heads.append({"call": cmd, "undo_head": s["undo_head"], "objects": sorted(s["scene"])})
show("U1 after each call: undo-queue head and objects", heads)

# U2 ------------------------------------------------------------------------
steps = []
for i in range(len(calls), 0, -1):
    res = ok("undo", {"steps": 1})
    s = state()
    steps.append({"undoing": calls[i - 1][0], "undone": res["undone"],
                  "scene == state before that call": same(s, states[i - 1]),
                  "undo_head": s["undo_head"], "redo_head": s["redo_head"],
                  "objects": sorted(s["scene"])})
show("U2 undo one step at a time", steps)
show("U2b scene after undoing everything == the fresh scene", same(state(), states[0]))

# U5 -----------------------------------------------------------------------
show("U5 undo past the end of the queue", ok("undo", {"steps": 5}))

# U3 ------------------------------------------------------------------------
redos = []
for i in range(1, len(calls) + 1):
    res = ok("redo", {"steps": 1})
    s = state()
    redos.append({"redoing": calls[i - 1][0], "redone": res["redone"],
                  "scene == state after that call": same(s, states[i]),
                  "objects": sorted(s["scene"])})
show("U3 redo one step at a time", redos)
show("U3b redo past the end", ok("redo", {"steps": 3}))

# U6 ------------------------------------------------------------------------
before = state()
ok("deform", {"mesh": "|ab", "deformer": "twist", "params": {"endAngle": 30}})
after = state()
cp = py("from maya_plugin.handlers import session\n"
        "import maya.cmds as cmds\n{'undo_head': cmds.undoInfo(q=True, undoName=True), 'scene_name': cmds.file(q=True, sceneName=True)}")
res = ok("undo", {"steps": 1})
back = state()
show("U6 a call that auto-checkpoints (deform twist): one undo returns the pre-call scene",
     {"after_call": cp, "undone": res["undone"], "back == before": same(back, before),
      "bbox_y before/after/back": [before["scene"].get("|ab", {}).get("bbox_y"), after["scene"].get("|ab", {}).get("bbox_y"), back["scene"].get("|ab", {}).get("bbox_y")]})

# U8 ------------------------------------------------------------------------
ok("transform", {"names": ["|ab"], "translate": [0, 3, 0]})
moved = state()
ok("capture_viewport", {"angles": ["front"], "resolution": 128})
after_cap = state()
res = ok("undo", {"steps": 1})
back = state()
show("U8 a capture between an edit and its undo",
     {"head after edit": moved["undo_head"], "head after capture": after_cap["undo_head"],
      "capture changed the scene": not same(moved, after_cap),
      "undo after capture reverted the edit": res["undone"] == 1 and back["scene"].get("|ab", {}).get("t") != moved["scene"].get("|ab", {}).get("t"),
      "ab.t after edit / after undo": [moved["scene"].get("|ab", {}).get("t"), back["scene"].get("|ab", {}).get("t")]})

# U7 ------------------------------------------------------------------------
ok("new_scene", {"confirm": True})
s = state()
res = ok("undo", {"steps": 1})
show("U7 new_scene then undo", {"head after new_scene": s["undo_head"], "undone": res["undone"],
                                "objects after undo": sorted(state()["scene"])})
print("\nfindings ->", os.path.join(OUT, "findings.json"))
