"""Live gate for the wave that fixed #603's Important 1: does `assemble`'s
reported `pivot` field match what Maya actually has, for the three shapes a
`pivots` map can produce?

    A - multi-part chunk, WITH an explicit `pivots` entry
    B - multi-part chunk, OMITTED from `pivots` (gets the global `pivot` mode
        via combine.unite)
    C - single-part chunk, OMITTED from `pivots` (gets NO pivot treatment -
        Maya's own default pivot stands)

This is a MEASUREMENT script, not an assertion of what B and C "should" be:
combine.unite places its mode-based pivot BEFORE its own internal freeze, and
freeze is documented elsewhere in this codebase to reset pivots to the world
origin, so whether B's reported pivot survives that freeze is exactly the
open question this script exists to answer. Only A has a value anyone can
assert against, because the explicit override in assemble.py runs AFTER
combine.unite (and therefore after its freeze) - that ordering is what
tests/test_assemble.py's TestPivots class now pins headlessly.

Defaults to port 9877, not live_call.py's 9878, for the same reason
evals/pivot_live.py does: prove the fix in the session the USER is actually
looking at. Do not "fix" it back to 9878.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from evals.live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9877"))

# Requested chunk names. Maya may uniquify these on a collision with a
# leftover from a failed prior run, exactly as pivot_live.py's polyCube can
# come back 'pivotGate1' instead of 'pivotGate' - every query and the final
# cleanup below address the name the RESPONSE gives back, never these
# literals.
CHUNK_A, CHUNK_B, CHUNK_C = (
    "assemblePivotGateA", "assemblePivotGateB", "assemblePivotGateC",
)
EXPLICIT_PIVOT = [0.0, 9.0, 0.0]


def _measure(node_name: str) -> list:
    return structured_result(call("execute_python", {"code":
        "import maya.cmds as cmds\n"
        "cmds.xform('%s', q=True, ws=True, rotatePivot=True)" % node_name
    }, port=PORT)["result"], "measured pivot for %s" % node_name)


def main() -> int:
    names = []
    try:
        response = call("assemble", {
            "name": "assemblePivotGate",
            "atlas": None,
            "parts": [
                {"pos": [0, 0, 0], "dim": [1, 1, 1], "chunk": CHUNK_A},
                {"pos": [0, 1, 0], "dim": [1, 1, 1], "chunk": CHUNK_A},
                {"pos": [5, 0, 0], "dim": [1, 1, 1], "chunk": CHUNK_B},
                {"pos": [5, 1, 0], "dim": [1, 1, 1], "chunk": CHUNK_B},
                {"pos": [10, 0, 0], "dim": [1, 1, 1], "chunk": CHUNK_C},
            ],
            "pivots": {CHUNK_A: EXPLICIT_PIVOT},
        }, port=PORT)
        if response.get("error"):
            print("FAIL assemble: %s" % response["error"])
            return 1

        objects = response["result"]["objects"]
        # Capture the names Maya actually assigned BEFORE anything below can
        # raise, so a failure partway through measurement still cleans up
        # every object that got built.
        names = [o["name"] for o in objects]

        wanted_chunks = (CHUNK_A, CHUNK_B, CHUNK_C)
        if len(objects) != len(wanted_chunks):
            print("FAIL expected %d objects back, got %d: %s"
                  % (len(wanted_chunks), len(objects), names))
            return 1

        explicit_landed = None
        for chunk, obj in zip(wanted_chunks, objects):
            reported = obj["pivot"]
            measured = _measure(obj["name"])
            if reported is None:
                # C's expected shape: no pivot treatment at all. Still print
                # what Maya actually has - that is the measurement.
                print("%s (%s): reported=None measured=%s"
                      % (chunk, obj["name"], measured))
                continue
            agree = max(abs(a - b) for a, b in zip(reported, measured)) <= 1e-4
            print("%s (%s): reported=%s measured=%s %s"
                  % (chunk, obj["name"], reported, measured,
                     "PASS" if agree else "DISAGREE"))
            if chunk == CHUNK_A:
                explicit_landed = (
                    agree
                    and max(abs(a - b) for a, b in zip(measured, EXPLICIT_PIVOT)) <= 1e-4
                )

        if explicit_landed is None:
            print("FAIL chunk A never reported a pivot at all")
            return 1
        if not explicit_landed:
            print("FAIL the explicit pivot on %s did not land at %s"
                  % (CHUNK_A, EXPLICIT_PIVOT))
            return 1

        print("PASS explicit pivot landed and matched the reported value")
        return 0
    finally:
        # Unconditional and per-object: this must run whether the body
        # returned early, raised (structured_result raises on a
        # truncated/missing result; a malformed response can KeyError), or
        # fell through normally. A failed delete must not mask the real
        # pass/fail result, so each one is swallowed here rather than raised.
        for node_name in names:
            try:
                call("execute_python", {"code":
                    "import maya.cmds as cmds\n"
                    "cmds.delete('%s')\n'cleaned'" % node_name
                }, port=PORT)
            except Exception as exc:  # noqa: BLE001 - cleanup must not mask the result
                print("WARN cleanup of %s failed: %s" % (node_name, exc))


if __name__ == "__main__":
    raise SystemExit(main())
