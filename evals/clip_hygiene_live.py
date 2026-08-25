"""Live gate for #721 part 2: `session.stop_idle_ipr` actually stops an idle
Arnold RenderView (IPR) and keeps it from wedging keyframe work.

#713 measured the failure this fixes: an Arnold RenderView left open by an
earlier render re-renders on every scene mutation, and the first keyframe
call after it wedged a live Maya for 30+ minutes. render_scene/render_sheet
now call `session.stop_idle_ipr` after finishing; author_clip/preview_clip
call it before keying. This is the measured re-run of that scenario:

1. render_scene one angle, arnold, low resolution, on a fresh cube - with
   the Arnold RenderView deliberately opened first (the #721p2 probe's
   measured open call), so the render's own hygiene has real cleanup to do.
   Asserts the result's warnings mention the hygiene action, and that the
   window is gone afterward.
2. Re-open the Arnold RenderView deliberately, then create_skeleton (two
   joints) + author_clip (three keys on one joint) with the DEFAULT
   timeout (120s, no timeout_s passed) - asserts it returns well inside that
   ceiling and that its warnings carry the "#721" hygiene line.
3. Cleanup: delete_clip, delete the scene objects, close any view.

Port default is 9877, NOT the usual disposable-Maya 9878: this ticket's own
task brief launches a dedicated agent Maya *on* 9877 for this work (see
.superpowers/sdd/task-5-brief.md's "Live Maya setup"), so 9877 is this
task's disposable session, not the user's. Set MAYA_MCP_EXPECT_PID to the
launched pid before running - the identity handshake in live_call.py then
refuses to proceed against any other Maya.

DESTRUCTIVE: calls new_scene.

Run:  MAYA_MCP_PORT=9877 MAYA_MCP_EXPECT_PID=<pid> .venv/Scripts/python.exe evals/clip_hygiene_live.py
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9877"))

CHECKS = []


def check(label, passed, detail=""):
    CHECKS.append((bool(passed), label))
    print("%s %s%s" % ("PASS" if passed else "FAIL", label,
                       ("  [%s]" % detail) if detail else ""))
    return bool(passed)


def send(command, params, timeout_s=120.0):
    try:
        return call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)


def ok(command, params, timeout_s=120.0):
    t0 = time.time()
    response = send(command, params, timeout_s)
    elapsed = time.time() - t0
    if response.get("status") != "ok":
        print("FAIL: %s: %s" % (command,
                                json.dumps(response.get("error"))[:600]))
        sys.exit(1)
    return response.get("result") or {}, elapsed


def py(code, what, timeout_s=60.0):
    result, _ = ok("execute_python", {"code": code}, timeout_s)
    return structured_result(result, what)


# The #721p2 probe's measured open call - a bare arnoldRenderView() call is
# exactly what mtoa's own "Render with the Arnold RenderView" menu item does
# (arnoldmenu.py: arnoldMtoARenderView), and it is what leaves Run IPR set.
# No explicit option=('Run IPR', '1') here: the probe measured that write as
# inert too (getoption's readback never moved either direction from script),
# so it would only be decorative - the bare open call is what actually
# leaves a window for stop_idle_ipr's deleteUI to find and close.
OPEN_ARV = (
    "import maya.cmds as cmds\n"
    "cmds.loadPlugin('mtoa', quiet=True)\n"
    "cmds.arnoldRenderView(camera='perspShape', mode='open')\n"
    "cmds.arnoldRenderView()\n"
    "cmds.window('ArnoldRenderView', exists=True)"
)
ARV_OPEN_CHECK = "cmds.window('ArnoldRenderView', exists=True)"


def main():
    identity = py("import os\n{'pid': os.getpid()}", "identity")
    print("Maya on %d: pid %s\n" % (PORT, identity["pid"]))

    ok("new_scene", {"confirm": True})

    # ---- 1. render_scene cleans up an ARV left open before it ran
    opened = py(OPEN_ARV, "open ARV before render_scene")
    check("ARV opened before render_scene (setup)", opened is True,
          "cmds.window(...)=%r" % opened)

    cube, _ = ok("create_primitive", {"kind": "cube", "name": "hygieneCube",
                                      "scale": [1.0, 1.0, 1.0],
                                      "translate": [0, 0, 0]})
    cube_name = cube["name"]
    result, elapsed_render = ok(
        "render_scene",
        {"angles": ["front"], "renderer": "arnold", "resolution": 64,
         "samples": 1, "isolate": [cube_name]},
        timeout_s=120.0)
    warnings_render = result.get("warnings", [])
    print("  render_scene elapsed: %.3fs" % elapsed_render)
    print("  render_scene warnings: %s" % json.dumps(warnings_render))
    check("render_scene: hygiene action reported in warnings",
          any("Arnold RenderView" in w and "#721" in w
              for w in warnings_render),
          json.dumps(warnings_render))
    window_after_render = py(ARV_OPEN_CHECK, "ARV state after render_scene")
    check("render_scene: the Arnold RenderView window is gone afterward",
          window_after_render is False, "window exists=%r" % window_after_render)

    # ---- 2. author_clip stops an ARV opened before it, within default timeout
    opened = py(OPEN_ARV, "re-open ARV before author_clip")
    check("ARV re-opened before author_clip (setup)", opened is True,
          "cmds.window(...)=%r" % opened)

    skeleton, _ = ok("create_skeleton", {"joints": [
        {"name": "hygieneRoot", "position": [0.0, 0.0, 0.0]},
        {"name": "hygieneMid", "position": [0.0, 1.0, 0.0],
         "parent": "hygieneRoot"},
    ]})
    root = skeleton["root"]

    t0 = time.time()
    # No timeout_s passed: this exercises the DEFAULT (120s) exactly as a
    # caller who never heard of #721 would call it.
    response = send("author_clip", {
        "root": root, "name": "hygieneProbe", "fps": 30,
        "keys": [
            {"time_s": 0.0, "rotations": {"hygieneMid": [0, 0, 0]}},
            {"time_s": 0.5, "rotations": {"hygieneMid": [0, 0, 30]}},
            {"time_s": 1.0, "rotations": {"hygieneMid": [0, 0, 0]}},
        ],
    }, timeout_s=125.0)  # a hair over the 120s default so a real hang times
                         # out here instead of at the socket layer
    elapsed_clip = time.time() - t0
    if response.get("status") != "ok":
        print("FAIL: author_clip: %s"
              % json.dumps(response.get("error"))[:600])
        sys.exit(1)
    clip_result = response.get("result") or {}
    print("  author_clip elapsed: %.3fs" % elapsed_clip)
    print("  author_clip warnings: %s" % json.dumps(clip_result["warnings"]))
    check("author_clip returned well inside the 120s default timeout",
          elapsed_clip < 120.0, "elapsed=%.3fs" % elapsed_clip)
    check("author_clip: warnings carry the #721 hygiene line",
          any("Arnold RenderView" in w and "#721" in w
              for w in clip_result["warnings"]),
          json.dumps(clip_result["warnings"]))

    # ---- 3. cleanup
    ok("delete_clip", {"root": root})
    py(("import maya.cmds as cmds\n"
        "for n in (%r, %r):\n"
        "    if cmds.objExists(n):\n"
        "        cmds.delete(n)\n"
        "if cmds.window('ArnoldRenderView', exists=True):\n"
        "    cmds.deleteUI('ArnoldRenderView')\n"
        "True") % (cube_name, root), "cleanup")

    failed = [label for passed, label in CHECKS if not passed]
    print("\n%d/%d passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
