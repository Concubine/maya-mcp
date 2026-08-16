"""Live gate for redmine #646: the two branches of maya_export_fbx nobody has run.

`evals/export_live.py` covers the selection export on the user's own Maya, one
cube at a time. Both holes this file exists for need a scene it may destroy and
a scene whose entire contents are known, so this one runs on the disposable
Maya and calls new_scene.

*1. The whole-scene branch (`nodes` omitted, `ea=True`).* Never run live. Every
committed FBX in the repo is a selection export. `FBXExportCameras` and
`FBXExportLights` are not pinned in the preamble, so whatever `FBXResetExport`
defaults to decides whether lights and cameras become `Model` records - and the
gate's identity-scale rule is applied to every `Model` regardless of kind. A
scaled light or locator would therefore refuse the export with a message about
vertex magnitude telling the caller to freeze transforms, which is not an
action that means anything for a light.

*2. Ancestor scale.* #646 predicted that exporting `nodes=["child"]` from under
a group carrying 0.8 writes a file whose every node is identity - green gate,
1.25x asset, invisible to any reader of the bytes. *It does not.* Measured on
Maya 2027: export-selected writes the ancestor chain, so `parentGRP` lands in
the file carrying its 0.8, the gate sees it and refuses by name. The check
below pins that behaviour down, because it is the whole reason no warning was
added: the file is not innocent, and the tool already says so.

Also exercised here, because the same controlled scene serves them: a
non-default rotateOrder (the reader composes only XYZ, so the measurement must
degrade honestly rather than lie or crash) and a moved pivot (#645's records,
which must now compose to the right height).

DESTRUCTIVE: calls new_scene. Defaults to port 9878 (the disposable
agent-launched Maya) and refuses 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1.

Run:  .venv/Scripts/python.exe evals/export_scene_live.py
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fbx_probe  # noqa: E402  - sibling import, see evals/delivery_units.py
from live_call import DEFAULT_PORT, call, structured_result  # noqa: E402

PORT = DEFAULT_PORT
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "export_scene_live")
SIDE = 2.0
TOL = 1e-3

CHECKS = []


def check(label, passed, detail=""):
    CHECKS.append((bool(passed), label))
    print("%s %s%s" % ("PASS" if passed else "FAIL", label,
                       ("  [%s]" % detail) if detail else ""))
    return bool(passed)


def send(command, params, timeout_s=180.0):
    """The raw response frame - a refusal is a measurement here, not an error."""
    try:
        return call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)


def ok(command, params, timeout_s=180.0):
    response = send(command, params, timeout_s)
    if response.get("status") != "ok":
        print("FAIL: %s: %s" % (command, json.dumps(response.get("error"))[:400]))
        sys.exit(1)
    return response.get("result") or {}


def py(code, what, timeout_s=120.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s), what)


def refresh_live_handlers():
    """Rebind export_fbx from the DEPLOYED source (#604): a running Maya holds
    the modules it imported at startup, so a fresh deploy is invisible to it."""
    return py(
        "import importlib\n"
        "from maya_plugin import maya_mcp_plugin as _plugin\n"
        "from maya_plugin.handlers import fbxbytes as _fbxbytes\n"
        "from maya_plugin.handlers import export as _export\n"
        "for _m in (_fbxbytes, _export):\n"
        "    importlib.reload(_m)\n"
        "_h = _plugin._active_server._dispatcher._handlers\n"
        "_h['export_fbx'] = _export.export_fbx\n"
        "list(_export.FBX_PREAMBLE_MEL) + list(_export.FBX_SCENE_CONTENT_MEL)",
        "rebind export_fbx from the deployed source",
    )


def export(path, nodes=None, metres_per_unit=1.0):
    params = {"path": path.replace("\\", "/"), "metres_per_unit": metres_per_unit}
    if nodes is not None:
        params["nodes"] = nodes
    return send("export_fbx", params)


def out(name):
    return os.path.join(OUT_DIR, name).replace("\\", "/")


def error_text(response):
    return json.dumps(response.get("error") or {})


def main():
    if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
        print("refusing to run on 9877: this eval discards the open scene. "
              "Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.")
        sys.exit(2)

    os.makedirs(OUT_DIR, exist_ok=True)
    identity = py("import os\nimport maya.cmds as cmds\n"
                  "{'pid': os.getpid()}", "identity")
    print("Maya on %d: pid %s, writing to %s" % (PORT, identity["pid"], OUT_DIR))
    print("preamble live: %s\n" % (refresh_live_handlers(),))

    # ---- 1. the whole-scene branch, on a scene holding what a lit scene holds
    ok("new_scene", {"confirm": True})
    # polyCube's width/height/depth, NOT create_primitive's scale: the latter
    # leaves the node carrying scale 2.0, which the gate refuses on its own
    # merits and would mask the thing under test here.
    py("import maya.cmds as cmds\n"
       "cmds.polyCube(w=%(s)g, h=%(s)g, d=%(s)g, name='sceneCube', ch=False)\n"
       "'built'" % {"s": SIDE}, "a metre-native probe cube")
    ok("setup_lighting", {"preset": "three_point"})
    py("import maya.cmds as cmds\ncmds.camera(name='shotCam')\n'built'",
       "a user camera")
    # The node the ticket predicts will refuse the export: not geometry, not a
    # light, carrying scale. An annotation locator is the ordinary way to get
    # one into a scene by accident.
    py("import maya.cmds as cmds\ncmds.spaceLocator(name='annotation')\n'built'",
       "an annotation locator")

    whole = out("whole_scene.fbx")
    if os.path.exists(whole):
        os.unlink(whole)
    response = export(whole)
    passed = check("a whole-scene export of a lit scene succeeds",
                   response.get("status") == "ok", error_text(response)[:200])
    if passed:
        result = response["result"]
        facts = fbx_probe.read_fbx(whole)
        kinds = sorted({n.kind for n in facts.nodes})
        check("the file carries the cube's geometry",
              result["mesh_count"] >= 1,
              "mesh_count=%d node_count=%d kinds=%s"
              % (result["mesh_count"], result["node_count"], kinds))
        check("the measured height is the cube's, not the rig's",
              result["height_m"] is not None
              and abs(result["height_m"] - SIDE) < TOL,
              "height_m=%r, expected %.1f, reason=%r"
              % (result["height_m"], SIDE, result.get("bounds_unavailable_reason")))
        # Lights and cameras DO become Model records - that is measured, and
        # now pinned in FBX_SCENE_CONTENT_MEL rather than left to
        # FBXResetExport's defaults. The point of asserting it is that the
        # scale rule below has to cope with them.
        check("lights and the camera are written as Models",
              len([n for n in facts.nodes if n.kind == "Light"]) == 3
              and any(n.kind == "Camera" for n in facts.nodes),
              "kinds present: %s" % kinds)

    # The defect: a scaled node that carries no geometry refused the whole
    # export with a message blaming vertex magnitude.
    scaled_extras = out("scaled_extras.fbx")
    if os.path.exists(scaled_extras):
        os.unlink(scaled_extras)
    py("import maya.cmds as cmds\n"
       "cmds.setAttr('annotation.scale', 3, 3, 3)\n"
       "cmds.setAttr('mcpLight_key.scale', 4, 4, 4)\n"
       "'scaled'", "scale the locator and a light")
    response = export(scaled_extras)
    if check("a scaled locator and a scaled LIGHT do not refuse the export",
             response.get("status") == "ok", error_text(response)[:300]):
        check("and the geometry is still measured correctly",
              abs(response["result"]["height_m"] - SIDE) < TOL,
              "height_m=%r" % response["result"]["height_m"])

    # ...but a scale that DOES reach a vertex must still refuse. A locator and
    # a group are both "Null" in the file, so this is the pair that proves the
    # rule is structural rather than by node kind.
    py("import maya.cmds as cmds\n"
       "cmds.group('sceneCube', name='assetGRP')\n"
       "cmds.setAttr('assetGRP.scale', 0.8, 0.8, 0.8)\n"
       "'grouped'", "put the cube under a scaled group")
    refused = out("scaled_ancestor.fbx")
    if os.path.exists(refused):
        os.unlink(refused)
    response = export(refused)
    message = error_text(response)
    check("a scaled group ABOVE the geometry still refuses",
          response.get("status") != "ok" and "assetGRP" in message,
          message[:200] or "exported anyway")
    check("and it names the group, not the locator or the light",
          "annotation" not in message and "mcpLight" not in message,
          message[:200])

    # ---- 2. ancestor scale: the file is innocent, the asset is 1.25x wrong
    ok("new_scene", {"confirm": True})
    py("import maya.cmds as cmds\n"
       "cmds.polyCube(w=%(s)g, h=%(s)g, d=%(s)g, name='child', ch=False)\n"
       "cmds.group('child', name='parentGRP')\n"
       "cmds.setAttr('parentGRP.scale', 0.8, 0.8, 0.8)\n"
       "cmds.exactWorldBoundingBox('child')[4] - "
       "cmds.exactWorldBoundingBox('child')[1]" % {"s": SIDE},
       "a child under a scaled group")

    dropped = out("ancestor_scale.fbx")
    if os.path.exists(dropped):
        os.unlink(dropped)
    response = export(dropped, nodes=["child"])
    message = error_text(response)
    # #646 expected a green export of a silently 1.25x asset. Maya writes the
    # ancestor chain into an export-selected file, so the 0.8 IS in the bytes
    # and the gate catches it - which is why the ticket's proposed
    # scene-scanning warning was not added: it would be dead code behind a
    # refusal that already names the node.
    check("a child of a scaled group is REFUSED, not silently shipped",
          response.get("status") != "ok" and "parentGRP" in message,
          message[:200] or "exported")
    check("and nothing reached the path", not os.path.exists(dropped))

    # ---- 3. a non-default rotateOrder must degrade honestly, not lie or crash
    ok("new_scene", {"confirm": True})
    py("import maya.cmds as cmds\n"
       "cmds.polyCube(w=%(s)g, h=%(s)g, d=%(s)g, name='spun', ch=False)\n"
       "cmds.setAttr('spun.rotateOrder', 3)\n"   # 3 = xzy
       "cmds.setAttr('spun.rotateY', 30)\n"
       "cmds.getAttr('spun.rotateOrder')" % {"s": SIDE},
       "a node with a non-default rotate order")

    spun = out("rotate_order.fbx")
    if os.path.exists(spun):
        os.unlink(spun)
    response = export(spun, nodes=["spun"])
    if check("a non-default rotateOrder still exports",
             response.get("status") == "ok", error_text(response)[:200]):
        result = response["result"]
        measured = result["height_m"] is not None
        reason = result.get("bounds_unavailable_reason")
        check("and either measures it or says why it cannot - never both null",
              measured or bool(reason),
              "height_m=%r reason=%r" % (result["height_m"], reason))
        if not measured:
            check("the reason names the rotate order, not 'no geometry'",
                  bool(reason) and "rotation order" in reason, "reason=%r" % reason)

    # ---- 4. a moved pivot: #645's records must compose to the right height
    ok("new_scene", {"confirm": True})
    scene_height = py(
        "import maya.cmds as cmds\n"
        "cmds.polyCube(w=%(s)g, h=%(s)g, d=%(s)g, name='pivoted', ch=False)\n"
        "cmds.xform('pivoted', piv=[0, -%(h)g, 0])\n"
        "cmds.setAttr('pivoted.rotateZ', 40)\n"
        "bb = cmds.exactWorldBoundingBox('pivoted')\n"
        "round(bb[4] - bb[1], 6)" % {"s": SIDE, "h": SIDE / 2.0},
        "a rotated node with a moved pivot")

    pivoted = out("moved_pivot.fbx")
    if os.path.exists(pivoted):
        os.unlink(pivoted)
    response = export(pivoted, nodes=["pivoted"])
    if check("a moved pivot still exports",
             response.get("status") == "ok", error_text(response)[:200]):
        result = response["result"]
        check("and the height read from the bytes matches Maya's own",
              result["height_m"] is not None
              and abs(result["height_m"] - scene_height) < 1e-2,
              "file %r vs maya %.5f" % (result["height_m"], scene_height))

    ok("new_scene", {"confirm": True})

    failed = [label for passed, label in CHECKS if not passed]
    print("\n%d/%d passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
