"""#767 live gate: every command refuses a param it does not read, over the wire.

The headless contract test (tests/test_param_contract.py) calls handlers
directly with no Maya. That proves the guard exists; it cannot prove the guard
is REACHABLE the way a real caller reaches it. This gate sends real frames to a
real Maya and asks three questions the headless suite structurally cannot:

  1  Does every registered command answer a bogus key with a refusal naming it,
     through the dispatcher, in a Maya where _cmds() actually succeeds? A guard
     that sat behind a Maya touch would still pass headless-with-no-maya by
     raising ImportError; here it would run the command instead.
  2  Does a refusal leave the session HEALTHY? A guard that raised past the
     dispatcher's HandlerError handling, or burned a checkpoint, or half-opened
     an undo chunk, would show up as the next call failing - so every refusal
     is followed by a liveness probe, and the scene is counted before and after.
  3  Do the synonym maps hint the RIGHT key? The #764 failure was a plausible
     wrong word, and a hint that names the wrong key is worse than no hint.

Plus the positive control that matters most: legitimate calls must still work.
A sweep that refuses everything would pass checks 1-3 and be a catastrophe, so
this builds and exports a small rig with ordinary params throughout.

DESTRUCTIVE: calls new_scene. Port 9878, the agent-launched Maya, per the
two-Maya policy - never point this at the user's 9877.

Run:  $env:MAYA_MCP_PORT='9878'; python evals/param_sweep_live.py --build
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from live_call import call  # noqa: E402
from maya_plugin.maya_mcp_plugin import _build_handlers  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
OUT_DIR = os.path.join(_HERE, "param_sweep_live")

# The key no handler will ever read. Deliberately not a near-miss of anything:
# a prefix-matchable word would exercise the hint path instead of the refusal.
BOGUS = "definitely_not_a_param_767"

# Commands whose bogus-key probe must NOT be sent blind, with the reason.
# new_scene/open_scene would discard the scene the positive controls build;
# they are probed at the very end instead, after nothing depends on the scene.
DEFER_TO_END = ("new_scene", "open_scene")

CHECKS = []


def check(label, passed, detail=""):
    CHECKS.append((bool(passed), label))
    print("%s %s%s" % ("PASS" if passed else "FAIL", label,
                       ("  [%s]" % detail) if detail else ""))


def require_ok(res, what, allow_error=False):
    if res.get("status") != "ok" and not allow_error:
        print("FATAL: %s failed: %r" % (what, res.get("error")))
        sys.exit(1)
    return res.get("result") or {}


def scene_object_count():
    res = call("get_scene_graph", {}, timeout_s=60.0)
    result = res.get("result") or {}
    return len(result.get("objects") or [])


def probe_unknown_key(command, extra_params=None):
    """Send `command` one bogus key and return (refused, message, hint)."""
    params = dict(extra_params or {})
    params[BOGUS] = 1
    res = call(command, params, timeout_s=120.0)
    if res.get("status") == "ok":
        return False, "COMMAND RAN - the key was ignored", ""
    err = res.get("error") or {}
    return (
        err.get("type") == "HandlerError" and BOGUS in (err.get("message") or ""),
        err.get("message") or "",
        err.get("hint") or "",
    )


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    if "--build" not in sys.argv:
        print(__doc__)
        print("refusing to run without --build (this calls new_scene)")
        return 1

    ping = call("ping", {}, timeout_s=20.0)
    if ping.get("status") != "ok":
        print("no plugin answered on port %d" % PORT)
        return 2

    # ---------------------------------------------------------------- 1. ping
    # ping first, because if the sweep broke the cheapest command nothing
    # below is trustworthy.
    refused, msg, hint = probe_unknown_key("ping")
    check("ping refuses an unknown key", refused, msg[:110])
    check("ping still answers after refusing",
          call("ping", {}, timeout_s=20.0).get("status") == "ok")

    require_ok(call("new_scene", {"confirm": True}, timeout_s=120.0),
               "new_scene")

    # ------------------------------------------------- 2. positive controls
    # Ordinary calls with ordinary params. If the sweep made the toolbox
    # refuse legitimate work, this is where it shows - and it is the failure
    # that matters more than any refusal below.
    require_ok(call("create_primitive", {
        "kind": "cube", "name": "gate_box", "translate": [0, 0.5, 0],
        "scale": [1, 1, 1]}, timeout_s=120.0), "create_primitive")
    check("create_primitive still works with ordinary params", True)

    require_ok(call("transform", {
        "names": ["|gate_box"], "translate": [0.25, 0, 0], "relative": True},
        timeout_s=120.0), "transform")
    check("transform still works", True)

    mat = require_ok(call("assign_material", {
        "mesh": "|gate_box", "shader": "standardSurface",
        "name": "gate_mat", "params": {"baseColor": [0.5, 0.4, 0.3]}},
        timeout_s=120.0), "assign_material")
    check("assign_material still works and honours the explicit name",
          mat.get("material") == "gate_mat", str(mat.get("material")))

    require_ok(call("duplicate", {
        "name": "|gate_box", "new_name": "gate_box_copy",
        "translate": [2, 0, 0]}, timeout_s=120.0), "duplicate")
    require_ok(call("group", {
        "names": ["|gate_box", "|gate_box_copy"], "group_name": "gate_grp"},
        timeout_s=120.0), "group")
    check("duplicate + group still work", True)

    before = scene_object_count()

    # --------------------------------------- 3. every command refuses a key
    # The whole registry, not a sample: the sweep's claim is universal, so a
    # sampled gate would be a weaker claim than the one being made.
    commands = sorted(_build_handlers())
    deferred = [c for c in commands if c in DEFER_TO_END]
    probes = [c for c in commands if c not in DEFER_TO_END]

    refused_all = []
    ran_anyway = []
    wrong_shape = []
    for command in probes:
        ok, msg, _hint = probe_unknown_key(command)
        if ok:
            refused_all.append(command)
        elif "COMMAND RAN" in msg:
            ran_anyway.append(command)
        else:
            wrong_shape.append((command, msg[:100]))

    check("every non-scene-destroying command refuses the bogus key (%d/%d)"
          % (len(refused_all), len(probes)),
          len(refused_all) == len(probes),
          ("ran anyway: %s; wrong error: %s" % (ran_anyway, wrong_shape))
          if (ran_anyway or wrong_shape) else "")

    # A refusal must cost nothing: same scene, still responsive. This is the
    # check that would catch a guard placed after a mutation or a checkpoint.
    after = scene_object_count()
    check("the scene is unchanged after %d refusals" % len(probes),
          after == before, "before=%d after=%d" % (before, after))
    check("the session is still healthy after %d refusals" % len(probes),
          call("ping", {}, timeout_s=20.0).get("status") == "ok")

    # ------------------------------------------------- 4. synonym diagnosis
    # Each case is a wrong word a caller genuinely reaches for, and the hint
    # must name the key they meant. #764 itself is the first row.
    synonym_cases = [
        ("assign_material", {"mesh": "|gate_box", "material": "x"},
         "material", "name"),
        ("create_primitive", {"kind": "cube", "type": "cube"},
         "type", "kind"),
        ("transform", {"names": ["|gate_box"], "position": [1, 0, 0]},
         "position", "translate"),
        ("mesh_cleanup", {"mesh": "|gate_box", "threshold": 0.01},
         "threshold", "merge_verts_threshold"),
        ("export_fbx", {"path": "x.fbx", "objects": ["|gate_box"]},
         "objects", "nodes"),
    ]
    for command, params, wrong, right in synonym_cases:
        res = call(command, params, timeout_s=120.0)
        err = res.get("error") or {}
        message = err.get("message") or ""
        hint = err.get("hint") or ""
        check("%s: %r is diagnosed as %r" % (command, wrong, right),
              res.get("status") == "error" and wrong in message
              and right in hint,
              (message + " | " + hint)[:150])

    # ------------------------------------------------------- 5. the deferred
    # Last, because these discard the scene everything above relied on.
    for command in deferred:
        ok, msg, _hint = probe_unknown_key(command)
        check("%s refuses the bogus key" % command, ok, msg[:110])

    check("the session survives the scene-destroying probes",
          call("ping", {}, timeout_s=20.0).get("status") == "ok")

    summary = {
        "commands_probed": len(probes) + len(deferred),
        "refused": len(refused_all) + len(deferred),
        "ran_anyway": ran_anyway,
        "wrong_error_shape": wrong_shape,
        "scene_objects_before": before,
        "scene_objects_after": after,
    }
    with open(os.path.join(OUT_DIR, "summary.json"), "w") as handle:
        json.dump(summary, handle, indent=1)

    failed = [label for passed, label in CHECKS if not passed]
    print("\n%d/%d passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
