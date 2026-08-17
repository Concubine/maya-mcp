"""Live gate for redmine #640: five naming and parameter papercuts.

Each of these cost the #601 golem run tool calls rather than correctness, and
each is the kind of thing a headless test can only half-prove:

1. `boolean_op(new_name=...)` could not reuse a name the call itself consumes.
   Whether it can now depends entirely on WHEN polyCBoolOp's operands stop
   existing, which a fake decides for itself.
2. `array` mirror numbered its single copy, so `name_prefix` was a stem rather
   than the name. 11 mirror calls, 11 renames.
3. `uv_atlas` refused `patch: 0` - the schema typed it as `object`, so the
   integer arrived as the string "0" and nothing coerced it. Only a run through
   the real MCP server exercises that coercion.
4. `render_sheet`'s isolate kept the subject's DESCENDANTS, so on a parented rig
   14 of 29 cells rendered sub-assemblies. Two halves: the hide set, and the
   framing - exactWorldBoundingBox includes hidden children, so a cell was
   framed on the subtree it had just hidden.
5. `render_sheet` had no `timeout_s`, and the timeout hint told the caller to
   pass one. The old ceiling WAS the old default, so the advice was unfollowable
   twice over.

Runs through the real MCP server (its schemas are half of items 3 and 5), so it
needs the tool surface, not just the plugin socket.

DESTRUCTIVE: calls new_scene. Defaults to port 9878 (the disposable
agent-launched Maya) and refuses 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1.

Run:  .venv/Scripts/python.exe evals/papercuts_live.py
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from maya_mcp import server as server_mod  # noqa: E402
from maya_mcp.connection import MayaConnection  # noqa: E402
from maya_plugin import version  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
    print("refusing to run against port 9877 (the user's Maya). Set "
          "MAYA_MCP_ALLOW_USER_SESSION=1 to override.")
    raise SystemExit(2)

failures = []
checks = 0


def check(name, ok, detail=""):
    global checks
    checks += 1
    print("%-4s %s%s" % ("PASS" if ok else "FAIL", name, (" - " + detail) if detail else ""))
    if not ok:
        failures.append(name)


def run(coro):
    return asyncio.run(coro)


def text_of(result):
    return " ".join(
        c.text for c in result.content if getattr(c, "type", None) == "text"
    )


def structured(result, prefix):
    """The JSON payload of the content block starting with `prefix`."""
    for block in result.content:
        body = getattr(block, "text", "") or ""
        if body.startswith(prefix):
            return json.loads(body[len(prefix):])
    return None


def json_of(result):
    """The first content block that parses as a JSON object.

    Tool results are pretty-printed over many lines, so substring checks like
    '"patch": [0, 0]' silently never match. Parse it instead.
    """
    for block in result.content:
        body = (getattr(block, "text", "") or "").strip()
        if body.startswith("{"):
            try:
                return json.loads(body)
            except ValueError:
                continue
    return None


def py(mcp, code):
    """execute_python, returning the repr of its final expression."""
    result = run(mcp.call_tool("maya_execute_python", {"code": code}))
    body = text_of(result)
    if "result_repr" in body:
        return json.loads(body[body.index("{"):])["result_repr"]
    return body


def main():
    conn = MayaConnection(port=PORT)
    try:
        pong = conn.request("ping", {}, timeout_s=10.0)
    except Exception as exc:  # noqa: BLE001
        print("no plugin answered on port %d (%s)" % (PORT, exc))
        return 2

    # A RUNNING Maya holds the plugin it imported at startup: deploying to
    # Documents/maya/scripts does not change it. Two of this ticket's fixes were
    # made after the eval Maya launched, and without this the run reported them
    # as regressions - the failure looked exactly like the bug it had just fixed.
    # Restart Maya rather than trying to hot-patch it.
    try:
        stale = version.compare(
            pong.get("plugin"),
            version.package_digest(os.path.join(REPO, "maya_plugin")),
            working_commit=version.git_stamp(REPO)["commit"],
        )
    except Exception:  # noqa: BLE001 - a missing stamp is not a verdict
        stale = None
    process = pong.get("process") or {}
    print("answering pid %s, plugin %s"
          % (process.get("pid"), (pong.get("plugin") or {}).get("digest", "?")[:12]))
    if stale and os.environ.get("MAYA_MCP_SKIP_STALE_CHECK") != "1":
        print("\n%s\n%s\nRESTART Maya before trusting this run.\n%s"
              % ("!" * 72, stale, "!" * 72))
        return 2

    mcp = server_mod.create_server(conn)

    # ---------------------------------------------------------------- item 1
    print("\n== 1. boolean_op can reuse a name it consumes ==")
    run(mcp.call_tool("maya_new_scene", {"confirm": True}))
    for name, translate in (("golem_L_shoulder", [0, 0, 0]), ("socket", [1, 1, 0])):
        run(mcp.call_tool("maya_create_primitive", {
            "kind": "cube", "name": name, "size": 2.0 if name != "socket" else 1.0,
            "translate": translate,
        }))
    out = run(mcp.call_tool("maya_boolean_op", {
        "a": "golem_L_shoulder", "b": "socket", "op": "difference",
        "new_name": "golem_L_shoulder",
    }))
    body = text_of(out)
    check("1a the result keeps the name the caller asked for",
          '"|golem_L_shoulder"' in body or "'|golem_L_shoulder'" in body,
          body[:160])
    check("1b and no _001 twin was invented",
          "golem_L_shoulder_001" not in body, body[:160])

    exists = py(mcp, "import maya.cmds as cmds\n"
                     "[cmds.objExists('|golem_L_shoulder'), "
                     "cmds.objExists('golem_L_shoulder_001')]")
    check("1c Maya agrees, not just the response", exists == "[True, False]", exists)

    # The safety half: a name held by something this call does NOT consume.
    run(mcp.call_tool("maya_create_primitive", {
        "kind": "cube", "name": "bystander", "translate": [20, 0, 0]}))
    run(mcp.call_tool("maya_create_primitive", {
        "kind": "cube", "name": "cutter2", "size": 1.0, "translate": [1, 1, 0]}))
    out = run(mcp.call_tool("maya_boolean_op", {
        "a": "golem_L_shoulder", "b": "cutter2", "op": "difference",
        "new_name": "bystander",
    }))
    body = text_of(out)
    still_there = py(mcp, "import maya.cmds as cmds\ncmds.objExists('|bystander')")
    check("1d an UNCONSUMED object's name is not stolen, and it says so",
          "bystander" in body and "held by another object" in body
          and still_there == "True",
          body[:200])

    # ---------------------------------------------------------------- item 2
    print("\n== 2. array mirror takes name_prefix as the NAME ==")
    run(mcp.call_tool("maya_new_scene", {"confirm": True}))
    run(mcp.call_tool("maya_create_primitive", {
        "kind": "cube", "name": "golem_L_arm", "translate": [2, 0, 0]}))
    out = run(mcp.call_tool("maya_array", {
        "name": "golem_L_arm", "mode": "mirror", "axis": "x",
        "name_prefix": "golem_R_arm",
    }))
    body = text_of(out)
    check("2a the mirrored copy is called exactly what was asked",
          '"|golem_R_arm"' in body or "'|golem_R_arm'" in body, body[:200])
    check("2b no unconditional _1 suffix", "golem_R_arm_1" not in body, body[:200])
    names = py(mcp, "import maya.cmds as cmds\n"
                    "sorted(n for n in cmds.ls('golem_*', long=True))")
    check("2c and that is the name in the scene",
          "|golem_R_arm'" in names and "golem_R_arm_1" not in names, names)

    # ---------------------------------------------------------------- item 3
    print("\n== 3. uv_atlas accepts the integer patch its docs describe ==")
    run(mcp.call_tool("maya_new_scene", {"confirm": True}))
    run(mcp.call_tool("maya_create_primitive", {"kind": "cube", "name": "chunk"}))
    out = run(mcp.call_tool("maya_uv_atlas", {"names": ["chunk"], "patch": 0}))
    check("3a patch=0 is accepted", out.is_error is False, text_of(out)[:200])
    payload = json_of(out) or {}
    check("3b and it wrote the TOP-LEFT patch", payload.get("patch") == [0, 0],
          "patch=%r, uv_bounds=%r"
          % (payload.get("patch"),
             (payload.get("meshes") or [{}])[0].get("uv_bounds")))
    out_pair = run(mcp.call_tool("maya_uv_atlas", {"names": ["chunk"], "patch": [2, 1]}))
    pair_payload = json_of(out_pair) or {}
    check("3c an explicit [col, row] still works",
          out_pair.is_error is False and pair_payload.get("patch") == [2, 1],
          "patch=%r" % (pair_payload.get("patch"),))

    # ---------------------------------------------------------------- item 4
    print("\n== 4. a sheet cell shows its own piece, not its sub-assemblies ==")
    run(mcp.call_tool("maya_new_scene", {"confirm": True}))
    # pelvis contains chest contains head - the golem's own shape.
    build = """
import maya.cmds as cmds
for name, size, y in (('pelvis', 2, 1), ('chest', 4, 4), ('head', 2, 7)):
    cmds.polyCube(name=name, w=size, h=size, d=size)
    cmds.xform(name, ws=True, t=(0, y, 0))
cmds.parent('chest', 'pelvis')
cmds.parent('head', 'chest')
[cmds.ls('pelvis', long=True)[0], cmds.ls('head', long=True)[0]]
"""
    print("   built: %s" % py(mcp, build))

    # The hide half, measured directly on the real function: which shapes does a
    # pelvis cell leave visible when chest and head are rival subjects?
    probe = """
import maya.cmds as cmds
from maya_plugin.handlers import render
hidden = render._hide_non_targets(
    cmds, ['|pelvis'], ['|pelvis|chest', '|pelvis|chest|head'])
visible = sorted(s for s in (cmds.ls(geometry=True, long=True) or [])
                 if cmds.getAttr(s + '.visibility'))
for h in hidden:
    cmds.showHidden(h)
visible
"""
    visible = py(mcp, probe)
    check("4a the pelvis cell keeps its own shape",
          "pelvisShape" in visible, visible)
    check("4b and hides the chest and head, which are cells of their own",
          "chestShape" not in visible and "headShape" not in visible, visible)

    # The framing half: the camera must sit where the CHUNK's box puts it.
    sheet = run(mcp.call_tool("maya_render_sheet", {
        "subjects": ["|pelvis", "|pelvis|chest", "|pelvis|chest|head"],
        "renderer": "hw2", "resolution": 128, "samples": 1, "timeout_s": 900.0,
    }))
    if sheet.is_error:
        check("4c the sheet rendered at all", False, text_of(sheet)[:300])
    else:
        body = text_of(sheet)
        notes = [
            line.strip() for line in body.split("note: ")[1:] if "contains" in line
        ]
        check("4c nesting is stated rather than left as a surprise",
              "contains 2 other subject" in body,
              (notes[0][:150] if notes else "no nesting note in the response"))
    # The framing half. The sheet TOOL does not report camera positions - a
    # 29-cell sheet would spend its whole response on them - so this reads them
    # off the plugin's own return, which still runs the entire handler in Maya.
    # Each cell's camera is compared against camera_placement's OWN answer for
    # the box that cell should have used, so a pass says WHICH framing happened
    # rather than "some number that looks small". The first version of this check
    # asserted `pelvis < max(distances)` and passed because a bug had put two
    # cameras 5.8e20 units out - an assertion satisfied by the defect it was
    # meant to catch.
    framing_probe = """
import maya.cmds as cmds
from maya_plugin.handlers import capture, render
subjects = ['|pelvis', '|pelvis|chest', '|pelvis|chest|head']
out = render.render_sheet({
    'subjects': subjects, 'renderer': 'hw2', 'resolution': 128, 'samples': 1,
})
expected = {}
for subject in subjects:
    own = cmds.listRelatives(subject, shapes=True, fullPath=True) or []
    box = cmds.exactWorldBoundingBox(*own) if own else None
    if box:
        pos, _rot = capture.camera_placement('three_quarter', box[:3], box[3:])
        expected[subject] = [round(v, 3) for v in pos]
subtree = cmds.exactWorldBoundingBox('|pelvis')
pos, _rot = capture.camera_placement('three_quarter', subtree[:3], subtree[3:])
{'actual': {p['label']: [round(v, 3) for v in p['position']]
            for p in out['camera_positions']},
 'expected_own_chunk': expected,
 'expected_whole_subtree': [round(v, 3) for v in pos]}
"""
    measured = py(mcp, framing_probe)
    try:
        data = json.loads(measured.replace("'", '"'))
    except ValueError:
        data = None
    if not data:
        check("4d each cell is framed on its own piece", False, str(measured)[:250])
    else:
        actual, expected = data["actual"], data["expected_own_chunk"]
        subtree_pos = data["expected_whole_subtree"]
        for label in sorted(actual):
            print("   %-24s camera %s (its own chunk wants %s)"
                  % (label.split("|")[-1], actual[label],
                     expected.get(label, "?")))
        print("   the whole subtree would want %s" % (subtree_pos,))
        matched = [
            label for label, pos in actual.items()
            if label in expected
            and math.dist(pos, expected[label]) < 0.05
        ]
        check("4d every cell is framed on its OWN chunk's box",
              len(matched) == len(actual) and len(actual) == 3,
              "%d of %d cells matched their chunk's placement" % (len(matched), len(actual)))
        check("4e and the containing cell is NOT framed on the whole subtree",
              math.dist(actual.get("|pelvis", [0, 0, 0]), subtree_pos) > 0.05,
              "pelvis camera %s vs subtree framing %s"
              % (actual.get("|pelvis"), subtree_pos))
        check("4f no cell got the all-hidden sentinel box (a 1e20 camera)",
              all(max(abs(v) for v in pos) < 1e4 for pos in actual.values()),
              "furthest camera component: %.3g"
              % max(max(abs(v) for v in pos) for pos in actual.values()))

    # ---------------------------------------------------------------- item 5
    print("\n== 5. render_sheet takes a timeout_s, and it reaches the plugin ==")
    tools = run(mcp.list_tools())
    sheet_tool = next(t for t in tools if t.name == "maya_render_sheet")
    schema = sheet_tool.input_schema["properties"]
    check("5a the parameter the timeout hint names actually exists",
          "timeout_s" in schema, ", ".join(sorted(schema)))
    check("5b it may exceed the old 600 s ceiling",
          schema.get("timeout_s", {}).get("maximum", 0) > 600.0,
          json.dumps(schema.get("timeout_s", {})))
    ceiling = py(mcp, "from maya_plugin import dispatcher\ndispatcher.MAX_TIMEOUT_S")
    check("5c and the LIVE plugin honours values that high",
          float(ceiling) >= schema.get("timeout_s", {}).get("maximum", 0),
          "live dispatcher MAX_TIMEOUT_S = %s, schema max = %s"
          % (ceiling, schema.get("timeout_s", {}).get("maximum")))

    print("\n%d checks, %d failures" % (checks, len(failures)))
    for name in failures:
        print("  FAILED: %s" % name)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
