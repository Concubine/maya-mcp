"""#771 run-1 diagnosis: (A) WHERE does deltaMush blow an edge to 8.9x on
the crouched humanoid, and does the #668 visible-tear currency (growth >=
10 mm) see it too? (B) is create_blendshape slow with a mush in the chain,
or was run 1's 600 s timeout the #721 idle-IPR wedge?

Reuses correctives_live's fixture builders by import. No renders until the
timing test explicitly makes one. DESTRUCTIVE (new_scene); 9878 only.
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
from live_call import call  # noqa: E402

py = gate.py
ok = gate.ok

DETAIL_PROBE = """
import maya.cmds as cmds
import maya.api.OpenMaya as om
_mesh = '|humanoid'
_shape = cmds.listRelatives(_mesh, shapes=True, fullPath=True)[0]
_flat = cmds.xform(_mesh + '.vtx[*]', query=True, worldSpace=True,
                   translation=True)
_sel = om.MSelectionList()
_sel.add(_shape)
_it = om.MItMeshEdge(_sel.getDagPath(0))
_rows = []
while not _it.isDone():
    _i = _it.index()
    _a = _it.vertexId(0) * 3
    _b = _it.vertexId(1) * 3
    _dx = _flat[_a] - _flat[_b]
    _dy = _flat[_a + 1] - _flat[_b + 1]
    _dz = _flat[_a + 2] - _flat[_b + 2]
    _len = (_dx * _dx + _dy * _dy + _dz * _dz) ** 0.5
    _bind = CORRECTIVES_BIND_EDGES[_i]
    if _bind > 1e-9:
        _rows.append((_len / _bind, _len - _bind, _bind, _i,
                      round(_flat[_a], 3), round(_flat[_a + 1], 3),
                      round(_flat[_a + 2], 3)))
    _it.next()
_rows.sort(reverse=True)
_vis = [r for r in _rows if r[1] >= 0.01]
{'worst_unfiltered': [
    {'ratio': round(r[0], 3), 'growth_mm': round(r[1] * 1000, 1),
     'bind_mm': round(r[2] * 1000, 2), 'edge': r[3],
     'pos': [r[4], r[5], r[6]]} for r in _rows[:8]],
 'worst_visible_ratio': round(_vis[0][0], 3) if _vis else 0.0,
 'worst_visible': [
    {'ratio': round(r[0], 3), 'growth_mm': round(r[1] * 1000, 1),
     'bind_mm': round(r[2] * 1000, 2), 'edge': r[3],
     'pos': [r[4], r[5], r[6]]} for r in _vis[:5]]}
"""


def detail(what):
    return py(DETAIL_PROBE, what, timeout_s=600.0)


def main():
    if gate.PORT == 9877:
        print("refusing 9877")
        return 2
    with open(gate.POSES_PATH) as fh:
        golem_poses = json.load(fh)
    gate.preflight()

    root = gate.build_fixture(golem_poses)
    gate.edge_probe(store=True, what="bind baseline")

    # ---- A: localize the spike -------------------------------------------
    gate.pose(root, golem_poses, "crouch")
    pre = detail("crouch pre-mush detail")
    print("\n== crouch PRE-mush ==")
    print(json.dumps(pre, indent=1))

    results = {}
    combos = [
        ("default it10 s0.5 pin", {"smoothingIterations": 10, "smoothingStep": 0.5, "pinBorderVertices": True}, {}),
        ("it5", {"smoothingIterations": 5, "smoothingStep": 0.5, "pinBorderVertices": True}, {}),
        ("it20", {"smoothingIterations": 20, "smoothingStep": 0.5, "pinBorderVertices": True}, {}),
        ("step0.25", {"smoothingIterations": 10, "smoothingStep": 0.25, "pinBorderVertices": True}, {}),
        ("nopin", {"smoothingIterations": 10, "smoothingStep": 0.5, "pinBorderVertices": False}, {}),
        ("inout1", {"smoothingIterations": 10, "smoothingStep": 0.5, "pinBorderVertices": True},
         {"inwardConstraint": 1.0, "outwardConstraint": 1.0}),
        ("inout0.5", {"smoothingIterations": 10, "smoothingStep": 0.5, "pinBorderVertices": True},
         {"inwardConstraint": 0.5, "outwardConstraint": 0.5}),
        ("distw1", {"smoothingIterations": 10, "smoothingStep": 0.5, "pinBorderVertices": True},
         {"distanceWeight": 1.0}),
    ]
    for tag, kwargs, extra in combos:
        code = (
            "import maya.cmds as cmds\n"
            "_dm = cmds.deltaMush('|humanoid', %s)[0]\n"
            "%s"
            "'ok'"
            % (", ".join("%s=%r" % kv for kv in kwargs.items()),
               "".join("cmds.setAttr(_dm + '.%s', %r)\n" % kv
                       for kv in extra.items())))
        py(code, "mush %s" % tag, timeout_s=600.0)
        after = detail("crouch %s" % tag)
        results[tag] = after
        print("\n== crouch WITH mush [%s] ==" % tag)
        print("unfiltered worst: %s" % json.dumps(after["worst_unfiltered"][:3]))
        print("visible worst ratio: %s" % after["worst_visible_ratio"])
        py("import maya.cmds as cmds\n"
           "cmds.delete(cmds.ls(type='deltaMush'))\n'ok'", "delete mush")

    # ---- B: create_blendshape timing, no ARV then with ARV ---------------
    ok("reset_pose", {"root": root})
    py("import maya.cmds as cmds\n"
       "_dup = cmds.duplicate('|humanoid', name='timing_target')[0]\n"
       "cmds.move(0, 0.05, 0, _dup + '.vtx[0:200]', relative=True)\n'ok'",
       "make timing target")
    py("import maya.cmds as cmds\n"
       "cmds.deltaMush('|humanoid', smoothingIterations=10)\n'ok'",
       "mush for timing")
    t0 = time.time()
    ok("create_blendshape", {"mesh": "|humanoid",
                             "targets": [{"name": "timing_a",
                                          "target_mesh": "timing_target"}]},
       timeout_s=1200.0)
    no_arv = time.time() - t0
    print("\ncreate_blendshape with mush, NO renders yet: %.1f s" % no_arv)

    gate.render("timing_probe")   # opens whatever render_scene leaves behind
    py("import maya.cmds as cmds\n"
       "_dup = cmds.duplicate('|humanoid', name='timing_target2')[0]\n"
       "cmds.delete(_dup, constructionHistory=True)\n"
       "cmds.move(0, 0.05, 0, _dup + '.vtx[0:200]', relative=True)\n'ok'",
       "make timing target 2")
    t0 = time.time()
    ok("create_blendshape", {"mesh": "|humanoid",
                             "targets": [{"name": "timing_b",
                                          "target_mesh": "timing_target2"}]},
       timeout_s=1200.0)
    with_arv = time.time() - t0
    print("create_blendshape with mush, AFTER a render: %.1f s" % with_arv)

    panels = py(
        "import maya.cmds as cmds\n"
        "{'arv_open': bool(cmds.getPanel(scriptType='renderWindowPanel')),\n"
        " 'windows': [w for w in (cmds.lsUI(windows=True) or [])]}",
        "what render UI is open")
    print("render UI state: %s" % json.dumps(panels))
    print("\nPROBE COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
