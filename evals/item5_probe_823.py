"""#823 PROBE: set_camera, group and capture_viewport angle=back, none of which
a gate has ever exercised functionally. Records, does not assert.

set_camera
  C1 fresh camera at (0,0,10) look_at origin, focal 35: result, the camera's
     ACTUAL view direction (world -Z of its matrix) against the vector to
     look_at, the focalLength attr, which camera the panel looks through
  C2 the same aim test from (10,0,0), (0,10,0), (5,5,5), (-3,2,-7) at an
     off-origin look_at - the look_at_rotation convention end to end
  C3 set_active=False leaves the panel's camera alone
  C4 a second call reuses the camera (warning) and moves it
  C5 camera="persp": Maya's own camera is moved
  C6 focal_length alone
  C7 PIXELS: red cube at +Z, blue cube at -Z; set_camera at +Z then capture
     angles=["current"] -> red dominates; set_camera at -Z -> blue

capture_viewport
  K1 the same scene, angles front/side/back: which colour dominates each,
     the reported camera positions/rotations
  K2 back with target=|red

group
  G1 two cubes at x=2 and x=4 grouped: the group's pivot and translate, the
     children's paths and world positions; then transform rotate [0,90,0] on
     the group - where the children end up (bbox-centre pivot vs origin)
  G2 a child that already has a parent: path after, world position kept?,
     the old parent left behind
  G3 group_name already taken: the reported name, any warning
  G4 a rotated+scaled member: world transform preserved?
  G5 grouping a group (nesting)
  G6 duplicate entries in names; two members with the same short name from
     different parents

Run:  MAYA_MCP_PORT=9878 python evals/item5_probe_823.py
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
    raise SystemExit("refusing the user's Maya")
OUT = os.path.join(_HERE, "item5_probe_823")
os.makedirs(OUT, exist_ok=True)
FINDINGS = {}


def ok(command, params, timeout_s=300.0):
    r = call(command, params, timeout_s=timeout_s, port=PORT)
    if r.get("status") != "ok":
        raise SystemExit("%s failed: %s" % (command, json.dumps(r.get("error"), indent=1)))
    return r.get("result") or {}


def result_or_error(command, params, timeout_s=300.0):
    r = call(command, params, timeout_s=timeout_s, port=PORT)
    return (r.get("result") or {}) if r.get("status") == "ok" else {"ERROR": r.get("error")}


def py(code, what="r", timeout_s=300.0):
    code = textwrap.dedent(code).strip()
    code += "\nr" if ("r =" in code or "r=" in code) else "\nr = 0\nr"
    res = ok("execute_python", {"code": code}, timeout_s)
    if res.get("traceback"):
        raise SystemExit("execute_python raised:\n" + res["traceback"])
    return structured_result(res, what)


def show(label, value):
    FINDINGS[label] = value
    with open(os.path.join(OUT, "findings.json"), "w", encoding="utf-8") as fh:
        json.dump(FINDINGS, fh, indent=1, default=str)
    print("\n--- %s ---" % label)
    print(json.dumps(value, indent=1, sort_keys=True, default=str))


def colours(png_b64, name):
    """Dominant colour of a capture: red / blue / neither pixel counts."""
    import numpy as np
    from PIL import Image
    img = Image.open(io.BytesIO(base64.b64decode(png_b64))).convert("RGB")
    img.save(os.path.join(OUT, name + ".png"))
    a = np.asarray(img).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    red = int(((r > 120) & (g < 90) & (b < 90)).sum())
    blue = int(((b > 120) & (r < 90) & (g < 90)).sum())
    return {"red_px": red, "blue_px": blue, "size": list(img.size),
            "dominant": "red" if red > blue * 1.5 else ("blue" if blue > red * 1.5 else "neither")}


LIB = r'''
import maya.cmds as cmds
import maya.api.OpenMaya as om

def view_check(cam, look_at):
    """dot(camera's world -Z, unit(look_at - position)); 1.0 = aimed exactly."""
    m = om.MMatrix(cmds.xform(cam, q=True, ws=True, m=True))
    fwd = om.MVector(-m[8], -m[9], -m[10]).normal()
    pos = om.MVector(*cmds.xform(cam, q=True, ws=True, t=True))
    to = (om.MVector(*look_at) - pos).normal()
    return round(fwd * to, 6)

def cam_state(cam):
    sh = cmds.listRelatives(cam, s=True, f=True)[0]
    panel = [p for p in cmds.getPanel(type="modelPanel") if cmds.modelPanel(p, q=True, camera=True)]
    return {"t": [round(v, 4) for v in cmds.xform(cam, q=True, ws=True, t=True)],
            "ro": [round(v, 4) for v in cmds.xform(cam, q=True, ws=True, ro=True)],
            "focal": cmds.getAttr(sh + ".focalLength"),
            "panel_cameras": {p: cmds.modelPanel(p, q=True, camera=True) for p in panel}}

def node_state(t):
    return {"exists": cmds.objExists(t),
            "ws_t": [round(v, 4) for v in cmds.xform(t, q=True, ws=True, t=True)] if cmds.objExists(t) else None,
            "ws_ro": [round(v, 4) for v in cmds.xform(t, q=True, ws=True, ro=True)] if cmds.objExists(t) else None,
            "local_t": [round(v, 4) for v in cmds.xform(t, q=True, r=True, t=True)] if cmds.objExists(t) else None,
            "ws_s": [round(v, 4) for v in cmds.xform(t, q=True, ws=True, s=True)] if cmds.objExists(t) else None,
            "pivot": [round(v, 4) for v in cmds.xform(t, q=True, ws=True, rp=True)] if cmds.objExists(t) else None,
            "children": cmds.listRelatives(t, c=True, f=True, type="transform") if cmds.objExists(t) else None}

def red_blue_scene():
    cmds.file(new=True, force=True)
    r = cmds.polyCube(name="red", w=1, h=1, d=1, ch=False)[0]; cmds.xform(r, ws=True, t=[0, 0, 1.2])
    b = cmds.polyCube(name="blue", w=1, h=1, d=1, ch=False)[0]; cmds.xform(b, ws=True, t=[0, 0, -1.2])
    for name, col in ((r, (1, 0, 0)), (b, (0, 0, 1))):
        sh = cmds.shadingNode("lambert", asShader=True, name=name + "_mat")
        cmds.setAttr(sh + ".color", *col, type="double3")
        sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=sh + "SG")
        cmds.connectAttr(sh + ".outColor", sg + ".surfaceShader")
        cmds.sets(name, e=True, forceElement=sg)
    return [cmds.ls(r, long=True)[0], cmds.ls(b, long=True)[0]]
'''


def main():
    py(LIB + "\nr = 1")

    # ---------------------------------------------------------------- C
    ok("new_scene", {"confirm": True}); py(LIB + "\nr = 1")
    res = result_or_error("set_camera", {"position": [0, 0, 10], "look_at": [0, 0, 0], "focal_length": 35})
    show("C1_fresh_camera", {"result": res, "aim_dot": py("r = view_check('|mcpCam', [0, 0, 0])", "r"),
                             "state": py("r = cam_state('|mcpCam')", "r")})
    c2 = {}
    for pos in ([10, 0, 0], [0, 10, 0], [5, 5, 5], [-3, 2, -7], [0, -6, 0.001]):
        res = result_or_error("set_camera", {"position": pos, "look_at": [1, 0.5, -2]})
        c2[str(pos)] = {"rotation": res.get("rotation"), "aim_dot": py("r = view_check('|mcpCam', [1, 0.5, -2])", "r"), "warnings": res.get("warnings")}
    show("C2_aim_from_five_positions", c2)
    before = py("r = cam_state('|mcpCam')['panel_cameras']", "r")
    py("cmds.lookThru('persp'); r = 1")
    res = result_or_error("set_camera", {"position": [0, 0, 5], "look_at": [0, 0, 0], "set_active": False})
    show("C3_set_active_false", {"panel_cameras_after": py("r = cam_state('|mcpCam')['panel_cameras']", "r"), "result": res})
    res = result_or_error("set_camera", {"camera": "persp", "position": [0, 0, 12], "look_at": [0, 0, 0]})
    show("C5_persp", {"result": res, "state": py("r = cam_state('|persp')", "r")})
    res = result_or_error("set_camera", {"focal_length": 85})
    show("C6_focal_only", {"result": res, "state": py("r = cam_state('|mcpCam')", "r")})
    bad = {}
    for label, params in (("no_params", {}), ("position_only", {"position": [1, 2, 3]}),
                          ("coincident", {"position": [0, 0, 0], "look_at": [0, 0, 0]}),
                          ("focal_zero", {"focal_length": 0}), ("focal_negative", {"focal_length": -5}),
                          ("focal_string", {"focal_length": "35"}), ("position_2d", {"position": [1, 2]})):
        r = result_or_error("set_camera", params)
        bad[label] = {"ERROR": (r.get("ERROR") or {}).get("message", "")[:160]} if "ERROR" in r else {"ok": {k: r.get(k) for k in ("position", "rotation", "warnings")}}
    show("C8_edge_params", bad)

    # C7 pixels
    ok("new_scene", {"confirm": True}); py(LIB + "\nr = 1")
    red, blue = py("r = red_blue_scene()", "r")
    c7 = {}
    for label, pos in (("from_plus_z", [0, 0, 8]), ("from_minus_z", [0, 0, -8])):
        ok("set_camera", {"position": pos, "look_at": [0, 0, 0]})
        shot = ok("capture_viewport", {"angles": ["current"], "shading": "flatShaded", "resolution": 256})
        c7[label] = {"colours": colours(shot["images"][0]["png_b64"], "C7_" + label), "camera": shot["camera_positions"][0], "warnings": shot["warnings"]}
    show("C7_pixels_after_set_camera", c7)

    # ---------------------------------------------------------------- K
    k1 = {}
    shot = ok("capture_viewport", {"angles": ["front", "side", "back", "top"], "shading": "flatShaded", "resolution": 256})
    for img, cam in zip(shot["images"], shot["camera_positions"]):
        k1[img["angle"]] = {"colours": colours(img["png_b64"], "K1_" + img["angle"]), "camera": {"position": [round(v, 3) for v in cam["position"]], "rotation": [round(v, 3) for v in cam["rotation"]]}, "blank": img["blank"]}
    k1["warnings"] = shot["warnings"]
    show("K1_front_side_back_top", k1)
    shot = ok("capture_viewport", {"angles": ["back"], "target": red, "shading": "flatShaded", "resolution": 256})
    show("K2_back_target_red", {"colours": colours(shot["images"][0]["png_b64"], "K2_back_target_red"), "camera": shot["camera_positions"][0], "warnings": shot["warnings"]})
    after = py("r = {'cameras': cmds.ls(type='camera'), 'panel': cam_state('|persp')['panel_cameras']}", "r")
    show("K3_scene_after_captures", after)

    # ---------------------------------------------------------------- G
    ok("new_scene", {"confirm": True}); py(LIB + "\nr = 1")
    ok("create_primitive", {"kind": "cube", "name": "a", "translate": [2, 0, 0]})
    ok("create_primitive", {"kind": "cube", "name": "b", "translate": [4, 0, 0]})
    res = result_or_error("group", {"names": ["|a", "|b"], "group_name": "pair"})
    g1 = {"result": res, "group": py("r = node_state('|pair')", "r"),
          "a": py("r = node_state('|pair|a')", "r"), "b": py("r = node_state('|pair|b')", "r")}
    tr = result_or_error("transform", {"names": ["|pair"], "rotate": [0, 90, 0]})
    g1["after_rotate_90"] = {"transform_result": tr.get("objects"), "a_ws": py("r = node_state('|pair|a')['ws_t']", "r"), "b_ws": py("r = node_state('|pair|b')['ws_t']", "r")}
    show("G1_group_pivot_and_rotate", g1)

    ok("new_scene", {"confirm": True}); py(LIB + "\nr = 1")
    py('''
    p = cmds.group(empty=True, name="holder"); cmds.xform(p, ws=True, t=[5, 5, 0]); cmds.xform(p, ws=True, ro=[0, 45, 0])
    c = cmds.polyCube(name="child", ch=False)[0]; cmds.parent(c, p); cmds.xform(c, ws=True, t=[6, 5, 0])
    d = cmds.polyCube(name="spun", ch=False)[0]; cmds.xform(d, ws=True, t=[0, 2, 0], ro=[30, 60, 0], s=[2, 1, 1])
    r = 1''')
    before = {"child": py("r = node_state('|holder|child')", "r"), "spun": py("r = node_state('|spun')", "r")}
    res = result_or_error("group", {"names": ["|holder|child", "|spun"], "group_name": "mixed"})
    show("G2_G4_parented_and_transformed_members", {
        "before": before, "result": res, "group": py("r = node_state('|mixed')", "r"),
        "child_after": py("r = node_state('|mixed|child')", "r"), "spun_after": py("r = node_state('|mixed|spun')", "r"),
        "holder_after": py("r = node_state('|holder')", "r")})

    ok("new_scene", {"confirm": True}); py(LIB + "\nr = 1")
    ok("create_primitive", {"kind": "cube", "name": "a"})
    ok("create_primitive", {"kind": "cube", "name": "b"})
    ok("create_primitive", {"kind": "cube", "name": "taken"})
    res = result_or_error("group", {"names": ["|a", "|b"], "group_name": "taken"})
    show("G3_group_name_taken", {"result": res, "transforms": py("r = sorted(t for t in cmds.ls(type='transform', long=True) if not cmds.listRelatives(t, s=True, type='camera'))", "r")})

    ok("new_scene", {"confirm": True}); py(LIB + "\nr = 1")
    ok("create_primitive", {"kind": "cube", "name": "a"})
    ok("create_primitive", {"kind": "cube", "name": "b"})
    inner = result_or_error("group", {"names": ["|a"], "group_name": "inner"})
    outer = result_or_error("group", {"names": [inner.get("name", "|inner"), "|b"], "group_name": "outer"})
    show("G5_nested", {"inner": inner, "outer": outer, "tree": py("r = cmds.ls('|outer', dag=True, long=True)", "r")})

    ok("new_scene", {"confirm": True}); py(LIB + "\nr = 1")
    ok("create_primitive", {"kind": "cube", "name": "a"})
    dup = result_or_error("group", {"names": ["|a", "|a"], "group_name": "dup"})
    py('''
    p1 = cmds.group(empty=True, name="p1"); p2 = cmds.group(empty=True, name="p2")
    x = cmds.polyCube(name="part", ch=False)[0]; cmds.parent(x, p1)
    y = cmds.polyCube(name="part", ch=False)[0]; cmds.parent(y, p2)
    r = 1''')
    same = result_or_error("group", {"names": ["|p1|part", "|p2|part"], "group_name": "parts"})
    show("G6_duplicates_and_same_short_names", {"dup": dup, "dup_tree": py("r = cmds.ls('|dup', dag=True, long=True) if cmds.objExists('|dup') else None", "r"),
                                                 "same": same, "same_tree": py("r = cmds.ls('|parts', dag=True, long=True) if cmds.objExists('|parts') else None", "r")})

    print("\nfindings ->", os.path.join(OUT, "findings.json"))


if __name__ == "__main__":
    main()
