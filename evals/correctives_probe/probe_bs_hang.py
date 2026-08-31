"""#771: bisect WHICH call makes create_blendshape hang when a deltaMush is
in history. Small direct steps, each timed, each in its own execute_python
so a hang leaves the previous timings on record.

DESTRUCTIVE (new_scene); 9878 only.
"""
from __future__ import annotations

import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import correctives_live as gate  # noqa: E402

py = gate.py
ok = gate.ok


def timed(label, code, timeout_s=240.0):
    t0 = time.time()
    try:
        result = py(code, label, timeout_s=timeout_s)
        print("%-55s %7.1f s  %s" % (label, time.time() - t0,
                                     json.dumps(result)[:90]))
        return result
    except SystemExit:
        print("%-55s TIMED OUT after %.0f s" % (label, time.time() - t0))
        raise


def main():
    if gate.PORT == 9877:
        print("refusing 9877")
        return 2
    with open(gate.POSES_PATH) as fh:
        golem_poses = json.load(fh)
    gate.preflight()
    root = gate.build_fixture(golem_poses)

    timed("duplicate target + move band", """
import maya.cmds as cmds
_dup = cmds.duplicate('|humanoid', name='t1')[0]
cmds.delete(_dup, constructionHistory=True)
cmds.move(0, 0.05, 0, _dup + '.vtx[0:200]', relative=True)
'ok'
""")
    timed("blendShape frontOfChain, NO mush", """
import maya.cmds as cmds
import time
_t0 = time.time()
_bs = cmds.blendShape('t1', '|humanoid', frontOfChain=True, name='probe_bs')[0]
round(time.time() - _t0, 2)
""")
    timed("setAttr weight 1 + xform read, NO mush", """
import maya.cmds as cmds
import time
_t0 = time.time()
cmds.setAttr('probe_bs.w[0]', 1.0)
_f = cmds.xform('|humanoid.vtx[*]', query=True, worldSpace=True,
                translation=True)
cmds.setAttr('probe_bs.w[0]', 0.0)
round(time.time() - _t0, 2)
""")
    timed("add deltaMush (distanceWeight=1)", """
import maya.cmds as cmds
_dm = cmds.deltaMush('|humanoid', smoothingIterations=10)[0]
cmds.setAttr(_dm + '.distanceWeight', 1.0)
_dm
""")
    timed("xform read WITH mush (first eval)", """
import maya.cmds as cmds
import time
_t0 = time.time()
_f = cmds.xform('|humanoid.vtx[*]', query=True, worldSpace=True,
                translation=True)
round(time.time() - _t0, 2)
""")
    timed("setAttr weight 1 + xform read, WITH mush", """
import maya.cmds as cmds
import time
_t0 = time.time()
cmds.setAttr('probe_bs.w[0]', 1.0)
_f = cmds.xform('|humanoid.vtx[*]', query=True, worldSpace=True,
                translation=True)
cmds.setAttr('probe_bs.w[0]', 0.0)
_f2 = cmds.xform('|humanoid.vtx[*]', query=True, worldSpace=True,
                 translation=True)
round(time.time() - _t0, 2)
""")
    timed("second target dup", """
import maya.cmds as cmds
_dup = cmds.duplicate('|humanoid', name='t2')[0]
cmds.delete(_dup, constructionHistory=True)
cmds.move(0, 0.05, 0, _dup + '.vtx[201:400]', relative=True)
'ok'
""")
    timed("blendShape EDIT add target, WITH mush", """
import maya.cmds as cmds
import time
_t0 = time.time()
cmds.blendShape('probe_bs', edit=True,
                target=('|humanoid', 1, 't2', 1.0))
round(time.time() - _t0, 2)
""", timeout_s=240.0)
    timed("third dup for fresh-node test", """
import maya.cmds as cmds
_dup = cmds.duplicate('|humanoid', name='t3')[0]
cmds.delete(_dup, constructionHistory=True)
cmds.move(0, 0.05, 0, _dup + '.vtx[401:600]', relative=True)
'ok'
""")
    timed("NEW blendShape frontOfChain WITH mush (the suspect)", """
import maya.cmds as cmds
import time
_t0 = time.time()
_bs2 = cmds.blendShape('t3', '|humanoid', frontOfChain=True,
                       name='probe_bs2')[0]
round(time.time() - _t0, 2)
""", timeout_s=240.0)
    print("BISECT COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
