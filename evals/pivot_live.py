"""Live gate for #603: a pivot lands, and the geometry does not move.

Defaults to port 9877, not live_call.py's 9878. 9878 is the disposable
agent-launched Maya (see live_call.py's docstring for the two-Maya
rationale) - fine for most gates, but wrong for this one. The point here is
to prove the fix works in the session the USER is actually looking at, so
this script deliberately targets 9877. Do not "fix" it back to 9878.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from evals.live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9877"))


def main() -> int:
    name = None
    try:
        # Capture the name Maya actually assigned rather than trusting
        # 'pivotGate' to still be free. If a prior run's cleanup failed,
        # polyCube uniquifies to pivotGate1/pivotGate2/... and every query
        # below addresses THAT object - never a stale leftover from a
        # previous run, which would silently measure the wrong mesh and
        # report a pass or fail describing neither run.
        name = structured_result(call("execute_python", {"code":
            "import maya.cmds as cmds\n"
            "name = cmds.polyCube(name='pivotGate')[0]\n"
            "cmds.xform(name, worldSpace=True, translation=(2, 3, 4))\n"
            "name"
        }, port=PORT)["result"], "build")

        before = structured_result(call("execute_python", {"code":
            "import maya.cmds as cmds\n"
            "(cmds.xform('%s', q=True, ws=True, translation=True),\n"
            " cmds.xform('%s', q=True, ws=True, boundingBox=True))" % (name, name)
        }, port=PORT)["result"], "before")

        response = call("transform", {"names": [name], "pivot": [0.0, 10.0, 0.0]},
                        port=PORT)
        if response.get("error"):
            print("FAIL transform: %s" % response["error"])
            return 1
        reported = response["result"]["objects"][0]["pivot"]

        after = structured_result(call("execute_python", {"code":
            "import maya.cmds as cmds\n"
            "(cmds.xform('%s', q=True, ws=True, rotatePivot=True),\n"
            " cmds.xform('%s', q=True, ws=True, translation=True),\n"
            " cmds.xform('%s', q=True, ws=True, boundingBox=True))" % (name, name, name)
        }, port=PORT)["result"], "after")

        pivot, translate, bbox = after
        ok = True
        if max(abs(a - b) for a, b in zip(pivot, [0.0, 10.0, 0.0])) > 1e-4:
            print("FAIL pivot is at %s, wanted [0, 10, 0]" % (pivot,)); ok = False
        if max(abs(a - b) for a, b in zip(reported, pivot)) > 1e-4:
            print("FAIL reported %s but Maya says %s" % (reported, pivot)); ok = False
        if max(abs(a - b) for a, b in zip(before[1], bbox)) > 1e-4:
            print("FAIL the mesh MOVED: %s -> %s" % (before[1], bbox)); ok = False
        if max(abs(a - b) for a, b in zip(before[0], translate)) > 1e-4:
            print("FAIL translate changed: %s -> %s" % (before[0], translate)); ok = False

        print("PASS pivot=%s bbox unchanged" % (pivot,) if ok else "FAILED")
        return 0 if ok else 1
    finally:
        # Unconditional: this must run whether the body returned early,
        # raised (structured_result raises on a truncated/missing result;
        # a malformed response can KeyError on ["result"]["objects"][0]),
        # or fell through normally. A failed delete must not mask the real
        # pass/fail result, so it is swallowed here rather than raised.
        if name is not None:
            try:
                call("execute_python", {"code":
                    "import maya.cmds as cmds\n"
                    "cmds.delete('%s')\n'cleaned'" % name
                }, port=PORT)
            except Exception as exc:  # noqa: BLE001 - cleanup must not mask the result
                print("WARN cleanup of %s failed: %s" % (name, exc))


if __name__ == "__main__":
    raise SystemExit(main())
