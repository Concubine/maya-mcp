"""#803 PROBE - measure before designing (the #796 rule).

Two Maya claims the ticket rests on, plus the two candidate fix orders:
  1. makeIdentity(apply, t/r/s) RESETS an off-origin pivot to the world origin.
  2. polyUnite(ch=False, name=<a consumed input's own name>) - what name does
     the result get, and is the input's name free afterwards for a rename?
  3. Freeze FIRST, place the pivot AFTER: does the placed pivot survive, and
     does xform -q -ws -rp answer what was written?
  4. mesh_cleanup shape: a caller-placed pivot, freeze, re-place at the old
     world point - does it come back exactly?

Run:  MAYA_MCP_PORT=9878 MAYA_MCP_EXPECT_PID=<pid> python evals/combine_pivot_probe_803.py
Refuses 9877 (calls new_scene).
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
from live_call import call  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
    print("refusing 9877 (the user's Maya): this probe calls new_scene",
          file=sys.stderr)
    raise SystemExit(2)

CODE = r'''
import json
import maya.cmds as cmds

out = {}
def rp(n): return [round(v, 6) for v in cmds.xform(n, q=True, ws=True, rotatePivot=True)]
def sp(n): return [round(v, 6) for v in cmds.xform(n, q=True, ws=True, scalePivot=True)]
def tr(n): return [round(v, 6) for v in cmds.xform(n, q=True, ws=True, translation=True)]

# ---- 1. freeze resets the pivot? (combine's current order: place, then freeze)
cmds.file(new=True, force=True)
a = cmds.polyCube(name="a")[0]; cmds.xform(a, ws=True, t=(1, 2, 3))
b = cmds.polyCube(name="b")[0]; cmds.xform(b, ws=True, t=(3, 4, 5))
u = cmds.polyUnite([a, b], ch=False, name="p")[0]
bb = cmds.exactWorldBoundingBox(u)
centre = [(bb[i] + bb[i + 3]) / 2.0 for i in range(3)]
cmds.xform(u, ws=True, pivots=tuple(centre))
out["1_centre_written"] = [round(v, 6) for v in centre]
out["1_rp_after_place_before_freeze"] = rp(u)
cmds.makeIdentity(u, apply=True, translate=True, rotate=True, scale=True)
out["1_rp_after_freeze"] = rp(u)
out["1_sp_after_freeze"] = sp(u)
out["1_translate_after_freeze"] = tr(u)

# ---- 3. freeze FIRST, then place (assemble.py's order)
cmds.file(new=True, force=True)
a = cmds.polyCube(name="a")[0]; cmds.xform(a, ws=True, t=(1, 2, 3))
b = cmds.polyCube(name="b")[0]; cmds.xform(b, ws=True, t=(3, 4, 5))
u = cmds.polyUnite([a, b], ch=False, name="p")[0]
cmds.makeIdentity(u, apply=True, translate=True, rotate=True, scale=True)
bb = cmds.exactWorldBoundingBox(u)
centre = [(bb[i] + bb[i + 3]) / 2.0 for i in range(3)]
cmds.xform(u, ws=True, pivots=tuple(centre))
out["3_centre_written"] = [round(v, 6) for v in centre]
out["3_rp_after_freeze_then_place"] = rp(u)
out["3_sp_after_freeze_then_place"] = sp(u)
out["3_translate"] = tr(u)
# and a second freeze after placing (if anyone re-freezes) resets again?
cmds.makeIdentity(u, apply=True, translate=True, rotate=True, scale=True)
out["3b_rp_after_second_freeze"] = rp(u)

# ---- 2. polyUnite with a consumed input's own name
cmds.file(new=True, force=True)
body = cmds.polyCube(name="body")[0]
arm = cmds.polyCube(name="arm")[0]; cmds.xform(arm, ws=True, t=(2, 0, 0))
res = cmds.polyUnite([body, arm], ch=False, name="body")
out["2_polyUnite_returned"] = res
out["2_exists_body"] = cmds.objExists("body")
out["2_ls_body_long"] = cmds.ls("body", long=True)
out["2_ls_all_transforms"] = cmds.ls(type="transform")
out["2_result_nodeType"] = cmds.nodeType(res[0])
# can the result be renamed to the consumed name now?
try:
    renamed = cmds.rename(res[0], "body")
    out["2_rename_to_body"] = {"returned": renamed, "long": cmds.ls(renamed, long=True)}
except Exception as e:
    out["2_rename_to_body"] = {"raised": "%s: %s" % (type(e).__name__, e)}

# 2c. same with ch=True (for the record: does the name differ when inputs survive?)
cmds.file(new=True, force=True)
body = cmds.polyCube(name="body")[0]
arm = cmds.polyCube(name="arm")[0]
res = cmds.polyUnite([body, arm], ch=True, name="body")
out["2c_ch_true_returned"] = res
out["2c_ch_true_transforms"] = cmds.ls(type="transform")

# 2d. the current handler order: unique_name BEFORE unite would pick body_001;
#     what does polyUnite give when asked for a FREE name while inputs exist?
cmds.file(new=True, force=True)
body = cmds.polyCube(name="body")[0]
arm = cmds.polyCube(name="arm")[0]
res = cmds.polyUnite([body, arm], ch=False, name="fresh")
out["2d_free_name_returned"] = res

# ---- 4. mesh_cleanup shape: caller-placed pivot survives a freeze + re-place?
cmds.file(new=True, force=True)
d = cmds.polyCube(name="dirty")[0]
cmds.xform(d, ws=True, t=(4, 0, 0), ro=(0, 30, 0), s=(2, 2, 2))
cmds.xform(d, ws=True, pivots=(0, 5, 0))
out["4_rp_before"] = rp(d)
before = cmds.xform(d, q=True, ws=True, rotatePivot=True)
cmds.delete(d, constructionHistory=True)
cmds.makeIdentity(d, apply=True, translate=True, rotate=True, scale=True)
out["4_rp_after_freeze"] = rp(d)
cmds.xform(d, ws=True, pivots=tuple(before))
out["4_rp_after_replace"] = rp(d)
out["4_sp_after_replace"] = sp(d)
out["4_translate_after"] = tr(d)
# does the re-placed pivot survive a further translate (i.e. is it a real local pivot)?
cmds.xform(d, ws=True, t=(1, 1, 1), relative=True)
out["4b_rp_after_move"] = rp(d)

# ---- 5. freeze with an off-origin pivot: does it leave translate = old pivot? (rotatePivotTranslate etc.)
cmds.file(new=True, force=True)
e = cmds.polyCube(name="e")[0]
cmds.xform(e, ws=True, t=(4, 0, 0))
cmds.xform(e, ws=True, pivots=(4, 5, 0))
cmds.makeIdentity(e, apply=True, translate=True, rotate=True, scale=True)
out["5_attrs_after_freeze"] = {k: [round(v, 6) for v in cmds.getAttr(e + "." + k)[0]]
                               for k in ("translate", "rotatePivot", "scalePivot",
                                         "rotatePivotTranslate", "scalePivotTranslate")}
out["maya_version"] = cmds.about(version=True)
json.dumps(out)
'''


def main() -> int:
    frame = call("execute_python", {"code": CODE, "timeout_s": 60},
                 timeout_s=90.0, port=PORT)
    if frame.get("status") != "ok":
        print(json.dumps(frame, indent=1)); return 1
    res = frame["result"]
    if res.get("traceback"):
        print(res["traceback"]); return 1
    data = json.loads(eval(res["result_repr"]))
    out_dir = os.path.join(_HERE, "combine_pivot_probe_803")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "readings.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    for k in sorted(data):
        print("%-34s %s" % (k, json.dumps(data[k])))
    print("written", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
