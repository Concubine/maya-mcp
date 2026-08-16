"""Live gate for maya-mcp #642: does maya_export_fbx write what it claims?

A headless test of this tool proves the gate logic and nothing else. The
export itself is Maya calling the FBX plugin, and the defect the gate exists
to catch is written at exactly that step - so the only check worth anything
runs against a real Maya and reads the bytes that came out.

Three measurements, one cube:

    a metre-native cube    -> exports, gate passes, span measures CUBE_SIDE
    the same cube, scaled  -> refused, and the FILE IS GONE afterwards
    metres_per_unit=100    -> refused before Maya is touched at all

The second is the important one. A tool that reports a violation but leaves
the file on disk has not solved anything: the transcript scrolls away and the
file ends up in a delivery.

DESTRUCTIVE: builds and deletes a probe cube in the current scene.

Defaults to port 9877, the user's own Maya, for the same reason
evals/units_live.py does - prove it in the session the user is looking at.
Do not "fix" it back to 9878.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fbx_probe  # noqa: E402  - sibling import, see evals/delivery_units.py
from evals.live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9877"))
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "export_live")
CUBE = "exportGateCube"
CUBE_SIDE = 3.0
TOL = 1e-3

CHECKS = []


def check(label, passed, detail=""):
    CHECKS.append((bool(passed), label))
    print("%s %s%s" % ("PASS" if passed else "FAIL", label,
                       ("  [%s]" % detail) if detail else ""))
    return bool(passed)


def _py(code, what):
    response = call("execute_python", {"code": code}, port=PORT)
    if response.get("error"):
        raise RuntimeError("%s: %s" % (what, response["error"]))
    return structured_result(response["result"], what)


def refresh_live_handlers():
    """Rebind export_fbx from the DEPLOYED source.

    A running Maya holds the modules it imported at startup, so a fresh deploy
    is invisible to it (maya-mcp #604). Without this the gate measures
    yesterday's plugin and reports it as today's.
    """
    return _py(
        "import importlib\n"
        "from maya_plugin import maya_mcp_plugin as _plugin\n"
        "from maya_plugin.handlers import fbxbytes as _fbxbytes\n"
        "from maya_plugin.handlers import export as _export\n"
        "for _m in (_fbxbytes, _export):\n"
        "    importlib.reload(_m)\n"
        "_h = _plugin._active_server._dispatcher._handlers\n"
        "_h['export_fbx'] = _export.export_fbx\n"
        "list(_export.FBX_PREAMBLE_MEL)",
        "rebind export_fbx from the deployed source",
    )


def build_cube(scale=1.0):
    """One cube of CUBE_SIDE units, optionally carrying a node scale.

    The name Maya actually returns is captured rather than assumed: polyCube
    auto-uniquifies, so a leftover from a previous run would make every later
    measurement describe the wrong object (the trap evals/pivot_live.py hit).
    """
    return _py("import maya.cmds as cmds\n"
               "if cmds.objExists('%(n)s'):\n"
               "    cmds.delete('%(n)s')\n"
               "_made = cmds.polyCube(w=%(s)g, h=%(s)g, d=%(s)g, name='%(n)s', "
               "ch=False)[0]\n"
               "cmds.setAttr(_made + '.scale', %(k)g, %(k)g, %(k)g)\n"
               "_made" % {"s": CUBE_SIDE, "n": CUBE, "k": scale},
               "build the probe cube")


def export(path, metres_per_unit=1.0, nodes=None):
    params = {"path": path.replace("\\", "/"), "metres_per_unit": metres_per_unit}
    if nodes is not None:
        params["nodes"] = nodes
    return call("export_fbx", params, port=PORT)


def span_of(facts):
    """Largest vertex extent in the file, on any axis - the cube is centred."""
    best = 0.0
    for verts in facts.meshes:
        for v in verts:
            best = max(best, abs(v))
    return best * 2.0


def cleanup():
    try:
        _py("import maya.cmds as cmds\n"
            "cmds.delete('%s') if cmds.objExists('%s') else None\n"
            "'cleaned'" % (CUBE, CUBE), "delete the probe cube")
    except Exception as exc:            # noqa: BLE001 - reporting, not control
        print("WARN could not delete %s: %s" % (CUBE, exc))


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("port %d, writing to %s\n" % (PORT, OUT_DIR))
    print("preamble live: %s\n" % (refresh_live_handlers(),))

    try:
        # 1. the good case
        good = os.path.join(OUT_DIR, "cube_ok.fbx")
        name = build_cube(scale=1.0)
        response = export(good, nodes=[name])
        if check("a metre-native cube exports", not response.get("error"),
                 str(response.get("error", ""))[:160]):
            # export_fbx is a first-class command, so its result IS the
            # handler's dict. structured_result is only for unwrapping
            # execute_python's repr envelope - which is the whole point of #642:
            # this no longer goes through execute_python.
            result = response["result"]
            facts = fbx_probe.read_fbx(good)
            check("the declaration is metres",
                  facts.unit_scale_factor == fbx_probe.DECLARES_METRES,
                  "UnitScaleFactor=%r" % facts.unit_scale_factor)
            check("the vertices are metre-magnitude",
                  abs(span_of(facts) - CUBE_SIDE) < TOL,
                  "span %.5f m, expected %.1f" % (span_of(facts), CUBE_SIDE))
            check("the reported height came from the file",
                  abs(result["height_m"] - CUBE_SIDE) < TOL,
                  "height_m=%.5f, bytes=%d, nodes=%d"
                  % (result["height_m"], result["bytes"], result["node_count"]))

        # 2. the case the whole tool exists for
        bad = os.path.join(OUT_DIR, "cube_scaled.fbx")
        if os.path.exists(bad):
            os.unlink(bad)
        name = build_cube(scale=0.01)
        response = export(bad, nodes=[name])
        check("a scaled node is refused", bool(response.get("error")),
              str(response.get("error", ""))[:160])
        check("and the refused file is NOT on disk", not os.path.exists(bad),
              "a warning the caller can ignore is not a gate")

        # 3. refused before Maya is touched
        never = os.path.join(OUT_DIR, "never_written.fbx")
        if os.path.exists(never):
            os.unlink(never)
        name = build_cube(scale=1.0)
        response = export(never, metres_per_unit=100.0, nodes=[name])
        check("metres_per_unit=100 is refused", bool(response.get("error")),
              str(response.get("error", ""))[:160])
        check("and nothing was written", not os.path.exists(never))
    finally:
        # Always, on every path: a leftover cube makes the NEXT run measure a
        # stale object, so a gate that skipped cleanup would lie on its second
        # invocation (maya-mcp #603's live gate hit exactly this).
        cleanup()

    failed = [label for ok, label in CHECKS if not ok]
    print("\n%d/%d passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
