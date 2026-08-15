"""Live gate for maya-mcp #634: does the reported unit predict the ARTIFACT?

`export_metres_per_unit` is a claim about a file that does not exist yet. The
whole lesson of #629 is that in-Maya numbers cannot see the exporter, so a gate
that only compares `get_scene_graph`'s block against `cmds.currentUnit` would
be checking one query against another and proving nothing.

So this measures the thing itself. Twice, with the SAME authored number:

    cm scene  -> build a 3-unit cube -> export -> FBX vertices should span 3.0
    m  scene  -> build a 3-unit cube -> export -> FBX vertices should span 300.0

and requires `export_metres_per_unit` to have predicted each span in advance.
The second half is the #629 defect reproduced deliberately, which is the only
way to show the field discriminates rather than always saying what we want.

Also checks the plumbing either side of that: new_scene FORCES the unit (from a
session deliberately dirtied to "m"), and get_scene_graph / get_object_info both
report a block agreeing with Maya.

DESTRUCTIVE: calls new_scene, so the current scene is discarded. An auto
checkpoint is taken by new_scene itself and its id is printed.

Defaults to port 9877, not live_call.py's 9878, for the same reason
evals/pivot_live.py and evals/assemble_pivots_live.py do: prove it in the
session the USER is looking at. Do not "fix" it back to 9878.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fbx_probe  # noqa: E402  - sibling import, see evals/delivery_units.py
import maya_export  # noqa: E402  - the one place the export preamble lives
from evals.live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9877"))

CUBE = "unitGateCube"
CUBE_SIDE = 3.0  # authored number, identical in both scenes - that is the point
TOL = 1e-3

CHECKS = []


def check(label, passed, detail=""):
    CHECKS.append((bool(passed), label))
    print("%s %s%s" % ("PASS" if passed else "FAIL", label,
                       ("  [%s]" % detail) if detail else ""))
    return bool(passed)


def _py(code, what):
    """Run code in Maya and return its result, raising if it did not come back."""
    response = call("execute_python", {"code": code}, port=PORT)
    if response.get("error"):
        raise RuntimeError("%s: %s" % (what, response["error"]))
    return structured_result(response["result"], what)


def refresh_live_handlers():
    """Rebind the handlers this gate exercises from the DEPLOYED source.

    A running Maya holds the modules it imported at startup, so a fresh deploy
    is invisible to it (maya-mcp #604, and the reason the deployed copy going
    stale has its own memory entry). Every other live eval that touches changed
    handler code does this same rebind; without it this script would measure
    yesterday's plugin and report it as today's.
    """
    return _py(
        "import importlib\n"
        "from maya_plugin import maya_mcp_plugin as _plugin\n"
        "from maya_plugin.handlers import units as _units\n"
        "from maya_plugin.handlers import scene as _scene\n"
        "from maya_plugin.handlers import objinfo as _objinfo\n"
        "from maya_plugin.handlers import session as _session\n"
        "for _m in (_units, _scene, _objinfo, _session):\n"
        "    importlib.reload(_m)\n"
        "_h = _plugin._active_server._dispatcher._handlers\n"
        "_h['new_scene'] = _session.new_scene\n"
        "_h['get_scene_graph'] = _scene.get_scene_graph\n"
        "_h['get_object_info'] = _objinfo.get_object_info\n"
        "sorted(_units._CM_PER_UNIT)",
        "rebind handlers from the deployed source",
    )


def scene_unit():
    return _py("import maya.cmds as cmds\ncmds.currentUnit(q=True, linear=True)",
               "query the scene's linear unit")


def build_and_export(path):
    """One cube of CUBE_SIDE units, exported through the delivery path."""
    _py("import maya.cmds as cmds\n"
        "cmds.polyCube(w=%(s)g, h=%(s)g, d=%(s)g, name='%(n)s', ch=False)\n"
        "cmds.select('%(n)s', replace=True)\n"
        "'built'" % {"s": CUBE_SIDE, "n": CUBE},
        "build the probe cube")
    # The delivery preamble verbatim, so this gate cannot drift from what the
    # generators actually ship through.
    _py("EXPORT_SCALE_FACTOR = %g\n%s\n"
        "cmds.select('%s', replace=True)\n"
        "cmds.file(%r, force=True, options='v=0', type='FBX export', pr=True, es=True)\n"
        "'exported'"
        % (maya_export.EXPORT_SCALE_FACTOR, maya_export.EXPORT_PREAMBLE, CUBE,
           path.replace("\\", "/")),
        "export the probe cube")
    return fbx_probe.read_fbx(path)


def span_of(facts):
    """Largest vertex extent in the file, on any axis.

    `facts.meshes` holds flat (x,y,z,x,y,z,...) tuples, one per mesh - the same
    layout evals/delivery_units.py walks.
    """
    best = 0.0
    for verts in facts.meshes:
        for axis in range(3):
            values = verts[axis::3]
            if values:
                best = max(best, max(values) - min(values))
    return best


def measure(unit, tmpdir):
    """Set `unit`, build, export, and check the block predicted the file."""
    _py("import maya.cmds as cmds\ncmds.currentUnit(linear=%r)\n'set'" % unit,
        "set the scene to %r" % unit)
    graph = call("get_scene_graph", {"max_objects": 1}, port=PORT)
    if graph.get("error"):
        raise RuntimeError("get_scene_graph: %s" % graph["error"])
    block = graph["result"].get("units")
    if not block:
        check("get_scene_graph reports a units block (%s)" % unit, False,
              "absent - is the live plugin stale?")
        return
    check("get_scene_graph's unit agrees with Maya (%s)" % unit,
          block["linear_unit"] == unit, block["linear_unit"])

    predicted = block["export_metres_per_unit"]
    path = os.path.join(tmpdir, "unit_gate_%s.fbx" % unit)
    facts = build_and_export(path)
    measured = span_of(facts)
    expected = CUBE_SIDE * predicted
    check("a %g-unit cube in a %r scene exports spanning %g"
          % (CUBE_SIDE, unit, expected),
          abs(measured - expected) <= TOL * max(1.0, expected),
          "predicted %g x %g = %g, file has %g"
          % (CUBE_SIDE, predicted, expected, measured))
    _py("import maya.cmds as cmds\ncmds.delete('%s')\n'deleted'" % CUBE,
        "delete the probe cube")


def main() -> int:
    import tempfile

    refresh_live_handlers()

    # Dirty the session exactly as a stray eval would leave it, so the forcing
    # below is proved against a scene that really was wrong.
    _py("import maya.cmds as cmds\ncmds.currentUnit(linear='m')\n'dirtied'",
        "dirty the session to metres")

    response = call("new_scene", {"confirm": True}, port=PORT)
    if response.get("error"):
        print("FAIL new_scene: %s" % response["error"])
        return 1
    result = response["result"]
    print("new_scene pre_checkpoint: %s" % result.get("pre_checkpoint"))
    block = result.get("units")
    check("new_scene reports the unit it set", bool(block), str(block))
    if block:
        check("new_scene forced the metre-true unit",
              block["linear_unit"] == "cm"
              and block["export_metres_per_unit"] == 1.0, str(block))
    check("Maya really is in that unit, not just the response",
          scene_unit() == "cm", scene_unit())

    tmpdir = tempfile.mkdtemp(prefix="maya_mcp_unit_gate_")
    try:
        # cm first: the convention, and the only one that should ship.
        measure("cm", tmpdir)
        # Then the defect, on purpose. If this half "passes" at 3.0 the field
        # is not discriminating and the gate is worthless.
        measure("m", tmpdir)
    finally:
        _py("import maya.cmds as cmds\ncmds.currentUnit(linear='cm')\n'restored'",
            "restore the metre-true unit")

    # A real object, and only the transform section - `persp` was tried first
    # and errored (a camera has no mesh_stats), which made this check silently
    # not run at all. A check that can skip itself is worse than no check.
    _py("import maya.cmds as cmds\n"
        "cmds.polyCube(w=1, h=1, d=1, name='%s', ch=False)\n'built'" % CUBE,
        "build a cube for get_object_info")
    try:
        info = call("get_object_info",
                    {"name": CUBE, "include": ["transform"]}, port=PORT)
        if info.get("error"):
            check("get_object_info carries a units block too", False,
                  str(info["error"]))
        else:
            block = info["result"].get("units")
            check("get_object_info carries a units block too",
                  bool(block) and block["export_metres_per_unit"] == 1.0,
                  str(block))
    finally:
        _py("import maya.cmds as cmds\ncmds.delete('%s')\n'deleted'" % CUBE,
            "delete the get_object_info cube")

    failed = [label for passed, label in CHECKS if not passed]
    print("\n%d checks, %d failed" % (len(CHECKS), len(failed)))
    for label in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
