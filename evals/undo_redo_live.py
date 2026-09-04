"""#820 LIVE GATE: one tool call is one undo step, and redo restores it -
measured with Maya's own no-op queue entries in play.

  1. eight mutating calls (create, transform, create, assign_material,
     combine, deform, execute_python x3 objects, delete), with a pause after
     each so Maya's deferred callbacks land on the queue as they do between
     an agent's requests. Then undo(steps=1) eight times: after EACH, the
     scene equals the state before the matching call and `undone` is 1 - the
     first create included (the scene is back to empty).
  2. undo past the end: undone 0, queue_empty true; the scene unchanged.
  3. redo(steps=1) eight times: each returns the state after the matching
     call; redo past the end: redone 0.
  4. a call that auto-checkpoints (deform twist): one undo returns the
     pre-call scene.
  5. new_scene then undo: undone 0 (the old handler said 1).

No captures. DESTRUCTIVE: calls maya_new_scene. Agent Maya on 9878 only;
refuses 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1. Phase 0 asserts the live
Maya imports THIS working tree.

Run:  MAYA_MCP_PORT=9878 python evals/undo_redo_live.py
"""
from __future__ import annotations

import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
    print("refusing to run against port 9877 (the user's Maya): this gate "
          "calls new_scene. Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.",
          file=sys.stderr)
    raise SystemExit(2)

OUT = os.path.join(_HERE, "undo_redo_live")
os.makedirs(OUT, exist_ok=True)
RESULTS = []
IDLE_S = 0.8   # long enough for Maya's deferred callbacks to push their entries


def check(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    print("%-4s %-72s %s" % ("PASS" if ok else "FAIL", label, detail), flush=True)


def ok(command, params, timeout_s=300.0):
    response = call(command, params, timeout_s=timeout_s, port=PORT)
    if response.get("status") != "ok":
        raise SystemExit("%s failed: %s" % (command, response.get("error")))
    return response.get("result") or {}


def py(code, what, timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s), what)


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
out
'''


def scene():
    return py(STATE, "scene")


# --------------------------------------------------------------- phase 0
print("=== 0. who answered, and whose code is it ===", flush=True)
ident = py("import os, maya_plugin\n{'file': maya_plugin.__file__, 'cwd': os.getcwd()}", "identity")
loaded = os.path.normcase(os.path.abspath(ident["file"]))
expected = os.path.normcase(os.path.join(REPO, "maya_plugin", "__init__.py"))
if loaded != expected:
    print("WRONG CODE: live Maya imports %s, not %s." % (loaded, expected), file=sys.stderr)
    raise SystemExit(2)
has = py("from maya_plugin.handlers import session\nhasattr(session, 'NO_OP_UNDO_ENTRIES')", "loaded")
check("0. the #820 session handler is loaded in the live Maya", has is True)

# --------------------------------------------------------------- phase 1
print("\n=== 1. eight calls, eight single undos ===", flush=True)
ok("new_scene", {"confirm": True})
time.sleep(IDLE_S)
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
states = [scene()]
for cmd, params in calls:
    ok(cmd, params)
    time.sleep(IDLE_S)
    states.append(scene())
QUEUE = py('''
import maya.cmds as cmds
names = []
while cmds.undoInfo(q=True, undoName=True) != "":
    names.append(cmds.undoInfo(q=True, undoName=True))
    cmds.undo()
for _ in names:
    cmds.redo()
names
''', "queue")
CHUNKS = sum(1 for n in QUEUE if n == "maya-mcp")
NOISE = [n for n in QUEUE if n != "maya-mcp"]
check("1a. the eight calls built what they should (5 objects, then 4)",
      sorted(states[7]) == ["|ab", "|bend1Handle", "|py0", "|py1", "|py2"] and sorted(states[8]) == ["|ab", "|bend1Handle", "|py0", "|py2"],
      json.dumps(sorted(states[8])))
all_ok, detail, total_skipped = True, [], 0
for i in range(len(calls), 0, -1):
    res = ok("undo", {"steps": 1})
    time.sleep(IDLE_S)
    now = scene()
    good = res["undone"] == 1 and now == states[i - 1]
    total_skipped += len(res.get("skipped") or [])
    all_ok &= good
    detail.append("%s:%s" % (calls[i - 1][0], "ok" if good else "MISMATCH"))
check("1b. each single undo returns EXACTLY the scene before its call, undone=1 each time",
      all_ok, " ".join(detail))
check("1c. ... including the first create: the scene is empty again", scene() == {} and states[0] == {},
      json.dumps(sorted(scene())))
check("1d. no chunk absorbed a deferred callback: exactly eight maya-mcp chunks were on the queue",
      CHUNKS == 8, "maya-mcp chunks %r (noise entries %r, skipped during undo %d)" % (CHUNKS, NOISE, total_skipped))

# --------------------------------------------------------------- phase 2
print("\n=== 2. past the end ===", flush=True)
res = ok("undo", {"steps": 5})
check("2. undo on the exhausted queue: undone 0, queue_empty, scene unchanged",
      res["undone"] == 0 and res["queue_empty"] is True and scene() == {},
      json.dumps({k: res[k] for k in ("undone", "requested", "queue_empty")}))

# --------------------------------------------------------------- phase 3
print("\n=== 3. eight single redos ===", flush=True)
all_ok, detail = True, []
for i in range(1, len(calls) + 1):
    res = ok("redo", {"steps": 1})
    time.sleep(IDLE_S)
    now = scene()
    good = res["redone"] == 1 and now == states[i]
    all_ok &= good
    detail.append("%s:%s" % (calls[i - 1][0], "ok" if good else "MISMATCH"))
check("3a. each single redo returns EXACTLY the scene after its call, redone=1 each time",
      all_ok, " ".join(detail))
res = ok("redo", {"steps": 3})
check("3b. redo past the end: redone 0, queue_empty", res["redone"] == 0 and res["queue_empty"] is True,
      json.dumps({k: res[k] for k in ("redone", "requested", "queue_empty")}))

# --------------------------------------------------------------- phase 4
print("\n=== 4. a call that auto-checkpoints ===", flush=True)
before = scene()
ok("deform", {"mesh": "|ab", "deformer": "twist", "params": {"endAngle": 30}})
time.sleep(IDLE_S)
changed = scene() != before
res = ok("undo", {"steps": 1})
check("4. deform twist (auto-checkpoint) then one undo: the scene is back exactly",
      changed and res["undone"] == 1 and scene() == before, "changed %r undone %r" % (changed, res["undone"]))

# --------------------------------------------------------------- phase 5
print("\n=== 5. new_scene then undo ===", flush=True)
ok("new_scene", {"confirm": True})
time.sleep(IDLE_S)
res = ok("undo", {"steps": 1})
check("5. undo after new_scene: undone 0 (the nameless entry is stepped over, not counted)",
      res["undone"] == 0 and res["queue_empty"] is True, json.dumps(res))

# --------------------------------------------------------------- summary
passed = sum(1 for _, r, _ in RESULTS if r)
print("\n%d / %d passed" % (passed, len(RESULTS)))
with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as fh:
    json.dump([{"check": label, "ok": r, "detail": d} for label, r, d in RESULTS], fh, indent=1)
raise SystemExit(0 if passed == len(RESULTS) else 1)
