"""Live gate for redmine #645: the FBX byte reader must agree with Maya.

The reader in maya_plugin/handlers/fbxbytes.py is what maya_export_fbx reports
height_m from, and what every delivery gate measures. Maya is the authority on
what an FBX means, so the only honest check is to hand Maya the same file and
compare - which is exactly what no headless test can do.

#645: the reader composed only T/R/Rp/S and silently dropped RotationOffset,
ScalingOffset, ScalingPivot, PreRotation, PostRotation and the Geometric*
records. Measured here before the fix: clock_tower.fbx read 44.90 where Maya
measures 37.10.

Two parts, because the committed artifacts do not contain every record:

  1. every committed FBX, compared on all six bounds numbers
  2. a scene built HERE to carry the records the artifacts lack - a moved
     rotate pivot with its compensating rotatePivotTranslate, an oriented
     joint (PreRotation), a scaled leaf about a moved scale pivot - exported
     and read back

NOTE the oracle is world-space VERTEX positions, never exactWorldBoundingBox:
that transforms the object-space box, so it over-reports any rotated mesh and
disagreed with a demonstrably correct composition by 1.8% on the golem.

Run:  .venv/Scripts/python.exe evals/fbx_probe_live.py
Exit: 0 all agree, 1 a disagreement, 2 no connection.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import DEFAULT_PORT, call, structured_result  # noqa: E402

from maya_plugin.handlers import fbxbytes  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = DEFAULT_PORT
# Vertex positions round-trip through the file as doubles and through Maya as
# floats; 1e-3 cm is a micron, far below anything a delivery cares about.
TOL_CM = 1e-3

COMMITTED = [
    "evals/structures/clock_tower.fbx",
    "evals/structures/gate.fbx",
    "evals/structures/rotunda.fbx",
    "evals/structures/water_tower.fbx",
    "evals/golem_delivery/golem.fbx",
    "evals/demigol_kit/demigol_kit.fbx",
    "evals/demigol_structures/tower.fbx",
]

IMPORT_AND_MEASURE = """
import maya.cmds as cmds
if not cmds.pluginInfo('fbxmaya', q=True, loaded=True):
    cmds.loadPlugin('fbxmaya')
cmds.file(new=True, force=True)
cmds.currentUnit(linear='cm')
cmds.file(%r, i=True, type='FBX', ignoreVersion=True, pr=True,
          mergeNamespacesOnClash=False, options='fbx')
meshes = cmds.ls(type='mesh', long=True, noIntermediate=True) or []
lo = [float('inf')] * 3
hi = [float('-inf')] * 3
for mesh in meshes:
    pts = cmds.xform(mesh + '.vtx[*]', q=True, ws=True, t=True)
    for c in range(3):
        col = pts[c::3]
        lo[c] = min(lo[c], min(col))
        hi[c] = max(hi[c], max(col))
{'meshes': len(meshes), 'bounds': (lo + hi) if meshes else None}
"""

# Every record the committed files lack, authored deliberately. rotatePivot +
# rotatePivotTranslate is what Maya writes when a pivot is moved with its
# position preserved - #603 put a `pivot` parameter on transform/assemble, so
# this is the common case now, not an exotic one.
BUILD_AND_EXPORT = """
import maya.cmds as cmds
if not cmds.pluginInfo('fbxmaya', q=True, loaded=True):
    cmds.loadPlugin('fbxmaya')
cmds.file(new=True, force=True)
cmds.currentUnit(linear='cm')

# 1. rotate pivot moved off the object, compensated - writes RotationOffset
pivoted = cmds.polyCube(name='probe_pivoted', w=2, h=6, d=2)[0]
cmds.setAttr(pivoted + '.translate', 4, 3, 0)
cmds.setAttr(pivoted + '.rotatePivot', 0, -3, 0)
cmds.setAttr(pivoted + '.rotatePivotTranslate', 1.5, 0.75, -0.5)
cmds.setAttr(pivoted + '.rotate', 0, 0, 35)

# 2. an oriented joint with a mesh under it - writes PreRotation
root = cmds.joint(name='probe_joint_root', position=(-6, 0, 0))
cmds.setAttr(root + '.jointOrient', 15, 0, 40)
child = cmds.polyCube(name='probe_joint_mesh', w=1, h=4, d=1)[0]
cmds.parent(child, root)
cmds.setAttr(child + '.translate', 0, 2, 0)
cmds.setAttr(child + '.rotate', 10, 0, 0)

# 3. a scaled leaf about a moved scale pivot - ScalingPivot stops collapsing
scaled = cmds.polyCube(name='probe_scaled', w=2, h=2, d=2)[0]
cmds.setAttr(scaled + '.translate', 0, 5, 6)
cmds.setAttr(scaled + '.scalePivot', 1, 1, 1)
cmds.setAttr(scaled + '.scale', 3, 0.5, 2)
cmds.setAttr(scaled + '.rotate', 0, 25, 0)

cmds.file(%r, force=True, type='FBX export', exportAll=True)
{'built': [pivoted, root, child, scaled]}
"""


def fail(message):
    print("FAIL: %s" % message)
    sys.exit(1)


def send(code, timeout_s=300.0):
    try:
        response = call("execute_python", {"code": code}, timeout_s, PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)
    if response.get("status") != "ok":
        fail("execute_python: %s" % json.dumps(response.get("error"))[:400])
    return structured_result(response["result"])


def reader_bounds_cm(path):
    """The reader's bounds in centimetres, so Maya's scene units compare."""
    facts = fbxbytes.read_fbx(path)
    lo, hi = fbxbytes.world_vertex_bounds(facts)
    usf = facts.unit_scale_factor or 1.0
    return [v * usf for v in list(lo) + list(hi)], facts


def records_in(facts):
    """Which of the once-dropped records this file actually carries."""
    present = set()
    for node in facts.nodes:
        for label, value, default in (
            ("RotationOffset", node.rotation_offset, fbxbytes.ORIGIN),
            ("ScalingOffset", node.scaling_offset, fbxbytes.ORIGIN),
            ("ScalingPivot", node.scaling_pivot, fbxbytes.ORIGIN),
            ("PreRotation", node.pre_rotation, fbxbytes.ORIGIN),
            ("PostRotation", node.post_rotation, fbxbytes.ORIGIN),
            ("GeometricTranslation", node.geometric_translation, fbxbytes.ORIGIN),
            ("GeometricRotation", node.geometric_rotation, fbxbytes.ORIGIN),
            ("GeometricScaling", node.geometric_scaling, fbxbytes.IDENTITY),
        ):
            if not fbxbytes._is(value, default):
                present.add(label)
    return sorted(present)


def compare(label, path):
    mine, facts = reader_bounds_cm(path)
    out = send(IMPORT_AND_MEASURE % path.replace("\\", "/"))
    if not out["bounds"]:
        fail("%s imported no meshes" % label)
    theirs = out["bounds"]
    worst = max(abs(a - b) for a, b in zip(mine, theirs))
    carries = ", ".join(records_in(facts)) or "none of the #645 records"
    status = "OK  " if worst <= TOL_CM else "DIFF"
    print("%s %-38s %2d meshes, worst axis %9.5f cm  [%s]"
          % (status, label, out["meshes"], worst, carries))
    if worst > TOL_CM:
        print("     reader %s" % ["%.4f" % v for v in mine])
        print("     maya   %s" % ["%.4f" % v for v in theirs])
    return worst <= TOL_CM


def main():
    identity = send("import os\nimport maya.cmds as cmds\n"
                    "{'pid': os.getpid()}", 60.0)
    print("Maya on %d: pid %s\n" % (PORT, identity["pid"]))

    ok = True
    for rel in COMMITTED:
        path = os.path.join(REPO, rel)
        if not os.path.isfile(path):
            fail("missing committed artifact %s" % rel)
        ok &= compare(rel, path)

    built = os.path.join(REPO, "evals", "fbx_probe_live", "authored.fbx")
    os.makedirs(os.path.dirname(built), exist_ok=True)
    send(BUILD_AND_EXPORT % built.replace("\\", "/"))
    if not os.path.isfile(built):
        fail("the authored scene did not export to %s" % built)
    carried = records_in(fbxbytes.read_fbx(built))
    for needed in ("RotationOffset", "PreRotation", "ScalingPivot"):
        if needed not in carried:
            fail("the authored scene was meant to carry %s and does not (%s) - "
                 "the arm proves nothing until it does" % (needed, carried))
    ok &= compare("evals/fbx_probe_live/authored.fbx (built here)", built)

    print()
    if not ok:
        print("the reader disagrees with Maya - see the pairs above")
        sys.exit(1)
    print("reader and Maya agree on every file, to within %g cm" % TOL_CM)


if __name__ == "__main__":
    main()
