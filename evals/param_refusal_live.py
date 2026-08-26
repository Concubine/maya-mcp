"""#764 live gate: a param the tool does not read is refused, over the wire.

The defect: `assign_material` reads its explicit-name param as `name`, and a
caller passing `material=` got no error and no warning - the key fell through
and the material was given the mesh-derived default name instead. Eleven tests
in this repo passed `material=`. Every one created a differently-named
material than it believed it was creating, and every one PASSED, because they
read the name back out of the result rather than pinning it.

That is the whole failure mode, and it is why this gate measures the NAME IN
MAYA rather than the name in the result: a result that echoes back what the
handler decided cannot catch a handler that decided wrong. The check here asks
Maya what the shader is actually called.

Headless tests already cover the refusal itself. What only a live run proves
is that the refusal survives the TCP layer - an eval or an art script talks to
the plugin directly, without the MCP wrapper's typed parameters standing in
the way, so this is exactly the path on which the bad key could be sent.

Usage:

    set MAYA_MCP_PORT=9878
    set MAYA_MCP_EXPECT_PID=<the pid you launched>
    python evals/param_refusal_live.py

MUTATES THE ANSWERING MAYA'S CURRENT SCENE (new_scene, two cubes).
MAYA_MCP_EXPECT_PID is REQUIRED: this discards the open scene, so it refuses
to guess which Maya is disposable. A port is not an identity (#648).

Exit: 0 pass, 1 fail.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import call, structured_result  # noqa: E402

failures: list = []


def fail(message: str) -> None:
    failures.append(message)
    print("FAIL: " + message)


def preflight() -> dict:
    if not (os.environ.get("MAYA_MCP_EXPECT_PID") or "").strip():
        raise SystemExit(
            "MAYA_MCP_EXPECT_PID is not set. This gate discards the answering "
            "Maya's scene, so it will not guess which one is disposable - "
            "launch one yourself and name its pid (#648).")
    frame = call("ping", {})
    if frame.get("status") != "ok":
        raise SystemExit("ping failed: %r" % (frame.get("error"),))
    ping = frame.get("result") or {}
    if not ping:
        raise SystemExit("no Maya answered - start one, or check "
                         "MAYA_MCP_PORT. Do NOT fall back to batchmode.")
    if (ping.get("plugin") or {}).get("restart_required"):
        raise SystemExit(
            "the answering Maya (pid %s) holds stale modules - restart it "
            "before running this gate"
            % (ping.get("process") or {}).get("pid"))
    return ping


def ok(command: str, params: dict, timeout_s: float = 120.0) -> dict:
    frame = call(command, params, timeout_s=timeout_s)
    if frame.get("status") != "ok":
        raise SystemExit("%s failed: %r" % (command, frame.get("error")))
    return frame.get("result") or {}


def refused(command: str, params: dict) -> dict:
    frame = call(command, params, timeout_s=60.0)
    if frame.get("status") == "ok":
        fail("%s(%r) was ACCEPTED - the key must be refused, not ignored"
             % (command, sorted(params)))
        return {}
    return frame.get("error") or {}


def shaders_on(mesh: str) -> list:
    """What Maya says is actually shading this mesh - not what we were told."""
    return structured_result(ok("execute_python", {"code":
        "import maya.cmds as cmds\n"
        "shape = cmds.listRelatives(%r, shapes=True, fullPath=True)[0]\n"
        "sgs = cmds.listConnections(shape, type='shadingEngine') or []\n"
        "out = []\n"
        "for sg in set(sgs):\n"
        "    out.extend(cmds.ls(cmds.listConnections(sg + '.surfaceShader')\n"
        "                       or [], long=False))\n"
        "sorted(set(out))\n" % mesh}), "shaders on %s" % mesh)


def main() -> int:
    ping = preflight()
    print("answering Maya: pid %s" % (ping.get("process") or {}).get("pid"))
    ok("new_scene", {"confirm": True})

    print("claim 1: the unread key is refused, and says what was meant")
    ok("create_primitive", {"kind": "cube", "name": "refusal_cube"})
    error = refused("assign_material", {
        "mesh": "|refusal_cube", "shader": "lambert", "material": "clay"})
    message = "%s %s" % (error.get("message", ""), error.get("hint", ""))
    print("  %s" % message.strip()[:150])
    if "material" not in message:
        fail("the refusal did not name the offending key: %r" % message)
    if "'name'" not in message:
        fail("the refusal did not name the key that was MEANT - a synonym is "
             "exactly what re-reading the call site cannot reveal: %r"
             % message)

    print("claim 2: nothing was built by the refused call")
    # A refusal that half-applies is worse than none: the caller believes
    # nothing happened. Validation runs before any node is made.
    shaders = shaders_on("|refusal_cube")
    print("  shaders on the cube: %r" % (shaders,))
    if any(s == "clay" for s in shaders):
        fail("the refused call built 'clay' anyway: %r" % (shaders,))

    print("claim 3: the key it DOES read reaches Maya under that exact name")
    # The measured failure was silent misnaming, so this asks MAYA what the
    # shader is called. A result field that echoes the handler's own decision
    # cannot catch a handler that decided wrong.
    ok("create_primitive", {"kind": "cube", "name": "named_cube"})
    result = ok("assign_material", {
        "mesh": "|named_cube", "shader": "lambert", "name": "clay"})
    shaders = shaders_on("|named_cube")
    print("  result says %r; Maya says %r" % (result.get("material"), shaders))
    if "clay" not in shaders:
        fail("asked for a material called 'clay' and Maya has %r - this is "
             "the #764 failure itself" % (shaders,))
    if result.get("material") != "clay":
        fail("the result reported %r for a material Maya calls 'clay'"
             % (result.get("material"),))

    print()
    if failures:
        print("GATE FAILED (%d)" % len(failures))
        return 1
    print("GATE PASSED - an unread param is refused over the wire, and the "
          "one that is read lands in Maya under the name it was given.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
