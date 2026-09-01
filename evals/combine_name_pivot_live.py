"""#803 LIVE GATE: combine claims a consumed input's name, and both combine and
mesh_cleanup report the pivot Maya actually has after their freeze.

Every check runs over the wire through the real command dispatch, against a
scene built and queried through execute_python, and every positive is paired
with a discriminating control:

  1. combine(names=[body, arm], name="body") -> |body, no warning, exactly one
     body in the scene. Control: name="fresh" is honoured directly.
  2. combine with an UNRELATED |body present -> |body_001 + a warning naming
     both, and the unrelated |body is untouched.
  3. combine defaults (pivot=center, freeze=True): the reported pivot equals
     xform -q -ws -rp AND the bounding-box centre. Control: freeze=False,
     same equality. pivot="origin": [0,0,0] both ways.
  4. mesh_cleanup on a rotated, scaled mesh with a world pivot at (0,5,0):
     after the call the pivot is (0,5,0), translate is zero, warnings empty.
     Control: freeze_transforms=False leaves translate non-zero.

DESTRUCTIVE: calls maya_new_scene. Runs against the disposable agent Maya on
9878 and REFUSES 9877 (the user's session) unless MAYA_MCP_ALLOW_USER_SESSION=1.
The live Maya must import THIS working tree (launch it with the repo as its
working directory - Maya puts the cwd on sys.path). Phase 0 asserts exactly that.

Run:  MAYA_MCP_PORT=9878 MAYA_MCP_EXPECT_PID=<pid> python evals/combine_name_pivot_live.py
"""
from __future__ import annotations

import os
import sys

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

RESULTS = []


def check(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    print("%-4s %-66s %s" % ("PASS" if ok else "FAIL", label, detail),
          flush=True)


def send(command, params, timeout_s=180.0):
    return call(command, params, timeout_s=timeout_s, port=PORT)


def ok(command, params, timeout_s=180.0):
    response = send(command, params, timeout_s)
    if response.get("status") != "ok":
        raise SystemExit("%s failed: %s" % (command, response.get("error")))
    return response.get("result") or {}


def py(code, what, timeout_s=180.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s),
                             what)


def close(a, b, tol=1e-4):
    return len(a) == len(b) and all(abs(float(x) - float(y)) <= tol
                                    for x, y in zip(a, b))


RP = ("[round(v, 6) for v in cmds.xform(%r, q=True, ws=True, rotatePivot=True)]")

# --------------------------------------------------------------- phase 0
print("=== 0. who answered, and whose code is it ===", flush=True)
ident = py("import os, maya_plugin\n"
           "{'file': maya_plugin.__file__, 'cwd': os.getcwd()}", "identity")
loaded = os.path.normcase(os.path.abspath(ident["file"]))
expected = os.path.normcase(os.path.join(REPO, "maya_plugin", "__init__.py"))
if loaded != expected:
    print("WRONG CODE: live Maya imports %s, not %s. Relaunch it with the "
          "repo as its working directory." % (loaded, expected),
          file=sys.stderr)
    raise SystemExit(2)
print("live plugin: %s" % loaded, flush=True)

# --------------------------------------------------------------- phase 1
print("\n=== 1. the result may take a consumed input's own name ===", flush=True)
ok("new_scene", {"confirm": True})
py("""
import maya.cmds as cmds
body = cmds.polyCube(name="body")[0]
arm = cmds.polyCube(name="arm")[0]; cmds.xform(arm, ws=True, t=(2, 0, 0))
cmds.ls(type="transform")
""", "setup")
res = ok("combine", {"names": ["|body", "|arm"], "name": "body"})
holders = py("import maya.cmds as cmds\ncmds.ls('body', long=True)", "holders")
check("1a. combine(body, arm, name='body') hands back |body",
      res.get("name") == "|body", "got %r" % res.get("name"))
check("1b. exactly one body in the scene and it is the result",
      holders == ["|body"], "ls body -> %r" % (holders,))
check("1c. no warning for a name the unite itself freed",
      res.get("warnings") == [], "warnings=%r" % (res.get("warnings"),))
check("1d. the result is one mesh of two shells",
      res.get("shells") == 2 and res.get("inputs") == 2,
      "shells=%r inputs=%r" % (res.get("shells"), res.get("inputs")))

ok("new_scene", {"confirm": True})
py("""
import maya.cmds as cmds
cmds.polyCube(name="body"); a = cmds.polyCube(name="arm")[0]; cmds.xform(a, ws=True, t=(2, 0, 0))
True
""", "setup")
res = ok("combine", {"names": ["|body", "|arm"], "name": "fresh"})
check("1e. CONTROL: a free name is honoured directly",
      res.get("name") == "|fresh" and res.get("warnings") == [],
      "got %r" % res.get("name"))

# --------------------------------------------------------------- phase 2
print("\n=== 2. a name held by an UNRELATED object gets the suffix and a warning ===",
      flush=True)
ok("new_scene", {"confirm": True})
py("""
import maya.cmds as cmds
cmds.polyCube(name="a"); b = cmds.polyCube(name="b")[0]; cmds.xform(b, ws=True, t=(2, 0, 0))
other = cmds.polyCube(name="body")[0]; cmds.xform(other, ws=True, t=(0, 9, 0))
True
""", "setup")
res = ok("combine", {"names": ["|a", "|b"], "name": "body"})
after = py("""
import maya.cmds as cmds
{"body": cmds.ls("body", long=True),
 "body_t": [round(v, 6) for v in cmds.xform("|body", q=True, ws=True, t=True)],
 "transforms": sorted(t for t in cmds.ls(type="transform") if t not in ("front", "persp", "side", "top"))}
""", "after")
check("2a. the result is |body_001",
      res.get("name") == "|body_001", "got %r" % res.get("name"))
check("2b. the unrelated |body is untouched (still at y=9)",
      after["body"] == ["|body"] and close(after["body_t"], [0, 9, 0]),
      "%r at %r" % (after["body"], after["body_t"]))
check("2c. the warning names the requested and the assigned name",
      any("body" in w and "body_001" in w for w in res.get("warnings") or []),
      "warnings=%r" % (res.get("warnings"),))
check("2d. the scene holds exactly body and body_001",
      after["transforms"] == ["body", "body_001"], "%r" % (after["transforms"],))

# --------------------------------------------------------------- phase 3
print("\n=== 3. the reported pivot is where Maya has it, after the freeze ===",
      flush=True)


def build_pair():
    ok("new_scene", {"confirm": True})
    py("""
import maya.cmds as cmds
a = cmds.polyCube(name="a")[0]; cmds.xform(a, ws=True, t=(1, 2, 3), ro=(0, 30, 0))
b = cmds.polyCube(name="b")[0]; cmds.xform(b, ws=True, t=(3, 4, 5), s=(2, 2, 2))
True
""", "setup")


build_pair()
res = ok("combine", {"names": ["|a", "|b"], "name": "p"})
live = py("import maya.cmds as cmds\n" + RP % "|p", "rp")
bbox = py("import maya.cmds as cmds\nbb = cmds.exactWorldBoundingBox('|p')\n"
          "[round((bb[i] + bb[i + 3]) / 2.0, 6) for i in range(3)]", "centre")
check("3a. defaults (center, freeze): reported pivot == live rotatePivot",
      close(res.get("pivot") or [], live), "reported %r live %r" % (res.get("pivot"), live))
check("3b. ... and == the bounding-box centre, i.e. not the origin",
      close(live, bbox) and not close(live, [0, 0, 0]), "centre %r" % (bbox,))
check("3c. ... with the transform frozen (translate 0)",
      close(py("import maya.cmds as cmds\n[round(v, 6) for v in cmds.xform('|p', q=True, ws=True, t=True)]", "t"),
            [0, 0, 0]) and res.get("frozen") is True)

build_pair()
res = ok("combine", {"names": ["|a", "|b"], "name": "p", "freeze": False})
live = py("import maya.cmds as cmds\n" + RP % "|p", "rp")
check("3d. CONTROL freeze=False: reported == live, same place",
      close(res.get("pivot") or [], live) and close(live, bbox),
      "reported %r live %r" % (res.get("pivot"), live))

build_pair()
res = ok("combine", {"names": ["|a", "|b"], "name": "p", "pivot": "origin"})
live = py("import maya.cmds as cmds\n" + RP % "|p", "rp")
check("3e. pivot='origin' + freeze: reported [0,0,0] == live",
      close(res.get("pivot") or [], [0, 0, 0]) and close(live, [0, 0, 0]),
      "reported %r live %r" % (res.get("pivot"), live))

# --------------------------------------------------------------- phase 4
print("\n=== 4. mesh_cleanup keeps the caller's pivot across its freeze ===",
      flush=True)


def build_dirty():
    ok("new_scene", {"confirm": True})
    py("""
import maya.cmds as cmds
d = cmds.polyCube(name="dirty")[0]
cmds.xform(d, ws=True, t=(4, 0, 0), ro=(0, 30, 0), s=(2, 2, 2))
cmds.xform(d, ws=True, pivots=(0, 5, 0))
True
""", "setup")


build_dirty()
res = ok("mesh_cleanup", {"mesh": "|dirty"})
state = py("import maya.cmds as cmds\n"
           "{'rp': " + RP % "|dirty" + ", 'sp': [round(v, 6) for v in cmds.xform('|dirty', q=True, ws=True, scalePivot=True)],"
           " 't': [round(v, 6) for v in cmds.xform('|dirty', q=True, ws=True, t=True)],"
           " 's': [round(v, 6) for v in cmds.xform('|dirty', q=True, r=True, s=True)],"
           " 'hist': cmds.listHistory('|dirty', pruneDagObjects=True)}", "state")
check("4a. the pivot is still at (0,5,0) after the default freeze",
      close(state["rp"], [0, 5, 0]) and close(state["sp"], [0, 5, 0]),
      "rp %r sp %r" % (state["rp"], state["sp"]))
check("4b. ... and the transform really was frozen (t=0, s=1, no history)",
      close(state["t"], [0, 0, 0]) and close(state["s"], [1, 1, 1]) and not state["hist"],
      "t %r s %r hist %r" % (state["t"], state["s"], state["hist"]))
check("4c. warnings is empty - and honest, because nothing moved",
      res.get("warnings") == [], "warnings=%r" % (res.get("warnings"),))

build_dirty()
ok("mesh_cleanup", {"mesh": "|dirty", "freeze_transforms": False})
state = py("import maya.cmds as cmds\n"
           "{'rp': " + RP % "|dirty" + ", 't': [round(v, 6) for v in cmds.xform('|dirty', q=True, ws=True, t=True)]}", "state")
check("4d. CONTROL freeze_transforms=False: pivot kept AND translate kept",
      close(state["rp"], [0, 5, 0]) and close(state["t"], [4, 0, 0]),
      "rp %r t %r" % (state["rp"], state["t"]))

# --------------------------------------------------------------- summary
ok("new_scene", {"confirm": True})
passed = sum(1 for _, okv, _ in RESULTS if okv)
print("\n%d/%d checks passed" % (passed, len(RESULTS)), flush=True)
for label, okv, detail in RESULTS:
    if not okv:
        print("  FAILED: %s  %s" % (label, detail))
raise SystemExit(0 if passed == len(RESULTS) else 1)
