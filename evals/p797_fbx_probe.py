"""#814 follow-up probe: what fbxmaya actually does on import, so the .fbx
retarget route can be fixed on evidence rather than on the two assumptions the
first probe refuted (the file command's namespace flag is honoured; the scene
time unit reflects the file's rate after import).

  P1. the default FBXImportMode
  P2. FBXImportSetMayaFrameRate -v true: does the unit follow the file, and
      do the keys land on integer frames?
  P3. import into a scene holding a SAME-NAMED rig, exactly as the handler
      does it: which nodes appear, and does the rig itself gain keys?
  P4. the same with FBXImportMode -v add set explicitly first.
  P5. what the file itself says: FBXRead-free - the take's stop time and
      the frame count implied by the 60fps bake.

No captures. Agent Maya on 9878 only, repo cwd.
Run:  MAYA_MCP_PORT=9878 python evals/p797_fbx_probe.py
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
import humanoid_live  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877:
    raise SystemExit("refusing the user's Maya")
OUT = os.path.join(_HERE, "p797_probes_814")
FBX = os.path.join(OUT, "walk_take.fbx").replace("\\", "/")
assert os.path.exists(FBX), "run p797_probes.py part C first - it writes the take"
FINDINGS = {}


def ok(command, params, timeout_s=600.0):
    r = call(command, params, timeout_s=timeout_s, port=PORT)
    if r.get("status") != "ok":
        raise SystemExit("%s failed: %s" % (command, json.dumps(r.get("error"), indent=1)))
    return r.get("result") or {}


def py(code, what="r", timeout_s=600.0):
    return structured_result(ok("execute_python", {"code": textwrap.dedent(code).strip()}, timeout_s), what)


def show(label, value):
    FINDINGS[label] = value
    with open(os.path.join(OUT, "fbx_findings.json"), "w", encoding="utf-8") as fh:
        json.dump(FINDINGS, fh, indent=1, default=str)
    print("\n--- %s ---" % label)
    print(json.dumps(value, indent=1, sort_keys=True, default=str))


ident = py("import os, maya_plugin\n{'file': maya_plugin.__file__, 'cwd': os.getcwd()}", "identity")
print("live plugin:", ident)

show("P1 default FBXImportMode + frame-rate flag", py('''
import maya.cmds as cmds, maya.mel as mel
cmds.loadPlugin("fbxmaya", quiet=True)
{"FBXImportMode": mel.eval("FBXImportMode -q"),
 "FBXImportSetMayaFrameRate": mel.eval("FBXImportSetMayaFrameRate -q"),
 "FBXImportMergeAnimationLayers": mel.eval("FBXImportMergeAnimationLayers -q"),
 "unit": cmds.currentUnit(q=True, time=True)}
'''))

show("P2 FBXImportSetMayaFrameRate true, empty film scene", py('''
import maya.cmds as cmds, maya.mel as mel
cmds.file(new=True, force=True); cmds.currentUnit(time="film")
mel.eval("FBXImportSetMayaFrameRate -v true")
cmds.file(%r, i=True, type="FBX", ignoreVersion=True, preserveReferences=False)
mel.eval("FBXImportSetMayaFrameRate -v false")
js = cmds.ls(type="joint"); t = cmds.keyframe(js, q=True) or []
frac = sum(1 for v in t if abs(v - round(v)) > 1e-6)
{"unit_after": cmds.currentUnit(q=True, time=True), "range": [min(t), max(t)], "keys": len(t),
 "fractional_keys": frac, "joints": len(js)}
''' % FBX))

show("P2b the flag left at its default (false), empty film scene", py('''
import maya.cmds as cmds
cmds.file(new=True, force=True); cmds.currentUnit(time="film")
cmds.file(%r, i=True, type="FBX", ignoreVersion=True, preserveReferences=False)
js = cmds.ls(type="joint"); t = cmds.keyframe(js, q=True) or []
frac = sum(1 for v in t if abs(v - round(v)) > 1e-6)
{"unit_after": cmds.currentUnit(q=True, time=True), "range": [min(t), max(t)], "keys": len(t), "fractional_keys": frac}
''' % FBX))

ok("new_scene", {"confirm": True})
rig = ok("create_skeleton", {"joints": humanoid_live.JOINTS})["root"]
show("P3 import (handler's exact call) into a scene holding the same-named rig", py('''
import maya.cmds as cmds, maya.mel as mel
before = set(cmds.ls(long=True))
keyed_before = cmds.keyframe(%r, q=True, hierarchy="below") or []
cmds.namespace(add="probe_ns")
cmds.file(%r, i=True, namespace="probe_ns", type="FBX", ignoreVersion=True, preserveReferences=False)
after = set(cmds.ls(long=True))
new = sorted(after - before)
keyed_after = cmds.keyframe(%r, q=True, hierarchy="below") or []
{"mode": mel.eval("FBXImportMode -q"), "new_nodes": len(new), "new_joints": [n for n in new if cmds.nodeType(n) == "joint"][:6],
 "new_types": sorted(set(cmds.nodeType(n) for n in new)),
 "rig_keys_before": len(keyed_before), "rig_keys_after": len(keyed_after),
 "namespaces": cmds.namespaceInfo(listOnlyNamespaces=True), "unit": cmds.currentUnit(q=True, time=True),
 "rig_range": [min(keyed_after), max(keyed_after)] if keyed_after else None}
''' % (rig, FBX, rig)))

ok("new_scene", {"confirm": True})
rig = ok("create_skeleton", {"joints": humanoid_live.JOINTS})["root"]
show("P4 FBXImportMode -v add, same-named rig", py('''
import maya.cmds as cmds, maya.mel as mel
before = set(cmds.ls(long=True))
mel.eval("FBXImportMode -v add")
cmds.namespace(add="probe_ns")
cmds.file(%r, i=True, namespace="probe_ns", type="FBX", ignoreVersion=True, preserveReferences=False)
after = set(cmds.ls(long=True)); new = sorted(after - before)
keyed_after = cmds.keyframe(%r, q=True, hierarchy="below") or []
new_joints = [n for n in new if cmds.nodeType(n) == "joint"]
{"new_nodes": len(new), "new_joints": new_joints[:6], "n_new_joints": len(new_joints),
 "rig_keys_after": len(keyed_after), "namespaces": cmds.namespaceInfo(listOnlyNamespaces=True),
 "new_joint_keys": len(cmds.keyframe(new_joints, q=True) or []) if new_joints else 0}
''' % (FBX, rig)))

ok("new_scene", {"confirm": True})
rig = ok("create_skeleton", {"joints": humanoid_live.JOINTS})["root"]
show("P5 FBXImportMode add + namespace via cmds.namespace(set=) before the import", py('''
import maya.cmds as cmds, maya.mel as mel
before = set(cmds.ls(long=True))
mel.eval("FBXImportMode -v add")
cmds.namespace(add="probe_ns"); cmds.namespace(set="probe_ns")
try:
    cmds.file(%r, i=True, type="FBX", ignoreVersion=True, preserveReferences=False)
finally:
    cmds.namespace(set=":")
after = set(cmds.ls(long=True)); new = sorted(after - before)
new_joints = [n for n in new if cmds.nodeType(n) == "joint"]
{"new_nodes": len(new), "new_joints": new_joints[:6], "n_new_joints": len(new_joints),
 "rig_keys_after": len(cmds.keyframe(%r, q=True, hierarchy="below") or []),
 "new_joint_keys": len(cmds.keyframe(new_joints, q=True) or []) if new_joints else 0}
''' % (FBX, rig)))

ok("new_scene", {"confirm": True})
print("\nfindings ->", os.path.join(OUT, "fbx_findings.json"))
