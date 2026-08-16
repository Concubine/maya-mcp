"""Live gate for redmine #636: bend must actually bend, and deform must say
how far it moved the mesh.

The defect was a unit, not plumbing. `bend.curvature` is an angle-typed
attribute, so `cmds.setAttr` reads its number in the scene's UI angular unit -
degrees. The golem build asked for `curvature: 0.35` meaning "a third of a
radian of hunch" and got a third of a DEGREE: a real deformation, 0.4% of the
mesh's height, reported as a plain success. Nothing in the response could
distinguish that from a bend.

So this gate measures three things a headless test cannot:

1. a 45-degree bend moves the mesh by a visible fraction of its own size;
2. the inert call from the golem build (0.35) is reported as inert;
3. the same curvature means the same shape in a radians scene as in a degrees
   scene - the conversion, not just the documentation.

Plus the sibling defect the same ticket names: soft_move with a radius that
reaches no vertex reported `applied: 1` and moved nothing.

DESTRUCTIVE: calls new_scene. Defaults to port 9878 (the disposable
agent-launched Maya) and refuses 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1.

Run:  .venv/Scripts/python.exe evals/bend_live.py
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import DEFAULT_PORT, call, structured_result  # noqa: E402

PORT = DEFAULT_PORT

# Vertex truth, never exactWorldBoundingBox: that transforms the object-space
# box and over-reports any rotated mesh.
PROFILE = """
import maya.cmds as cmds
flat = cmds.xform('%s.vtx[*]', q=True, ws=True, t=True)
xs = flat[0::3]; ys = flat[1::3]; zs = flat[2::3]
{'lean': max(xs) - min(xs), 'height': max(ys) - min(ys),
 'depth': max(zs) - min(zs), 'verts': len(xs),
 # The centroid is here because extents alone cannot see a uniform move: a
 # soft_move whose falloff weighs every vertex the same (a sphere seen from
 # its own centre) slides the mesh without changing a single extent.
 'center': [round(sum(a) / len(a), 6) for a in (xs, ys, zs)]}
"""

failures = []


def send(command: str, params: dict, timeout_s: float = 120.0) -> dict:
    try:
        response = call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)
    if response.get("status") != "ok":
        print("FAIL: %s: %s" % (command, json.dumps(response.get("error"))[:400]))
        sys.exit(1)
    return response.get("result") or {}


def check(label: str, ok: bool, detail: str) -> None:
    print("%s %s: %s" % ("PASS" if ok else "FAIL", label, detail))
    if not ok:
        failures.append(label)


def profile(mesh: str) -> dict:
    return structured_result(send("execute_python", {"code": PROFILE % mesh}, 60.0))


def make_column(name: str) -> dict:
    """A 2.0-tall, 0.4-wide column: the torso shape, small enough to measure."""
    send("create_primitive", {"kind": "cylinder", "name": name,
                              "scale": [0.4, 2.0, 0.4], "divisions": 3})
    return profile("|" + name)


def bend_column(name: str, curvature: float) -> tuple:
    result = send("deform", {"mesh": "|" + name, "deformer": "bend",
                             "params": {"curvature": curvature}})
    return result, profile("|" + name)


def main() -> None:
    if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
        print("refusing to run on 9877: this eval discards the open scene. "
              "Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.")
        sys.exit(2)

    identity = structured_result(send("execute_python", {"code":
        "import os\nimport maya.cmds as cmds\n"
        "{'pid': os.getpid(), 'angle': cmds.currentUnit(q=True, angle=True)}"}, 60.0))
    print("Maya on %d: pid %s, angle unit %s\n"
          % (PORT, identity["pid"], identity["angle"]))

    send("new_scene", {"confirm": True})

    # 1. A bend the size a plan would ask for.
    before = make_column("bend_45")
    result, deg_after = bend_column("bend_45", 45.0)
    moved = result.get("max_displacement")
    check("45 degrees bends the column",
          isinstance(moved, (int, float)) and moved > 0.2,
          "max_displacement=%s, lean %.4f -> %.4f (X spread), height %.4f -> %.4f"
          % (moved, before["lean"], deg_after["lean"], before["height"],
             deg_after["height"]))
    check("a real bend raises no warning", result.get("warnings") == [],
          repr(result.get("warnings")))

    # 2. The golem's call, verbatim. It must now come back labelled.
    before = make_column("bend_inert")
    result, _inert_after = bend_column("bend_inert", 0.35)
    inert = result.get("max_displacement")
    ratio = inert / before["height"] if before["height"] else 0.0
    warnings = result.get("warnings") or []
    check("curvature 0.35 is reported as inert", len(warnings) == 1,
          "max_displacement=%.6f (%.3f%% of height) warnings=%s"
          % (inert, ratio * 100.0, warnings))
    check("the warning names the unit",
          bool(warnings) and "DEGREES" in warnings[0],
          warnings[0] if warnings else "(none)")

    # 3. The same number must mean the same shape in a radians scene. Pre-fix
    #    this was 45 RADIANS - seven full turns - and nothing said so.
    send("execute_python", {"code": "import maya.cmds as cmds\n"
                                    "cmds.currentUnit(angle='rad')\n'rad'"}, 60.0)
    try:
        make_column("bend_rad")
        rad_result, rad_after = bend_column("bend_rad", 45.0)
    finally:
        send("execute_python", {"code": "import maya.cmds as cmds\n"
                                        "cmds.currentUnit(angle='deg')\n'deg'"}, 60.0)
    same = abs(rad_result.get("max_displacement", 0.0) - moved) < 1e-4
    check("degrees mean degrees in a radians scene", same,
          "degrees scene %.6f vs radians scene %.6f (lean %.4f vs %.4f)"
          % (moved, rad_result.get("max_displacement", 0.0),
             deg_after["lean"], rad_after["lean"]))

    # 4. The sibling: soft_move whose radius reaches nothing.
    send("create_primitive", {"kind": "sphere", "name": "far_ball",
                              "translate": [5, 0, 0]})
    before = profile("|far_ball")
    response = call("sculpt_ops", {
        "mesh": "|far_ball",
        "ops": [{"op": "soft_move", "center": [0, 0, 0], "radius": 0.9,
                 "delta": [0, 0.5, 0]}],
    }, timeout_s=120.0, port=PORT)
    message = json.dumps(response.get("error") or {})
    after = profile("|far_ball")
    check("soft_move refuses a radius that reaches no vertex",
          response.get("status") != "ok" and "does not reach the mesh" in message,
          message[:200] or "reported ok")
    check("and it refused before moving anything",
          after == before, "%s vs %s" % (after, before))

    if failures:
        print("\n%d FAILED: %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
