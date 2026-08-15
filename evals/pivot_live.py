"""Live gate for #603: a pivot lands, and the geometry does not move."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from evals.live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9877"))


def main() -> int:
    call("execute_python", {"code": "import maya.cmds as cmds\n"
                                    "cmds.polyCube(name='pivotGate')\n"
                                    "cmds.xform('pivotGate', worldSpace=True, "
                                    "translation=(2, 3, 4))\n"
                                    "'built'"}, port=PORT)

    before = structured_result(call("execute_python", {"code":
        "import maya.cmds as cmds\n"
        "(cmds.xform('pivotGate', q=True, ws=True, translation=True),\n"
        " cmds.xform('pivotGate', q=True, ws=True, boundingBox=True))"
    }, port=PORT)["result"], "before")

    response = call("transform", {"names": ["pivotGate"], "pivot": [0.0, 10.0, 0.0]},
                    port=PORT)
    if response.get("error"):
        print("FAIL transform: %s" % response["error"])
        return 1
    reported = response["result"]["objects"][0]["pivot"]

    after = structured_result(call("execute_python", {"code":
        "import maya.cmds as cmds\n"
        "(cmds.xform('pivotGate', q=True, ws=True, rotatePivot=True),\n"
        " cmds.xform('pivotGate', q=True, ws=True, translation=True),\n"
        " cmds.xform('pivotGate', q=True, ws=True, boundingBox=True))"
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

    call("execute_python", {"code": "import maya.cmds as cmds\n"
                                    "cmds.delete('pivotGate')\n'cleaned'"}, port=PORT)
    print("PASS pivot=%s bbox unchanged" % (pivot,) if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
