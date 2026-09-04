"""#820 PROBE 2: enumerate the undo queue BY NAME around the two things probe 1
refuted - the extra `selectionMaskResetAll` entry and undo/redo on an empty
queue. Records, does not assert.

  Q1. fresh scene -> create_primitive: every entry on the queue, by name
  Q2. fresh scene -> three query-only execute_python calls -> create: same
  Q3. fresh scene -> a bare cmds.polyCube inside ONE hand-opened chunk: same
      (is the extra entry Maya's, pushed after our chunk closes?)
  Q4. second create in the same scene: does the extra entry come back?
  Q5. cmds.undo() / cmds.redo() on an empty queue: raise, or silently no-op?
      and the undoQueueEmpty / redoQueueEmpty query flags
  Q6. does an interactive-style selection change push an entry?

Run:  MAYA_MCP_PORT=9878 python evals/undo_probe_820b.py
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


def py(code, what="r"):
    return structured_result(ok("execute_python", {"code": textwrap.dedent(code).strip()}), what)


def show(label, value):
    FINDINGS[label] = value
    with open(os.path.join(OUT, "findings_b.json"), "w", encoding="utf-8") as fh:
        json.dump(FINDINGS, fh, indent=1, default=str)
    print("\n--- %s ---" % label)
    print(json.dumps(value, indent=1, sort_keys=True, default=str))


# Walk the whole queue: undo until empty, recording each head name and whether
# the scene's transform list changed; then redo it all back.
WALK = '''
import maya.cmds as cmds
names = []
def objs():
    return sorted(t for t in cmds.ls(type="transform", long=True) if not cmds.listRelatives(t, s=True, type="camera"))
while not cmds.undoInfo(q=True, undoQueueEmpty=True):
    head = cmds.undoInfo(q=True, undoName=True)
    before = objs()
    cmds.undo()
    names.append({"name": head, "changed_objects": objs() != before})
for _ in names:
    cmds.redo()
{"queue_top_to_bottom": names, "empty_after_redo_all": cmds.undoInfo(q=True, undoQueueEmpty=True), "redo_empty": cmds.undoInfo(q=True, redoQueueEmpty=True)}
'''

ok("new_scene", {"confirm": True})
ok("create_primitive", {"kind": "cube", "name": "a"})
show("Q1 fresh scene -> create_primitive", py(WALK))

ok("new_scene", {"confirm": True})
for _ in range(3):
    py("import maya.cmds as cmds\ncmds.ls(type='transform')")
show("Q2a fresh scene -> 3 query-only execute_python calls: queue", py(WALK))
ok("create_primitive", {"kind": "cube", "name": "a"})
show("Q2b ... then create", py(WALK))

ok("new_scene", {"confirm": True})
show("Q3 fresh scene -> bare polyCube in one hand-opened chunk (no tool)", py('''
import maya.cmds as cmds
cmds.undoInfo(openChunk=True, chunkName="probe-chunk")
cmds.polyCube(name="raw")
cmds.undoInfo(closeChunk=True)
{"head_right_after": cmds.undoInfo(q=True, undoName=True)}
''') | py(WALK))

ok("create_primitive", {"kind": "cube", "name": "b"})
show("Q4 a SECOND create in the same scene", py(WALK))

ok("new_scene", {"confirm": True})
show("Q5 undo/redo on an empty queue", py('''
import maya.cmds as cmds
out = {"undo_empty": cmds.undoInfo(q=True, undoQueueEmpty=True), "redo_empty": cmds.undoInfo(q=True, redoQueueEmpty=True)}
try:
    r = cmds.undo(); out["undo_raised"] = False; out["undo_returned"] = r
except Exception as e:
    out["undo_raised"] = "%s: %s" % (type(e).__name__, e)
try:
    r = cmds.redo(); out["redo_raised"] = False; out["redo_returned"] = r
except Exception as e:
    out["redo_raised"] = "%s: %s" % (type(e).__name__, e)
out
'''))

ok("new_scene", {"confirm": True})
ok("create_primitive", {"kind": "cube", "name": "a"})
show("Q6 select / deselect after a create: entries pushed?", py('''
import maya.cmds as cmds
h0 = cmds.undoInfo(q=True, undoName=True)
cmds.select("a"); h1 = cmds.undoInfo(q=True, undoName=True)
cmds.select(clear=True); h2 = cmds.undoInfo(q=True, undoName=True)
{"after_create": h0, "after_select": h1, "after_clear": h2}
''') | py(WALK))
ok("new_scene", {"confirm": True})
print("\nfindings ->", os.path.join(OUT, "findings_b.json"))
