"""Live gate for redmine #796: the guards answer the question they were asked,
and delete_clip stops taking rig setup with it.

Three defects, all in the refuse-or-warn layer, all of a shape that headless
tests structurally cannot catch - each one turns on what REAL Maya does with a
name, a connection, or a deleted node:

1. delete_clip reaped set-driven keys. `_anim_curves` asks for type "animCurve"
   and Maya's type filter matches the DERIVED U-typed nodes too, so the
   teardown deleted the caller's rig setup along with the clip. The fix leaves
   them standing and says so. Two further hazards live only in real Maya and
   were found by review, not by the suite: classifying a node AFTER deleting it
   raises (FakeCmds happily answers "transform" for a dead name), and the
   no-bind-pose fallback's setAttr on a rotate compound raises once an SDK
   curve survives on one of its children (FakeCmds never checks connections).

2. guard_static_pose saw only a DIRECTLY connected curve, so a curve reaching a
   plug through the pairBlend Maya inserts when a keyed plug is also
   constrained was invisible: the guard passed and the static write was
   silently overridden. Whether an anim LAYER is reachable the same way is a
   question only Maya can answer - layers wire the .rotate COMPOUND, and a
   child-plug query does not see a parent connection. This gate MEASURES both
   wirings rather than asserting a belief about them.

3. _outside_wearers compared SHORT names, so |left|limb and |right|limb were
   indistinguishable and baking one silently skipped the warning that the
   other's look changed. The decisive input is what `cmds.sets(sg, query=True)`
   actually ANSWERS for that scene - Maya returns the shortest UNIQUE name,
   which for a mirrored pair is a PARTIAL path ('right|limbShape'), neither of
   the two forms a fake naturally produces. Measured here, not assumed.

DESTRUCTIVE: calls new_scene. Runs against the disposable agent Maya on 9878
and REFUSES 9877 (the user's session) unless MAYA_MCP_ALLOW_USER_SESSION=1.

The live Maya must be launched with the repo as its working directory, so that
Maya's CWD-on-sys.path makes it import THIS working tree's plugin rather than
the deployed copy in Documents/maya/scripts. Phase 0 asserts exactly that -
a green run against the deployed copy would be a measurement of last week.

Run:  MAYA_MCP_PORT=9878 MAYA_MCP_EXPECT_PID=<pid> .venv/Scripts/python.exe evals/guards_live.py
Exit: 0 pass, 1 fail, 2 environment (nothing listening / wrong code loaded).
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
          "calls new_scene. Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.")
    raise SystemExit(2)

CHECKS = []


def check(label, passed, detail=""):
    CHECKS.append((bool(passed), label))
    print("%-4s %s%s" % ("PASS" if passed else "FAIL", label,
                         ("  [%s]" % detail) if detail else ""))
    return bool(passed)


def send(command, params, timeout_s=120.0):
    try:
        return call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)


def ok(command, params, timeout_s=120.0):
    response = send(command, params, timeout_s)
    if response.get("status") != "ok":
        print("FAIL: %s: %s" % (command, json.dumps(response.get("error"))[:800]))
        sys.exit(1)
    return response.get("result") or {}


def refusal(command, params, timeout_s=120.0):
    """The error payload of a call that MUST refuse, or None if it succeeded."""
    response = send(command, params, timeout_s)
    if response.get("status") == "ok":
        return None
    return response.get("error") or {}


def py(code, what, timeout_s=120.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s),
                             what)


def main():
    # ---- 0. who answered, and WHOSE code is it -------------------------
    ident = py("import os, maya_plugin\n"
               "{'pid': os.getpid(), 'plugin': maya_plugin.__file__}",
               "identity")
    print("maya on %d: pid %s\nplugin: %s\n" % (PORT, ident["pid"],
                                                ident["plugin"]))
    if os.path.normcase(REPO) not in os.path.normcase(ident["plugin"]):
        print("the live Maya is running the plugin at %s, NOT this working "
              "tree (%s). Relaunch Maya with -WorkingDirectory %s so its CWD "
              "puts the repo on sys.path; a gate against the deployed copy "
              "measures the wrong code." % (ident["plugin"], REPO, REPO))
        sys.exit(2)

    ok("new_scene", {"confirm": True})

    # ---- 1. a rig carrying three clips AND a set-driven key ------------
    # Four joints: two carry clip motion, the fourth carries rig setup. They
    # must be different channels - a plug holds ONE input connection, so a
    # driven key and a clip curve cannot share one, and the defect needs both
    # kinds present on the SAME rig, which is what _joint_plugs sweeps.
    skel = ok("create_skeleton", {
        "chain": [[0, 0, 0], [0, 1, 0], [0, 2, 0], [0, 3, 0]],
        "chain_prefix": "g"})
    root = skel["root"]
    names = [j["name"] for j in skel["joints"]]
    check("setup: a four-joint chain exists", len(names) == 4,
          ", ".join(names))
    mid, tip, leaf = names[1], names[2], names[3]

    def clip(name, joint, angle):
        return ok("author_clip", {
            "root": root, "name": name, "fps": 30, "interpolation": "smooth",
            "keys": [{"time_s": 0.0, "rotations": {joint: [0, 0, 0]}},
                     {"time_s": 0.5, "rotations": {joint: [0, 0, angle]}},
                     {"time_s": 1.0, "rotations": {joint: [0, 0, 0]}}]})

    clip("idle", mid, 20)
    clip("wave", tip, 25)
    step = clip("step", mid, 12)
    check("setup: three clips on one rig",
          sorted(step.get("clips") or []) == ["idle", "step", "wave"],
          json.dumps(step.get("clips")))

    # The set-driven key: leaf.rotateX driven by a custom attribute on the
    # root. rotateX deliberately - a rotate CHILD is what the full teardown's
    # no-bind-pose fallback writes a compound setAttr over.
    sdk = py(
        "import maya.cmds as cmds\n"
        "root, leaf = %r, %r\n"
        "if not cmds.attributeQuery('sdk_drv', node=root, exists=True):\n"
        "    cmds.addAttr(root, ln='sdk_drv', at='double', dv=0.0, k=True)\n"
        "rest = cmds.getAttr(leaf + '.rotateX')\n"
        "cmds.setDrivenKeyframe(leaf + '.rotateX', cd=root + '.sdk_drv',\n"
        "                       dv=0.0, v=rest)\n"
        "cmds.setDrivenKeyframe(leaf + '.rotateX', cd=root + '.sdk_drv',\n"
        "                       dv=10.0, v=rest + 35.0)\n"
        "src = cmds.listConnections(leaf + '.rotateX', s=True, d=False) or []\n"
        "{'curve': src[0] if src else None,\n"
        " 'type': cmds.nodeType(src[0]) if src else None,\n"
        " 'rest': rest,\n"
        " 'keys': cmds.keyframe(src[0], q=True, valueChange=True) if src "
        "else None,\n"
        # floatChange is the DRIVER-value index of a U-typed curve - the axis
        # a time-range cutKey would mistake for time.
        " 'floats': cmds.keyframe(src[0], q=True, floatChange=True) if src "
        "else None}" % (root, leaf), "set-driven key")
    sdk_curve, sdk_type = sdk["curve"], sdk["type"]
    check("setup: the driven key is a U-typed curve Maya derives from "
          "animCurve", bool(sdk_curve) and str(sdk_type).startswith("animCurveU"),
          "%s is a %s" % (sdk_curve, sdk_type))
    # The whole defect rests on this: the teardown's own query must SEE it.
    seen_by_query = py(
        "import maya.cmds as cmds\n"
        "cmds.listConnections(%r + '.rotateX', s=True, d=False, "
        "type='animCurve') or []" % leaf, "type filter reach")
    check("the type='animCurve' filter really does match the U-typed node "
          "(this is why the teardown ate it)", seen_by_query == [sdk_curve],
          json.dumps(seen_by_query))

    # ---- 1b. RE-AUTHOR: a time-range cut against a driver-indexed curve --
    # The driven key's keys sit at DRIVER values 0 and 10. Re-authoring a clip
    # cuts its frame range - 0..30 here - over every joint plug, and those
    # numbers overlap. A cut that does not partition first destroys rig setup
    # while reporting a re-authored clip.
    reauth = ok("author_clip", {
        "root": root, "name": "step", "fps": 30, "interpolation": "smooth",
        "keys": [{"time_s": 0.0, "rotations": {mid: [0, 0, 0]}},
                 {"time_s": 0.5, "rotations": {mid: [0, 0, 24]}},
                 {"time_s": 1.0, "rotations": {mid: [0, 0, 0]}}]})
    check("setup: re-authoring 'step' replaced it rather than appending",
          sorted(reauth.get("clips") or []) == ["idle", "step", "wave"],
          json.dumps(reauth.get("clips")))
    after_cut = py(
        "import maya.cmds as cmds\n"
        "curve = %r\n"
        "{'alive': cmds.objExists(curve),\n"
        " 'keys': cmds.keyframe(curve, q=True, valueChange=True) "
        "if cmds.objExists(curve) else None,\n"
        " 'floats': cmds.keyframe(curve, q=True, floatChange=True) "
        "if cmds.objExists(curve) else None}" % sdk_curve,
        "sdk after a re-author cut")
    check("a re-author's time-range cut leaves the driver-indexed keys alone",
          after_cut["alive"] and after_cut["keys"] == sdk["keys"]
          and after_cut["floats"] == sdk["floats"],
          "before %s at %s, after %s at %s"
          % (json.dumps(sdk["keys"]), json.dumps(sdk["floats"]),
             json.dumps(after_cut["keys"]), json.dumps(after_cut["floats"])))

    # ---- 2. a PARTIAL delete: the #730 orphan reap ----------------------
    # Deleting 'wave' orphans tip's channels, so the reap runs - the branch
    # that classified curves it had already deleted and died on the second
    # nodeType. A green 'status ok' here IS the measurement.
    partial = ok("delete_clip", {"root": root, "name": "wave"})
    check("partial delete_clip survives the orphan reap",
          sorted(partial.get("clips") or []) == ["idle", "step"],
          json.dumps(partial.get("clips")))
    after_partial = py(
        "import maya.cmds as cmds\n"
        "leaf, curve = %r, %r\n"
        "src = cmds.listConnections(leaf + '.rotateX', s=True, d=False) or []\n"
        "{'alive': cmds.objExists(curve), 'src': src,\n"
        " 'keys': cmds.keyframe(curve, q=True, valueChange=True) "
        "if cmds.objExists(curve) else None}" % (leaf, sdk_curve),
        "sdk after partial delete")
    check("the driven key survives a partial delete untouched",
          after_partial["alive"] and after_partial["src"] == [sdk_curve]
          and after_partial["keys"] == sdk["keys"],
          json.dumps(after_partial))

    # ---- 3. the FULL teardown ------------------------------------------
    # This rig is unbound, so there is no bind pose and the teardown falls
    # into the rotation-zeroing branch - which writes the compound .rotate of
    # every joint, including the leaf whose rotateX an SDK curve still feeds.
    full = ok("delete_clip", {"root": root})
    warnings = full.get("warnings") or []
    print("   delete_clip warnings: %s" % json.dumps(warnings)[:600])
    check("full teardown completes on a rig whose rotate child is still "
          "connection-fed", True, "no RuntimeError from the compound setAttr")
    survived = py(
        "import maya.cmds as cmds\n"
        "root, leaf, curve = %r, %r, %r\n"
        "src = cmds.listConnections(leaf + '.rotateX', s=True, d=False) or []\n"
        "cmds.setAttr(root + '.sdk_drv', 10.0)\n"
        "driven_high = cmds.getAttr(leaf + '.rotateX')\n"
        "cmds.setAttr(root + '.sdk_drv', 0.0)\n"
        "driven_low = cmds.getAttr(leaf + '.rotateX')\n"
        "clip_curves = [c for j in %r for a in ('rotateX','rotateY','rotateZ')\n"
        "               for c in (cmds.listConnections(j + '.' + a, s=True,\n"
        "                         d=False, type='animCurve') or [])]\n"
        "{'alive': cmds.objExists(curve), 'src': src,\n"
        " 'high': driven_high, 'low': driven_low,\n"
        " 'remaining_curves': sorted(set(clip_curves)),\n"
        " 'meta': cmds.attributeQuery('mcp_clip', node=root, exists=True)}"
        % (root, leaf, sdk_curve, [mid, tip]), "sdk after full teardown")
    check("the set-driven key node survives the full teardown",
          survived["alive"] and survived["src"] == [sdk_curve],
          json.dumps({k: survived[k] for k in ("alive", "src")}))
    check("and it still DRIVES (the connection is live, not just present)",
          abs(survived["high"] - (sdk["rest"] + 35.0)) < 1e-3
          and abs(survived["low"] - sdk["rest"]) < 1e-3,
          "driver 10 -> %.3f, driver 0 -> %.3f"
          % (survived["high"], survived["low"]))
    check("every clip curve on the keyed joints is gone",
          survived["remaining_curves"] == [],
          json.dumps(survived["remaining_curves"]))
    check("the clip metadata is gone", not survived["meta"])
    check("deleted_curves counts only what was actually deleted",
          isinstance(full.get("deleted_curves"), int)
          and full["deleted_curves"] > 0,
          "deleted_curves=%s" % full.get("deleted_curves"))
    check("a warning names the driven-key curve left standing",
          any(sdk_curve in w for w in warnings),
          json.dumps(warnings)[:300])

    # ---- 4. author_clip is not locked out by a driven key --------------
    # The refusal loop the review measured: delete_clip refuses to remove an
    # SDK curve (correctly), so author_clip must not refuse BECAUSE of one, or
    # a rig carrying rig setup can never be given a first clip.
    reauthored = send("author_clip", {
        "root": root, "name": "again", "fps": 30,
        "keys": [{"time_s": 0.0, "rotations": {mid: [0, 0, 0]}},
                 {"time_s": 0.5, "rotations": {mid: [0, 0, 15]}}]})
    check("author_clip accepts a rig that carries a set-driven key",
          reauthored.get("status") == "ok",
          json.dumps(reauthored.get("error"))[:300])
    ok("delete_clip", {"root": root})

    # ---- 5. a curve hiding behind the pairBlend a constraint inserts ----
    # The driven key goes first, so that the ONLY thing left for the guard to
    # find is the curve behind the blend node - otherwise a refusal naming the
    # SDK curve would pass a check meant to prove the blend arm works.
    wiring = py(
        "import maya.cmds as cmds\n"
        "mid = %r\n"
        "if cmds.objExists(%r):\n"
        "    cmds.delete(%r)\n"
        "cmds.setKeyframe(mid + '.rotateZ', t=0, v=0.0)\n"
        "cmds.setKeyframe(mid + '.rotateZ', t=10, v=30.0)\n"
        "loc = cmds.spaceLocator(n='guard_target')[0]\n"
        "cmds.setAttr(loc + '.translateX', 2.0)\n"
        "cmds.orientConstraint(loc, mid, mo=False)\n"
        "direct = cmds.listConnections(mid + '.rotateZ', s=True, d=False,\n"
        "                              type='animCurve') or []\n"
        "src = cmds.listConnections(mid + '.rotateZ', s=True, d=False) or []\n"
        "{'direct_curves': direct, 'source': src[0] if src else None,\n"
        " 'source_type': cmds.nodeType(src[0]) if src else None}"
        % (mid, sdk_curve, sdk_curve), "pairBlend wiring")
    print("   constrained+keyed wiring: %s" % json.dumps(wiring))
    check("a constraint on a keyed plug really does hide the curve behind an "
          "intermediary (the premise of defect 2)",
          wiring["direct_curves"] == [] and wiring["source"] is not None,
          "source is a %s, direct animCurve query returns %s"
          % (wiring["source_type"], wiring["direct_curves"]))
    # Does a keyframe LAND on a plug the pairBlend feeds? #771 measured that
    # setKeyframe on a connection-fed plug returns 0 and creates nothing, but
    # a pairBlend is the one intermediary that exists precisely so a plug can
    # be keyed AND constrained - if the write lands here, author_clip must not
    # refuse this shape of rig, and if it does not, a clip authored on a
    # constrained joint has been silently empty all along.
    keyed_through = py(
        "import maya.cmds as cmds\n"
        "mid = %r\n"
        "src = cmds.listConnections(mid + '.rotateZ', s=True, d=False) or []\n"
        "before = cmds.keyframe(mid + '.rotateZ', q=True, timeChange=True) "
        "or []\n"
        "returned = cmds.setKeyframe(mid + '.rotateZ', t=20, v=45.0)\n"
        "after = cmds.keyframe(mid + '.rotateZ', q=True, timeChange=True) "
        "or []\n"
        "{'returned': returned, 'before': len(before), 'after': len(after),\n"
        " 'source_type': cmds.nodeType(src[0]) if src else None}" % mid,
        "setKeyframe through a pairBlend")
    check("MEASURED: does setKeyframe land through a %s?"
          % keyed_through["source_type"], True,
          "setKeyframe returned %s, keys %d -> %d"
          % (keyed_through["returned"], keyed_through["before"],
             keyed_through["after"]))

    err = refusal("pose_skeleton", {"root": root,
                                    "rotations": {mid: [0, 0, 10]}})
    text = json.dumps(err) if err else ""
    check("pose_skeleton refuses rather than writing a pose the hidden curve "
          "would override", err is not None, text[:300])
    check("the refusal names the intermediary the caller has to deal with",
          bool(wiring["source"]) and wiring["source"] in text,
          "looking for %r in %s" % (wiring["source"], text[:300]))
    # Not "delete_clip is unmentioned" - the honest hint DOES name it, to say
    # it will not help. What must be absent is the RECOMMENDATION, which is
    # what the guard used to give for every curve it found.
    check("and does NOT recommend delete_clip, which cannot reach a curve "
          "behind a blend node",
          "delete_clip removes the curves" not in text
          and "will NOT remove" in text, text[:400])

    # ---- 6. the anim-LAYER wiring, measured rather than believed --------
    # Review's open question: rotation layers connect the .rotate COMPOUND, and
    # a child-plug query cannot see a parent's connection - if so the guard
    # must reach the parent to cover layered rotations at all.
    layer = py(
        "import maya.cmds as cmds\n"
        "tip = %r\n"
        "for a in ('rotateX', 'rotateY', 'rotateZ'):\n"
        "    for c in cmds.listConnections(tip + '.' + a, s=True, d=False) "
        "or []:\n"
        "        cmds.delete(c)\n"
        "cmds.select(tip)\n"
        "lyr = cmds.animLayer('guardLayer', addSelectedObjects=True)\n"
        "cmds.animLayer(lyr, e=True, preferred=True)\n"
        "cmds.setKeyframe(tip + '.rotateY', t=0, v=0.0, animLayer=lyr)\n"
        "cmds.setKeyframe(tip + '.rotateY', t=10, v=25.0, animLayer=lyr)\n"
        "{'child_src': cmds.listConnections(tip + '.rotateY', s=True, d=False,"
        " p=True) or [],\n"
        " 'compound_src': cmds.listConnections(tip + '.rotate', s=True, "
        "d=False, p=True) or [],\n"
        " 'child_curves': cmds.listConnections(tip + '.rotateY', s=True, "
        "d=False, type='animCurve') or []}" % tip, "anim layer wiring")
    print("   anim-layer wiring: %s" % json.dumps(layer))
    check("MEASURED: where an anim layer connects (child vs compound)", True,
          "child=%s compound=%s" % (json.dumps(layer["child_src"]),
                                    json.dumps(layer["compound_src"])))
    layered = refusal("pose_skeleton", {"root": root,
                                        "rotations": {tip: [0, 5, 0]}})
    check("pose_skeleton refuses a joint whose rotation lives in an anim "
          "layer", layered is not None,
          json.dumps(layered)[:300] if layered else "it ACCEPTED the write")

    # ---- 7. the outside-wearer guard on a mirrored rig ------------------
    mirrored = py(
        "import maya.cmds as cmds\n"
        # '|limb' anchors at the root, so each group() call names exactly one
        # node: a bare 'limb' becomes ambiguous the moment the second cube
        # exists, which is the whole point of the scene being built.
        "cmds.polyCube(n='limb')\n"
        "cmds.group('|limb', n='left')\n"
        "cmds.polyCube(n='limb')\n"
        "cmds.group('|limb', n='right')\n"
        "left = cmds.listRelatives('|left|limb', shapes=True, "
        "fullPath=True)[0]\n"
        "right = cmds.listRelatives('|right|limb', shapes=True, "
        "fullPath=True)[0]\n"
        "sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,\n"
        "               name='limbSG')\n"
        "sh = cmds.shadingNode('lambert', asShader=True, name='limb_mat')\n"
        "cmds.connectAttr(sh + '.outColor', sg + '.surfaceShader', f=True)\n"
        "cmds.sets([left, right], e=True, forceElement=sg)\n"
        "{'left': left, 'right': right, 'sg': sg,\n"
        " 'members': cmds.sets(sg, q=True) or []}", "mirrored rig")
    print("   cmds.sets(sg, q=True) answered: %s"
          % json.dumps(mirrored["members"]))
    check("setup: two shapes under different parents share one short name",
          mirrored["left"].split("|")[-1] == mirrored["right"].split("|")[-1],
          "%s vs %s" % (mirrored["left"], mirrored["right"]))
    check("MEASURED: the member-name form the guard actually receives", True,
          json.dumps(mirrored["members"]))
    # An INSTANCE is one shape node under two paths - the case the guard must
    # NOT report, and the case whose whole treatment turns on what cmds.ls
    # answers for a node with several paths. The suite currently models ls as
    # returning them all; Maya may return one. Ask.
    instanced = py(
        "import maya.cmds as cmds\n"
        "cmds.polyCube(n='inst')\n"
        "cmds.instance('|inst', n='inst_copy')\n"
        "shp = cmds.listRelatives('|inst', shapes=True, fullPath=True)[0]\n"
        "leaf = shp.split('|')[-1]\n"
        # allPaths is asked defensively: an unknown flag would raise and take
        # the whole gate with it, and "that flag does not exist" is itself an
        # answer worth recording.
        "try:\n"
        "    allpaths = cmds.ls(leaf, long=True, allPaths=True) or []\n"
        "except Exception as exc:\n"
        "    allpaths = ['<raised> %s' % exc]\n"
        "{'shape': shp, 'leaf': leaf,\n"
        " 'ls_long': cmds.ls(leaf, long=True) or [],\n"
        " 'ls_allpaths': allpaths,\n"
        " 'uuids': (cmds.ls(leaf, uuid=True) or [])}", "instanced shape")
    print("   instanced shape resolution: %s" % json.dumps(instanced))
    check("MEASURED: cmds.ls(leaf, long=True) on an instanced shape returns "
          "%d path(s); allPaths returns %d"
          % (len(instanced["ls_long"]), len(instanced["ls_allpaths"])), True,
          json.dumps(instanced["ls_long"]))

    wearers = py(
        "from maya_plugin.handlers import texbake\n"
        "import maya.cmds as cmds\n"
        "{'outside': texbake._outside_wearers(cmds, %r, [%r]),\n"
        " 'both_named': texbake._outside_wearers(cmds, %r, [%r, %r]),\n"
        " 'module': texbake.__file__}"
        % (mirrored["sg"], mirrored["left"], mirrored["sg"],
           mirrored["left"], mirrored["right"]), "outside wearers")
    check("the mirrored twin IS reported as an outside wearer",
          wearers["outside"] == [mirrored["right"]],
          json.dumps(wearers["outside"]))
    check("and naming both meshes reports nobody outside",
          wearers["both_named"] == [], json.dumps(wearers["both_named"]))

    # ---- 8. the BOUND teardown: dagPose restore vs a connected plug -----
    # The no-bind-pose fallback is the RARE branch. Any rig with a skinCluster
    # has a bind pose, so `dagPose(restore=True)` is what the common teardown
    # actually writes - and nothing in this repo has ever measured what it
    # does when one of those rotate channels is fed by a surviving driven key.
    # Both outcomes need different handling, so the gate asks rather than
    # assumes: does it RAISE (a teardown dying after it has already deleted
    # the curves) or SKIP (a result claiming a bind restore that half happened)?
    ok("new_scene", {"confirm": True})
    skel2 = ok("create_skeleton", {
        "chain": [[0, 0, 0], [0, 1, 0], [0, 2, 0]], "chain_prefix": "b"})
    root2 = skel2["root"]
    bnames = [j["name"] for j in skel2["joints"]]
    bmid, btip = bnames[1], bnames[2]
    py("import maya.cmds as cmds\n"
       "m = cmds.polyCylinder(name='bind_tube', radius=0.3, height=2.0,\n"
       "                      subdivisionsY=6, ch=False)[0]\n"
       "cmds.xform(m, worldSpace=True, translation=[0, 1.0, 0])\n"
       "m", "bound mesh")
    bind = ok("bind_skin", {"mesh": "|bind_tube", "root": root2})
    check("setup: the mesh is bound with every vertex owned",
          bind.get("unweighted_vertices") == 0,
          "unweighted=%s" % bind.get("unweighted_vertices"))
    ok("author_clip", {
        "root": root2, "name": "idle", "fps": 30,
        "keys": [{"time_s": 0.0, "rotations": {bmid: [0, 0, 0]}},
                 {"time_s": 0.5, "rotations": {bmid: [0, 0, 18]}}]})
    sdk2 = py(
        "import maya.cmds as cmds\n"
        "root, tip = %r, %r\n"
        "cmds.addAttr(root, ln='sdk_drv', at='double', dv=0.0, k=True)\n"
        "rest = cmds.getAttr(tip + '.rotateX')\n"
        "cmds.setDrivenKeyframe(tip + '.rotateX', cd=root + '.sdk_drv',\n"
        "                       dv=0.0, v=rest)\n"
        "cmds.setDrivenKeyframe(tip + '.rotateX', cd=root + '.sdk_drv',\n"
        "                       dv=10.0, v=rest + 20.0)\n"
        "src = cmds.listConnections(tip + '.rotateX', s=True, d=False) or []\n"
        "{'curve': src[0] if src else None,\n"
        " 'poses': cmds.dagPose(root, q=True, bindPose=True) or []}"
        % (root2, btip), "bound rig driven key")
    check("setup: this rig HAS a bind pose (so the common branch runs)",
          bool(sdk2["poses"]), json.dumps(sdk2["poses"]))
    bound = send("delete_clip", {"root": root2})
    check("the bound teardown completes with a connection-fed rotate child",
          bound.get("status") == "ok",
          json.dumps(bound.get("error"))[:400])
    if bound.get("status") == "ok":
        bw = (bound.get("result") or {}).get("warnings") or []
        print("   bound teardown warnings: %s" % json.dumps(bw)[:600])
        after_bound = py(
            "import maya.cmds as cmds\n"
            "root, tip, curve = %r, %r, %r\n"
            "src = cmds.listConnections(tip + '.rotateX', s=True, d=False) "
            "or []\n"
            "cmds.setAttr(root + '.sdk_drv', 10.0)\n"
            "high = cmds.getAttr(tip + '.rotateX')\n"
            "cmds.setAttr(root + '.sdk_drv', 0.0)\n"
            "{'alive': cmds.objExists(curve), 'src': src, 'high': high}"
            % (root2, btip, sdk2["curve"]), "sdk after bound teardown")
        check("the driven key survives the bound teardown and still drives",
              after_bound["alive"] and after_bound["src"] == [sdk2["curve"]]
              and after_bound["high"] > 15.0, json.dumps(after_bound))
    # The isolated question, asked directly - this is the measurement that
    # tells a future reader which branch the handler has to defend against.
    dagpose = py(
        "import maya.cmds as cmds\n"
        "root, tip = %r, %r\n"
        "poses = cmds.dagPose(root, q=True, bindPose=True) or []\n"
        "before = cmds.getAttr(tip + '.rotateX')\n"
        "raised = None\n"
        "try:\n"
        "    cmds.dagPose(poses[0], restore=True, g=True)\n"
        "except Exception as exc:\n"
        "    raised = '%%s: %%s' %% (type(exc).__name__, exc)\n"
        "{'raised': raised, 'before': before,\n"
        " 'after': cmds.getAttr(tip + '.rotateX')}" % (root2, btip),
        "dagPose vs a connected plug")
    check("MEASURED: dagPose restore against a connection-fed rotate child",
          True, "raised=%r, %.3f -> %.3f" % (dagpose["raised"],
                                             dagpose["before"],
                                             dagpose["after"]))

    # ---- 9. author_clip refuses the channels the driven key OWNS --------
    # Round 2 stopped a driven key ANYWHERE on the rig from blocking a clip;
    # the channel it actually feeds must still refuse, or author_clip writes a
    # keyframe that measurably never lands and reports success anyway.
    clash = send("author_clip", {
        "root": root2, "name": "clash", "fps": 30,
        "keys": [{"time_s": 0.0, "rotations": {btip: [0, 0, 0]}},
                 {"time_s": 0.5, "rotations": {btip: [10, 0, 0]}}]})
    clash_text = json.dumps(clash.get("error")) if clash.get("status") != "ok" \
        else ""
    check("author_clip refuses a channel a set-driven key feeds",
          clash.get("status") != "ok", json.dumps(clash)[:300])
    check("and the refusal names the channel or its curve",
          bool(clash_text) and (btip.split("|")[-1] in clash_text
                                or str(sdk2["curve"]) in clash_text),
          clash_text[:300])
    free = send("author_clip", {
        "root": root2, "name": "free", "fps": 30,
        "keys": [{"time_s": 0.0, "rotations": {bmid: [0, 0, 0]}},
                 {"time_s": 0.5, "rotations": {bmid: [0, 0, 12]}}]})
    check("but a clip on the OTHER channels is still accepted",
          free.get("status") == "ok",
          json.dumps(free.get("error"))[:300])
    if free.get("status") == "ok":
        landed = py(
            "import maya.cmds as cmds\n"
            "[c for a in ('rotateX', 'rotateY', 'rotateZ')\n"
            " for c in (cmds.listConnections(%r + '.' + a, s=True, d=False,\n"
            "           type='animCurve') or [])]" % bmid, "clip landed")
        check("and that clip's keys really landed (not a silent no-op)",
              bool(landed), json.dumps(landed))
        # The handler now READS setKeyframe's return to decide what it claims
        # it keyed. That only works if the number means what #771 measured, so
        # ask what a REDUNDANT key returns: a back-fill re-pins frames that
        # can already hold an identical key, and a 0 there would report a
        # healthy rig as broken.
        redundant = py(
            "import maya.cmds as cmds\n"
            "plug = %r + '.rotateZ'\n"
            "frames = cmds.keyframe(plug, q=True, timeChange=True) or []\n"
            "if not frames:\n"
            "    out = {'skipped': 'no keys on the plug'}\n"
            "else:\n"
            "    f = frames[0]\n"
            "    v = (cmds.keyframe(plug, q=True, time=(f, f),\n"
            "                       valueChange=True) or [0.0])[0]\n"
            "    first = cmds.setKeyframe(plug, t=f, v=v)\n"
            "    again = cmds.setKeyframe(plug, t=f, v=v)\n"
            "    out = {'existing_frames': len(frames), 'value': v,\n"
            "           'returned_first': first, 'returned_again': again}\n"
            "out" % bmid, "redundant setKeyframe")
        check("MEASURED: what setKeyframe returns for a key that already "
              "exists with the same value", True, json.dumps(redundant))

    failed = [label for passed, label in CHECKS if not passed]
    print("\n%d/%d passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
