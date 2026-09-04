"""Throwaway probe for #829: what do rename, reset_namespace and set_viewport
actually DO in a real Maya? Nobody has ever asked them.

They are the last three commands with no live caller (#818 audit, item 6), so
everything believed about them comes from unit tests against fakes - and #799
measured what that is worth. Written BEFORE any design: this only asks
questions, it asserts nothing.

  A  rename        - the shape, a taken name, descendants, the ledger, names
                     Maya will not accept, a shape, a bound joint, a shaded mesh
  B  reset_namespace - is the execute_python namespace really gone afterwards
  C  set_viewport  - does what it REPORTS match what the viewport DRAWS, and
                     does a capture (which restores panel state) undo it

Run:  MAYA_MCP_PORT=9878 MAYA_MCP_EXPECT_PID=<pid> python evals/uncalled_trio_probe_829.py

MUTATES THE ANSWERING MAYA'S SCENE. Refuses 9877.
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import textwrap

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877:
    raise SystemExit("refusing 9877 - that is the user's Maya")
OUT = os.path.join(_HERE, "uncalled_trio_probe_829")
os.makedirs(OUT, exist_ok=True)
FINDINGS: dict = {}


def raw(command: str, params: dict, timeout_s: float = 180.0) -> dict:
    """The whole response frame - a refusal is a measurement here, not a stop."""
    return call(command, params, timeout_s=timeout_s, port=PORT)


def ok(command: str, params: dict, timeout_s: float = 180.0) -> dict:
    frame = raw(command, params, timeout_s)
    if frame.get("status") != "ok":
        raise SystemExit("%s failed: %s"
                         % (command, json.dumps(frame.get("error"), indent=1)))
    return frame.get("result") or {}


def outcome(command: str, params: dict) -> dict:
    """What a caller sees: the result, or the refusal, whichever came back."""
    frame = raw(command, params)
    if frame.get("status") == "ok":
        return {"ok": True, "result": frame.get("result")}
    err = frame.get("error") or {}
    return {"ok": False, "error": err.get("message"), "hint": err.get("hint")}


def py(code: str, timeout_s: float = 180.0):
    body = textwrap.dedent(code).strip() + "\nr"
    res = ok("execute_python", {"code": body}, timeout_s=timeout_s)
    if res.get("traceback"):
        raise SystemExit("execute_python raised:\n" + res["traceback"])
    return structured_result(res, "r")


def show(label: str, value) -> None:
    FINDINGS[label] = value
    with open(os.path.join(OUT, "findings.json"), "w", encoding="utf-8") as fh:
        json.dump(FINDINGS, fh, indent=1, default=str)
    print("\n--- %s ---" % label)
    print(json.dumps(value, indent=1, sort_keys=True, default=str))


def opaque(png_b64: str, name: str = None) -> dict:
    from PIL import Image
    img = Image.open(io.BytesIO(base64.b64decode(png_b64))).convert("RGBA")
    if name:
        img.save(os.path.join(OUT, name + ".png"))
    px = list(img.getdata())
    op = [p for p in px if p[3] > 0]
    return {"opaque": len(op), "total": len(px),
            "distinct": len(set(px))}


LIB = r'''
import maya.cmds as cmds
from maya_plugin.handlers import ledger as _ledger


DEFAULT_ASSEMBLIES = ("persp", "top", "front", "side")


def user_assemblies():
    """Top-level nodes somebody made - never Maya's four default cameras.

    cmds.ls(assemblies=True) includes them, and they are READ ONLY: renaming
    one raises "Cannot rename a read only node", which is how this probe's
    first run died.
    """
    return sorted(n for n in (cmds.ls(assemblies=True) or [])
                  if n not in DEFAULT_ASSEMBLIES)


def wipe():
    junk = user_assemblies()
    if junk:
        cmds.delete(junk)
    return user_assemblies()


def one_victim():
    wipe()
    cmds.polyCube(name="victim")
    return user_assemblies()


def node_state(name):
    """Everything a caller might later hold a name of."""
    if not cmds.objExists(name):
        return {"exists": False}
    long_name = (cmds.ls(name, long=True) or [None])[0]
    shapes = cmds.listRelatives(long_name, shapes=True, fullPath=True) or []
    kids = cmds.listRelatives(long_name, children=True, fullPath=True) or []
    return {"exists": True, "long": long_name, "shapes": shapes,
            "shape_short": [s.split("|")[-1] for s in shapes],
            "children": kids, "type": cmds.nodeType(long_name)}


def ledger_keys():
    return sorted(_ledger._written)


def shading_groups(mesh):
    shapes = cmds.listRelatives(mesh, shapes=True, fullPath=True) or []
    if not shapes:
        return []
    return sorted(set(cmds.listConnections(shapes[0], type="shadingEngine") or []))


def panel_flags():
    from maya_plugin.handlers.capture import find_model_panel
    p = find_model_panel(cmds)
    return {"panel": p,
            "grid": cmds.modelEditor(p, q=True, grid=True),
            "wireframeOnShaded": cmds.modelEditor(p, q=True, wireframeOnShaded=True),
            "displayLights": cmds.modelEditor(p, q=True, displayLights=True),
            "camera": cmds.modelPanel(p, q=True, camera=True)}
'''


def section_a_rename():
    ok("new_scene", {"confirm": True})
    py(LIB + "\nr = 1")

    # A1 the shape under a renamed transform
    ok("create_primitive", {"kind": "cube", "name": "lamp_base"})
    before = py("r = node_state('lamp_base')")
    res = ok("rename", {"name": "lamp_base", "new_name": "base"})
    after = py("r = node_state('base')")
    show("A1 rename a transform: what happens to its shape", {
        "handler_result": res,
        "before": before,
        "after": after,
        "shape_still_named_after_the_old_transform":
            any("lamp_base" in s for s in after.get("shape_short") or []),
    })

    # A2 a name that is already taken
    ok("create_primitive", {"kind": "cube", "name": "arm"})
    ok("create_primitive", {"kind": "sphere", "name": "shade"})
    taken = ok("rename", {"name": "shade", "new_name": "arm"})
    show("A2 rename onto a name that exists", {
        "handler_result": taken,
        "asked_for": "arm",
        "got": taken.get("name"),
        "warnings": taken.get("warnings"),
        "scene": py("r = user_assemblies()"),
    })

    # A3 a renamed PARENT, its descendants and the ledger
    ok("new_scene", {"confirm": True})
    py(LIB + "\nr = 1")
    ok("create_primitive", {"kind": "cube", "name": "kid_a"})
    ok("create_primitive", {"kind": "cube", "name": "kid_b"})
    # transform writes are what the ledger records
    ok("transform", {"names": ["kid_a"], "translate": [1, 0, 0]})
    ok("transform", {"names": ["kid_b"], "translate": [0, 1, 0]})
    grp = ok("group", {"names": ["kid_a", "kid_b"], "group_name": "rig"})
    before_keys = py("r = ledger_keys()")
    renamed = ok("rename", {"name": grp.get("name") or "rig",
                            "new_name": "lamp_rig"})
    after_keys = py("r = ledger_keys()")
    kids_now = py("r = node_state('lamp_rig')")
    show("A3 renaming a parent: descendant paths and the ledger", {
        "handler_result": renamed,
        "ledger_before": before_keys,
        "ledger_after": after_keys,
        "children_now": kids_now.get("children"),
        "ledger_keys_that_no_longer_exist":
            py("r = [k for k in ledger_keys() if not cmds.objExists(k)]"),
    })

    # A3b does a stale ledger key attach itself to a NEW node of that name?
    ok("create_primitive", {"kind": "cube", "name": "kid_a"})
    show("A3b a new node reusing a renamed node's old name", {
        "ledger_keys": py("r = ledger_keys()"),
        "new_node": py("r = node_state('kid_a')"),
        "ledger_check_on_it": py(
            "r = str(_ledger.check(cmds, (cmds.ls('kid_a', long=True) or [''])[0]))"),
    })

    # A4 names Maya will not take
    ok("new_scene", {"confirm": True})
    py(LIB + "\nr = 1")
    bad = {}
    for label, requested in [("space", "my lamp"), ("leading_digit", "2lamp"),
                             ("pipe", "a|b"), ("colon", "ns:lamp"),
                             ("empty", "   "), ("dash", "lamp-01"),
                             ("unicode", "lampé")]:
        # A fresh victim per case, so one case's outcome cannot colour the next.
        py("r = one_victim()")
        bad[label] = outcome("rename", {"name": "victim", "new_name": requested})
        bad[label]["scene_after"] = py("r = user_assemblies()")
    show("A4 names Maya may not accept", bad)

    # A5 renaming a shape node directly
    py("r = one_victim()")
    shape = py("r = (cmds.listRelatives('victim', shapes=True, fullPath=True) or [''])[0]")
    show("A5 rename a SHAPE directly", {
        "shape": shape,
        "outcome": outcome("rename", {"name": shape, "new_name": "victimShape_x"}),
        "state": py("r = node_state('victim')"),
    })

    # A6 a joint a skinCluster binds, and A7 a mesh with a material
    ok("new_scene", {"confirm": True})
    py(LIB + "\nr = 1")
    ok("create_primitive", {"kind": "cube", "name": "skin_me",
                            "scale": [1, 4, 1], "subdivisions": [2, 6, 2]})
    ok("create_skeleton", {"joints": [
        {"name": "root_jnt", "position": [0, -2, 0]},
        {"name": "tip_jnt", "position": [0, 2, 0], "parent": "root_jnt"}]})
    ok("bind_skin", {"mesh": "skin_me", "root": "root_jnt"})
    ok("assign_material", {"mesh": "skin_me", "shader": "standardSurface",
                           "name": "lamp_mat"})
    before_sg = py("r = shading_groups('skin_me')")
    joint_res = outcome("rename", {"name": "root_jnt", "new_name": "hip_jnt"})
    mesh_res = outcome("rename", {"name": "skin_me", "new_name": "lamp_mesh"})
    show("A6/A7 a bound joint and a shaded mesh", {
        "joint_rename": joint_res,
        "mesh_rename": mesh_res,
        "shading_groups_before": before_sg,
        "shading_groups_after": py("r = shading_groups('lamp_mesh')"),
        "skin_still_bound": py(
            "r = bool(cmds.ls(cmds.listHistory('lamp_mesh') or [], type='skinCluster'))"),
        "skin_influences": py(
            "sc = (cmds.ls(cmds.listHistory('lamp_mesh') or [], type='skinCluster') or [None])[0]\n"
            "r = sorted(cmds.skinCluster(sc, q=True, influence=True)) if sc else None"),
        "weight_report": outcome("weight_report", {"mesh": "lamp_mesh"}),
    })


def section_b_reset_namespace():
    defined = py("probe_marker_829 = 41 + 1\nr = probe_marker_829")
    still = py("r = probe_marker_829")
    reset = outcome("reset_namespace", {})
    gone = raw("execute_python", {"code": "r = probe_marker_829\nr"})
    after = gone.get("result") or {}
    rebuilt = py("r = str(type(cmds))")
    show("B reset_namespace end to end", {
        "defined": defined,
        "survived_the_next_call": still,
        "reset_result": reset,
        "reading_it_after_reset": {
            "status": gone.get("status"),
            "traceback_tail": (after.get("traceback") or "").strip().splitlines()[-1:]
            if after.get("traceback") else None,
            "error": (gone.get("error") or {}).get("message"),
        },
        "cmds_available_again": rebuilt,
        "refuses_any_param": outcome("reset_namespace", {"confirm": True}),
    })


def section_c_set_viewport():
    ok("new_scene", {"confirm": True})
    py(LIB + "\nr = 1")
    ok("create_primitive", {"kind": "cube", "name": "subject"})

    query_only = outcome("set_viewport", {})
    show("C1 set_viewport as a pure query", {
        "result": query_only,
        "maya_says": py("r = panel_flags()"),
    })

    grid_off = ok("set_viewport", {"show_grid": False})
    shot_off = ok("capture_viewport", {"angles": ["front"], "resolution": 256})
    grid_on = ok("set_viewport", {"show_grid": True})
    shot_on = ok("capture_viewport", {"angles": ["front"], "resolution": 256})
    px_off = opaque(shot_off["images"][0]["png_b64"], "C2_grid_off")
    px_on = opaque(shot_on["images"][0]["png_b64"], "C2_grid_on")
    show("C2 does a reported flag reach the pixels", {
        "reported_off": grid_off.get("show_grid"),
        "reported_on": grid_on.get("show_grid"),
        "pixels_grid_off": px_off,
        "pixels_grid_on": px_on,
        "the_capture_can_see_the_grid_at_all": px_off != px_on,
    })

    before_capture = py("r = panel_flags()")
    ok("capture_viewport", {"angles": ["three_quarter"], "resolution": 192})
    show("C3 does a capture survive the persistent settings", {
        "panel_before_capture": before_capture,
        "panel_after_capture": py("r = panel_flags()"),
        "set_viewport_says_after": outcome("set_viewport", {}),
    })

    lights = {}
    for mode in ("default", "all", "active", "flat", "none", "nonsense"):
        lights[mode] = outcome("set_viewport", {"display_lights": mode})
        lights[mode]["maya_says"] = py("r = panel_flags()['displayLights']")
    show("C4 display_lights round trip", lights)

    show("C5 the camera name it reports", {
        "set_viewport": outcome("set_viewport", {}),
        "modelPanel_short_name": py("r = panel_flags()['camera']"),
    })

    # C7 asked because a capture of the vendored agent's finished lamp came
    # back with a wireframe overlay NOBODY ASKED FOR in that call. A capture
    # is supposed to restore every panel setting it touches - so does
    # wireframe_overlay leak into the next capture?
    py("r = panel_flags()")
    plain_before = opaque(
        ok("capture_viewport", {"angles": ["front"], "resolution": 256}
           )["images"][0]["png_b64"], "C7_plain_before")
    over = ok("capture_viewport", {"angles": ["front"], "resolution": 256,
                                   "wireframe_overlay": True})
    flags_after = py("r = panel_flags()")
    plain_after = opaque(
        ok("capture_viewport", {"angles": ["front"], "resolution": 256}
           )["images"][0]["png_b64"], "C7_plain_after")
    show("C7 does a wireframe overlay leak into the NEXT capture", {
        "plain_before": plain_before,
        "with_overlay": opaque(over["images"][0]["png_b64"], "C7_with_overlay"),
        "plain_after": plain_after,
        "panel_flags_after_the_overlay_capture": flags_after,
        "the_next_plain_capture_differs_from_the_first":
            plain_before != plain_after,
    })

    wos = ok("set_viewport", {"wireframe_on_shaded": True})
    shot = ok("capture_viewport", {"angles": ["front"], "resolution": 256})
    show("C6 wireframe_on_shaded in the pixels", {
        "reported": wos.get("wireframe_on_shaded"),
        "pixels": opaque(shot["images"][0]["png_b64"], "C6_wireframe_on_shaded"),
        "vs_plain_shaded": px_on,
    })
    ok("set_viewport", {"wireframe_on_shaded": False})


def main():
    print("### probe 829 on port %s" % PORT)
    ping = ok("ping", {})
    print("answering Maya: pid %s" % (ping.get("process") or {}).get("pid"))
    section_a_rename()
    section_b_reset_namespace()
    section_c_set_viewport()
    print("\nfindings written to %s" % os.path.join(OUT, "findings.json"))


if __name__ == "__main__":
    main()
