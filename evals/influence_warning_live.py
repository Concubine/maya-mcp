"""#817 LIVE GATE: export_fbx says when a skin ships vertices with more than 4
influences - read from the FILE, matching what weight_report measured in the
scene - and says nothing for a 4-influence bind of the same mesh.

  1. a 10-joint chain, a tall tube bound at max_influences=8: export with
     include_skins -> skin.max_influences > 4, vertices_over_4_influences > 0,
     ONE warning naming the count, the maximum and the 4-heaviest rule; the
     file's maximum equals weight_report's.
  2. the same rig and mesh rebound at max_influences=4: max_influences <= 4,
     no such warning, and the export is otherwise identical in shape.

No captures. DESTRUCTIVE: calls maya_new_scene. Agent Maya on 9878 only;
refuses 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1. Phase 0 asserts the live
Maya imports THIS working tree.

Run:  MAYA_MCP_PORT=9878 python evals/influence_warning_live.py
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
    print("refusing to run against port 9877 (the user's Maya): this gate "
          "calls new_scene. Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.",
          file=sys.stderr)
    raise SystemExit(2)

OUT = os.path.join(_HERE, "influence_warning_live")
os.makedirs(OUT, exist_ok=True)
RESULTS = []


def check(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    print("%-4s %-72s %s" % ("PASS" if ok else "FAIL", label, detail), flush=True)


def ok(command, params, timeout_s=300.0):
    response = call(command, params, timeout_s=timeout_s, port=PORT)
    if response.get("status") != "ok":
        raise SystemExit("%s failed: %s" % (command, response.get("error")))
    return response.get("result") or {}


def py(code, what, timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s), what)


CHAIN = [[0, 0.2 * i, 0] for i in range(10)]


def build(max_influences):
    ok("new_scene", {"confirm": True})
    root = ok("create_skeleton", {"chain": CHAIN, "chain_prefix": "seg"})["root"]
    py("import maya.cmds as cmds\n"
       "cmds.polyCylinder(name='tube', r=0.15, h=1.8, sx=16, sy=36, sz=1)\n"
       "cmds.xform('tube', t=(0, 0.9, 0)); cmds.makeIdentity('tube', apply=True, t=True)\nTrue", "tube")
    bind = ok("bind_skin", {"mesh": "|tube", "root": root, "max_influences": max_influences})
    report = ok("weight_report", {"mesh": "|tube"})
    path = os.path.join(OUT, "tube_%d.fbx" % max_influences).replace("\\", "/")
    exp = ok("export_fbx", {"path": path, "metres_per_unit": 1.0, "include_skins": True,
                            "nodes": [root, "|tube"]})
    return bind, report, exp


# --------------------------------------------------------------- phase 0
print("=== 0. who answered, and whose code is it ===", flush=True)
ident = py("import os, maya_plugin\n{'file': maya_plugin.__file__, 'cwd': os.getcwd()}", "identity")
loaded = os.path.normcase(os.path.abspath(ident["file"]))
expected = os.path.normcase(os.path.join(REPO, "maya_plugin", "__init__.py"))
if loaded != expected:
    print("WRONG CODE: live Maya imports %s, not %s." % (loaded, expected), file=sys.stderr)
    raise SystemExit(2)
has = py("from maya_plugin.handlers import export\nhasattr(export, 'skin_warnings')", "loaded")
check("0. the #817 export handler is loaded in the live Maya", has is True)

# --------------------------------------------------------------- phase 1
print("\n=== 1. bound at 8 ===", flush=True)
bind8, rep8, exp8 = build(8)
skin8 = exp8.get("skin") or {}
over = [w for w in exp8.get("warnings", []) if "more than 4 influences" in w]
check("1a. the FILE reports a maximum above 4 and vertices over 4",
      (skin8.get("max_influences") or 0) > 4 and skin8.get("vertices_over_4_influences", 0) > 0,
      "max %r over %r" % (skin8.get("max_influences"), skin8.get("vertices_over_4_influences")))
check("1b. ... matching what weight_report measured in the scene",
      skin8.get("max_influences") == rep8.get("max_influences"),
      "file %r scene %r" % (skin8.get("max_influences"), rep8.get("max_influences")))
check("1c. exactly one warning, naming the count, the maximum and the 4-heaviest rule",
      len(over) == 1 and str(skin8.get("vertices_over_4_influences")) in over[0]
      and str(skin8.get("max_influences")) in over[0] and "renormalis" in over[0],
      over[0][:200] if over else json.dumps(exp8.get("warnings")))
check("1d. it is a warning: the export succeeded and the skin block is clean otherwise",
      skin8.get("unweighted_file_vertices") == 0 and (skin8.get("max_weight_sum_error") or 0) < 1e-2,
      json.dumps({k: skin8.get(k) for k in ("unweighted_file_vertices", "max_weight_sum_error")}))

# --------------------------------------------------------------- phase 2
print("\n=== 2. the same mesh bound at 4 ===", flush=True)
bind4, rep4, exp4 = build(4)
skin4 = exp4.get("skin") or {}
over4 = [w for w in exp4.get("warnings", []) if "more than 4 influences" in w]
check("2a. the FILE reports a maximum of at most 4 and no vertex over",
      (skin4.get("max_influences") or 0) <= 4 and skin4.get("vertices_over_4_influences") == 0,
      "max %r over %r" % (skin4.get("max_influences"), skin4.get("vertices_over_4_influences")))
check("2b. ... matching weight_report", skin4.get("max_influences") == rep4.get("max_influences"),
      "file %r scene %r" % (skin4.get("max_influences"), rep4.get("max_influences")))
check("2c. no influence warning", over4 == [], json.dumps(exp4.get("warnings")))
check("2d. CONTROL: both files bound the same joints",
      skin4.get("clusters") == skin8.get("clusters") and skin4.get("influenced_models") == skin8.get("influenced_models"),
      "clusters %r/%r" % (skin4.get("clusters"), skin8.get("clusters")))

# --------------------------------------------------------------- summary
ok("new_scene", {"confirm": True})
passed = sum(1 for _, r, _ in RESULTS if r)
print("\n%d / %d passed" % (passed, len(RESULTS)))
with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as fh:
    json.dump([{"check": label, "ok": r, "detail": d} for label, r, d in RESULTS], fh, indent=1)
raise SystemExit(0 if passed == len(RESULTS) else 1)
