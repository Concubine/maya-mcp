"""#805 PROBE - a measurement, not a fix.

Does  cmds.ls(cmds.listHistory(shape, pruneDagObjects=True) or [], type=T)
go SCENE-WIDE on a history-less mesh?  Six call sites (export.py x2,
blendshape.py x2, rigging.py x2) are written that way.  Hypothesis from #799:
pruneDagObjects strips the shape itself, a frozen mesh leaves an EMPTY list,
Maya flattens it to no operands, and a bare `ls -type T` answers scene-wide.

Run:  MAYA_MCP_PORT=9878 MAYA_MCP_EXPECT_PID=<pid> python evals/listhistory_probe_805.py
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

cmds.file(new=True, force=True)
out = {}

# A: frozen cube, history deleted -> history-less mesh shape.
frozen = cmds.polyCube(name="slab")[0]
cmds.delete(frozen, constructionHistory=True)
frozen_shape = cmds.listRelatives(frozen, shapes=True, fullPath=True)[0]

# B: an unrelated mesh carrying a REAL deltaMush, a skinCluster, a blendShape.
far = cmds.polySphere(name="far")[0]
far_shape = cmds.listRelatives(far, shapes=True, fullPath=True)[0]
mush = cmds.deltaMush(far, name="far_relax")[0]
j = cmds.joint(name="far_j")
skin = cmds.skinCluster(j, far, name="far_skin")[0]
tgt = cmds.polySphere(name="far_tgt")[0]
bs = cmds.blendShape(tgt, far, name="far_bs")[0]

out["setup"] = {"frozen_shape": frozen_shape, "far_shape": far_shape,
                "mush": mush, "skin": skin, "bs": bs}

# 1. What listHistory returns for the history-less shape.
h = cmds.listHistory(frozen_shape, pruneDagObjects=True)
out["1_listHistory_frozen_pruned"] = {"repr": repr(h), "type": type(h).__name__}
out["1b_listHistory_frozen_unpruned"] = repr(cmds.listHistory(frozen_shape))
out["1c_listHistory_far_pruned"] = repr(cmds.listHistory(far_shape, pruneDagObjects=True))

# 2. ls with an EMPTY list positional.
def rec(label, fn):
    try:
        out[label] = {"repr": repr(fn())}
    except Exception as e:  # noqa: BLE001 - the measurement includes failures
        out[label] = {"raised": "%s: %s" % (type(e).__name__, e)}

rec("2a_ls_emptylist_deltaMush", lambda: cmds.ls([], type="deltaMush"))
rec("2b_ls_emptylist_skinCluster", lambda: cmds.ls([], type="skinCluster"))
rec("2c_ls_emptylist_blendShape", lambda: cmds.ls([], type="blendShape"))
rec("2d_ls_none_deltaMush", lambda: cmds.ls(None, type="deltaMush"))
rec("2e_ls_emptytuple_deltaMush", lambda: cmds.ls((), type="deltaMush"))
rec("2f_ls_noargs_deltaMush", lambda: cmds.ls(type="deltaMush"))

# 3. The real expression, all three types, on the history-less shape.
expr = lambda t: cmds.ls(cmds.listHistory(frozen_shape, pruneDagObjects=True) or [], type=t)
rec("3a_real_expr_frozen_deltaMush", lambda: expr("deltaMush"))
rec("3b_real_expr_frozen_skinCluster", lambda: expr("skinCluster"))
rec("3c_real_expr_frozen_blendShape", lambda: expr("blendShape"))

# 3'. Control: the same expression on the mesh that HAS the deformers.
expr_far = lambda t: cmds.ls(cmds.listHistory(far_shape, pruneDagObjects=True) or [], type=t)
rec("3d_real_expr_far_deltaMush", lambda: expr_far("deltaMush"))
rec("3e_real_expr_far_skinCluster", lambda: expr_far("skinCluster"))
rec("3f_real_expr_far_blendShape", lambda: expr_far("blendShape"))

# 4. A mesh with history but NO deformer of the asked type (polyCube left
#    unfrozen): is a non-empty, non-matching list scoped, as expected?
plain = cmds.polyCube(name="plain")[0]
plain_shape = cmds.listRelatives(plain, shapes=True, fullPath=True)[0]
out["4a_listHistory_plain_pruned"] = repr(cmds.listHistory(plain_shape, pruneDagObjects=True))
rec("4b_real_expr_plain_deltaMush",
    lambda: cmds.ls(cmds.listHistory(plain_shape, pruneDagObjects=True) or [], type="deltaMush"))

# 5. Candidate fix shape: skip ls when history is empty.
def scoped(shape, t):
    hist = cmds.listHistory(shape, pruneDagObjects=True) or []
    return cmds.ls(hist, type=t) if hist else []
rec("5a_scoped_frozen_deltaMush", lambda: scoped(frozen_shape, "deltaMush"))
rec("5b_scoped_far_deltaMush", lambda: scoped(far_shape, "deltaMush"))

out["scene_wide"] = {"deltaMush": cmds.ls(type="deltaMush"),
                     "skinCluster": cmds.ls(type="skinCluster"),
                     "blendShape": cmds.ls(type="blendShape")}
out["maya_version"] = cmds.about(version=True)
json.dumps(out)
'''


def main() -> int:
    frame = call("execute_python", {"code": CODE, "timeout_s": 60},
                 timeout_s=90.0, port=PORT)
    if frame.get("status") != "ok":
        print(json.dumps(frame, indent=1))
        return 1
    res = frame["result"]
    if res.get("traceback"):
        print(res["traceback"])
        return 1
    data = json.loads(eval(res["result_repr"]))  # repr of a JSON string
    out_dir = os.path.join(_HERE, "listhistory_probe_805")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "readings.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    for k in sorted(data):
        print("%-36s %s" % (k, json.dumps(data[k])))
    print("written", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
