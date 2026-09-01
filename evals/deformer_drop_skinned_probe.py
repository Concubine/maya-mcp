"""#767/M5, part 2: does a deformer survive export on a SKINNED mesh?

deformer_drop_probe.py measured five deformers on UNSKINNED meshes and found
every one of them travels: FBX writes the evaluated vertices, so the deformed
shape ships as static geometry. That result cannot be the whole story, because
#771 measured the opposite for a deltaMush - with and without exports came out
byte-identical - and export.py warns on that basis.

The difference is skinning, and it decides whether the warning needs
extending. A skinned mesh does not ship its evaluated shape: FBX stores the
BIND POSE plus weights, and the consumer re-evaluates. Anything downstream of
the skinCluster - which is exactly where apply_delta_mush puts its node, and
apply_delta_mush REFUSES an unskinned mesh - has no way to travel.

This measures that directly: pose a skinned cylinder, record its shape with
and without the mush, export with skins, reimport, re-pose to the same angle,
and see which of the two shapes came back.

DESTRUCTIVE: calls new_scene. Port 9878 (agent Maya).
Run:  $env:MAYA_MCP_PORT='9878'; python evals/deformer_drop_skinned_probe.py --build
"""

from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402

OUT_DIR = os.path.join(_HERE, "deformer_drop_probe")

SIG = (
    "def _sig(mesh):\n"
    "    _p = cmds.xform(mesh + '.vtx[*]', query=True, worldSpace=True,\n"
    "                    translation=True)\n"
    "    _v = [_p[i:i+3] for i in range(0, len(_p), 3)]\n"
    "    _n = float(len(_v))\n"
    "    _c = [sum(a[i] for a in _v) / _n for i in range(3)]\n"
    "    _d = [[a[i] - _c[i] for i in range(3)] for a in _v]\n"
    "    _rms = (sum(x*x + y*y + z*z for x, y, z in _d) / _n) ** 0.5\n"
    "    return {'norm': [[round(x/_rms, 5), round(y/_rms, 5),\n"
    "                      round(z/_rms, 5)] for x, y, z in _d]}\n"
    "def _delta(a, b):\n"
    "    _pa, _pb = a['norm'], b['norm']\n"
    "    if len(_pa) != len(_pb):\n"
    "        return None\n"
    "    return round(max(sum((x - y) ** 2 for x, y in zip(u, v)) ** 0.5\n"
    "                     for u, v in zip(_pa, _pb)), 6)\n"
)


def run(code, label, timeout_s=300.0):
    res = call("execute_python", {"code": code}, timeout_s=timeout_s)
    if res.get("status") != "ok":
        print("FATAL %s: %r" % (label, res.get("error")))
        sys.exit(1)
    result = res.get("result") or {}
    if result.get("traceback"):
        print("FATAL %s raised in Maya:\n%s" % (label, result["traceback"][-900:]))
        sys.exit(1)
    return structured_result(result, label)


def main():
    if "--build" not in sys.argv:
        print(__doc__)
        return 1
    os.makedirs(OUT_DIR, exist_ok=True)
    fbx = os.path.join(OUT_DIR, "skinned.fbx").replace("\\", "/")

    call("new_scene", {"confirm": True}, timeout_s=180.0)

    built = run(SIG + """
m = cmds.polyCylinder(name='skinned_case', r=0.5, h=6, sx=12, sy=12)[0]
cmds.select(clear=True)
j1 = cmds.joint(p=(0, -3, 0), name='jroot')
j2 = cmds.joint(p=(0, 0, 0), name='jmid')
j3 = cmds.joint(p=(0, 3, 0), name='jtip')
# The export unit gate refuses InheritType 2 (#703): Unity compounds the
# unit conversion once per joint level. create_skeleton authors these off;
# a hand-built chain has to be told.
for _j in (j1, j2, j3):
    cmds.setAttr(_j + '.segmentScaleCompensate', 0)
cmds.skinCluster(j1, j2, j3, m, toSelectedBones=True)
cmds.setAttr(j2 + '.rotateZ', 40)
cmds.refresh()
_shapes = {}
_shapes['skin_only'] = _sig(m)
_d = cmds.deltaMush(m)[0]
cmds.setAttr(_d + '.smoothingIterations', 20)
cmds.setAttr(_d + '.distanceWeight', 1.0)
cmds.refresh()
_shapes['skin_mush'] = _sig(m)
out = {'mush_changed_posed_shape': _delta(_shapes['skin_only'],
                                          _shapes['skin_mush'])}
out
""", "build skinned + mush")
    moved = built["mush_changed_posed_shape"]
    print("the mush changed the POSED shape by: %s" % moved)
    if not moved or moved < 1e-3:
        print("INCONCLUSIVE: the mush did not visibly change the posed shape, "
              "so nothing can be concluded about whether it survives.")
        return 1

    exp = call("export_fbx", {
        # Both the chain AND the mesh: the mesh is a sibling of the joint
        # root, not a child, so exporting the root alone ships a skeleton
        # with nothing bound to it.
        "path": fbx, "nodes": ["|jroot", "|skinned_case"],
        "metres_per_unit": 1.0,
        "include_skins": True, "include_animation": False}, timeout_s=600.0)
    print("export status: %s" % exp.get("status"))
    warnings = (exp.get("result") or {}).get("warnings") or []
    for w in warnings:
        print("  warn: %s" % w[:160])
    if exp.get("status") != "ok":
        print("export error: %s" % str(exp.get("error"))[:500])
        return 1

    after = run(SIG + """
cmds.file(%r, i=True, type='FBX', ignoreVersion=True,
          mergeNamespacesOnClash=True, namespace=':')
_new = [t for t in cmds.ls(type='transform')
        if t.split('|')[-1].split(':')[-1].startswith('skinned_case')][-1]
_mid = [j for j in cmds.ls(type='joint')
        if 'jmid' in j.split('|')[-1]][-1]
cmds.setAttr(_mid + '.rotateZ', 40)
cmds.refresh()
out = {'imported': _new,
       'vs_skin_only': _delta(_shapes['skin_only'], _sig(_new)),
       'vs_skin_mush': _delta(_shapes['skin_mush'], _sig(_new))}
out
""" % fbx, "reimport skinned", timeout_s=600.0)

    to_plain = after["vs_skin_only"]
    to_mush = after["vs_skin_mush"]
    print("\nreimported %s, re-posed to the same 40 deg" % after["imported"])
    print("  distance to the SKIN-ONLY shape : %s" % to_plain)
    print("  distance to the SKIN+MUSH shape : %s" % to_mush)
    # A verdict is only allowed when the reimport actually LANDS on one of
    # the two candidates. Measured 2026-09-01: 0.2126 vs 0.1889 - the
    # round-trip shape sits far from both, so the re-pose (bind pose and
    # joint orientation do not survive FBX unchanged) dominates the signal
    # and the 12% gap between two large numbers discriminates nothing.
    # Reporting "travelled" off that gap would be the blind measurement this
    # probe exists to avoid, so it reports its own failure instead.
    near = min(to_plain or 9.0, to_mush or 9.0)
    if near > 0.05:
        verdict = ("INCONCLUSIVE - the reimport matches neither shape "
                   "(nearest %.4f); the re-pose does not reproduce the "
                   "original closely enough to tell the two apart" % near)
    elif (to_plain or 9) < (to_mush or 9):
        verdict = "MUSH LOST - the consumer gets the unrelaxed skin"
    else:
        verdict = "MUSH TRAVELLED"
    print("\nVERDICT: %s" % verdict)

    with open(os.path.join(OUT_DIR, "skinned_report.json"), "w") as handle:
        json.dump({"mush_changed_posed_shape": moved,
                   "vs_skin_only": to_plain, "vs_skin_mush": to_mush,
                   "verdict": verdict, "export_warnings": warnings},
                  handle, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
