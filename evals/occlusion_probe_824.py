"""Throwaway probe for #824: can a ray test tell that capture_viewport's
`target` is hidden behind another mesh from the placed camera?

Measures, on the agent Maya (never 9877):

  A  the #823 K2 scene: back + target=|red, blue cube in the way
  B  front + target=|red (nothing in the way)
  C  side + target=|red
  D  blue shifted half a cube sideways: partial cover, rays vs red pixels
  E  a cube standing on a floor plane, three_quarter: do corner rays graze
     the floor (tolerance question)
  F  target = a group of two cubes with a third in front: occluders must
     exclude the target's own shapes
  G  a skinned cube: does ls(geometry, visible) list the intermediate
     ShapeOrig, and does it answer rays
  H  timing: 9 rays against a 250k-face sphere
  I  isolate=[red] + target red from the back: the isolated-away blue must
     not count as an occluder (pixels say red)
  J  what closestIntersection returns on a miss (API 2.0 shape)

Run:  MAYA_MCP_PORT=9878 python evals/occlusion_probe_824.py
"""

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
OUT = os.path.join(_HERE, "occlusion_probe_824")
os.makedirs(OUT, exist_ok=True)
FINDINGS = {}


def ok(command, params, timeout_s=300.0):
    r = call(command, params, timeout_s=timeout_s, port=PORT)
    if r.get("status") != "ok":
        raise SystemExit("%s failed: %s" % (command, json.dumps(r.get("error"), indent=1)))
    return r.get("result") or {}


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
    import numpy as np
    from PIL import Image
    img = Image.open(io.BytesIO(base64.b64decode(png_b64))).convert("RGB")
    img.save(os.path.join(OUT, name + ".png"))
    a = np.asarray(img).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    red = int(((r > 120) & (g < 90) & (b < 90)).sum())
    blue = int(((b > 120) & (r < 90) & (g < 90)).sum())
    return {"red_px": red, "blue_px": blue}


LIB = r'''
import time
import maya.cmds as cmds
import maya.api.OpenMaya as om

def colour(t, col, name):
    sh = cmds.shadingNode("lambert", asShader=True, name=name + "_mat")
    cmds.setAttr(sh + ".color", *col, type="double3")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=sh + "SG")
    cmds.connectAttr(sh + ".outColor", sg + ".surfaceShader")
    cmds.sets(t, e=True, forceElement=sg)

def red_blue_scene(blue_x=0.0):
    cmds.file(new=True, force=True)
    r = cmds.polyCube(name="red", w=1, h=1, d=1, ch=False)[0]; cmds.xform(r, ws=True, t=[0, 0, 1.2])
    b = cmds.polyCube(name="blue", w=1, h=1, d=1, ch=False)[0]; cmds.xform(b, ws=True, t=[blue_x, 0, -1.2])
    colour(r, (1, 0, 0), "red"); colour(b, (0, 0, 1), "blue")
    return [cmds.ls(r, long=True)[0], cmds.ls(b, long=True)[0]]

def visible_meshes():
    out = []
    for s in cmds.ls(geometry=True, visible=True, long=True) or []:
        out.append({"shape": s, "type": cmds.nodeType(s),
                    "intermediate": bool(cmds.getAttr(s + ".intermediateObject")) if cmds.attributeQuery("intermediateObject", node=s, exists=True) else None})
    return out

def shapes_under(transforms):
    out = set()
    for t in transforms:
        for s in cmds.listRelatives(t, allDescendents=True, shapes=True, fullPath=True, noIntermediate=True) or []:
            out.add(s)
        if cmds.nodeType(t) == "mesh":
            out.add(cmds.ls(t, long=True)[0])
    return out

def samples_of(transforms):
    bb = cmds.exactWorldBoundingBox(*transforms)
    pts = [((bb[0] + bb[3]) / 2.0, (bb[1] + bb[4]) / 2.0, (bb[2] + bb[5]) / 2.0)]
    pts += [(x, y, z) for x in (bb[0], bb[3]) for y in (bb[1], bb[4]) for z in (bb[2], bb[5])]
    return pts

def ray_report(cam_pos, transforms, occluders, tol=1e-4):
    src = om.MPoint(*cam_pos)
    fns = []
    for shp in occluders:
        sel = om.MSelectionList(); sel.add(shp)
        fns.append((shp, om.MFnMesh(sel.getDagPath(0))))
    rows = []
    t0 = time.perf_counter()
    for p in samples_of(transforms):
        dst = om.MPoint(*p); d = dst - src; dist = d.length()
        dirv = om.MFloatVector(d.normal())
        blockers = []
        for shp, fn in fns:
            hit = fn.closestIntersection(om.MFloatPoint(src), dirv, om.MSpace.kWorld, dist, False)
            if hit is not None and hit[2] != -1 and hit[1] < dist * (1.0 - tol):
                blockers.append([shp.split("|")[-1], round(hit[1], 4), round(dist, 4)])
        rows.append({"sample": [round(v, 3) for v in p], "blockers": blockers})
    return {"rays": rows, "blocked": sum(1 for r in rows if r["blockers"]),
            "ms": round((time.perf_counter() - t0) * 1000.0, 2)}

def occluders_for(transforms, isolate=None):
    own = shapes_under(transforms)
    out = []
    for m in visible_meshes():
        if m["type"] != "mesh" or m["intermediate"] or m["shape"] in own:
            continue
        if isolate is not None:
            keep = shapes_under(isolate)
            if m["shape"] not in keep:
                continue
        out.append(m["shape"])
    return out
'''


def capture(params, name):
    shot = ok("capture_viewport", dict(params, resolution=256, shading="flatShaded"))
    img = shot["images"][0]
    return {"colours": colours(img["png_b64"], name), "camera": shot["camera_positions"][0],
            "warnings": shot["warnings"], "blank": img.get("blank")}


def rays(cam, targets, isolate=None):
    return py('''
        r = ray_report(%r, %r, occluders_for(%r, %r))
    ''' % (list(cam["position"]), targets, targets, isolate))


def main():
    py(LIB + "\nr = 1")

    # A/B/C: the K2 scene from three angles
    ok("new_scene", {"confirm": True}); py(LIB + "\nr = 1")
    py("r = red_blue_scene()")
    for angle in ("back", "front", "side"):
        shot = capture({"angles": [angle], "target": "|red"}, "ABC_%s" % angle)
        show("ABC_%s" % angle, {"capture": shot, "rays": rays(shot["camera"], ["|red"])})

    # D: half cover
    ok("new_scene", {"confirm": True}); py(LIB + "\nr = 1")
    py("r = red_blue_scene(blue_x=0.5)")
    shot = capture({"angles": ["back"], "target": "|red"}, "D_half")
    show("D_half_cover", {"capture": shot, "rays": rays(shot["camera"], ["|red"])})
    py("r = red_blue_scene(blue_x=0.9)")
    shot = capture({"angles": ["back"], "target": "|red"}, "D_tenth")
    show("D_tenth_cover", {"capture": shot, "rays": rays(shot["camera"], ["|red"])})

    # E: cube on a floor, three_quarter and front
    ok("new_scene", {"confirm": True}); py(LIB + "\nr = 1")
    py('''
        cmds.file(new=True, force=True)
        c = cmds.polyCube(name="red", ch=False)[0]; colour(c, (1, 0, 0), "red")
        f = cmds.polyPlane(name="floor", w=10, h=10, sx=1, sy=1, ch=False)[0]
        cmds.xform(f, ws=True, t=[0, -0.5, 0]); colour(f, (0, 0, 1), "floor")
        r = 1
    ''')
    for angle in ("three_quarter", "front", "top"):
        shot = capture({"angles": [angle], "target": "|red"}, "E_%s" % angle)
        raw = py('''
            r = ray_report(%r, ["|red"], occluders_for(["|red"]), tol=0.0)
        ''' % list(shot["camera"]["position"]))
        show("E_floor_%s" % angle, {"capture": shot, "rays_tol": rays(shot["camera"], ["|red"]),
                                    "rays_raw_blocked": raw["blocked"], "raw": raw["rays"]})

    # F: target is a group; a third cube in front
    ok("new_scene", {"confirm": True}); py(LIB + "\nr = 1")
    py('''
        cmds.file(new=True, force=True)
        a = cmds.polyCube(name="a", ch=False)[0]; cmds.xform(a, ws=True, t=[-1, 0, 0]); colour(a, (1, 0, 0), "ra")
        b = cmds.polyCube(name="b", ch=False)[0]; cmds.xform(b, ws=True, t=[1, 0, 0]); colour(b, (1, 0, 0), "rb")
        g = cmds.group(a, b, name="pair")
        w = cmds.polyCube(name="wall", w=4, h=2, d=0.2, ch=False)[0]; cmds.xform(w, ws=True, t=[0, 0, 2]); colour(w, (0, 0, 1), "wall")
        r = {"occ": occluders_for(["|pair"]), "own": sorted(shapes_under(["|pair"]))}
    ''')
    shot = capture({"angles": ["front"], "target": "|pair"}, "F_front")
    show("F_group_target", {"setup": py("r = {'occ': occluders_for(['|pair'])}"), "capture": shot,
                            "rays": rays(shot["camera"], ["|pair"])})
    shot = capture({"angles": ["back"], "target": "|pair"}, "F_back")
    show("F_group_target_back", {"capture": shot, "rays": rays(shot["camera"], ["|pair"])})

    # G: skinned cube - intermediate shapes
    ok("new_scene", {"confirm": True}); py(LIB + "\nr = 1")
    show("G_skinned", py('''
        cmds.file(new=True, force=True)
        c = cmds.polyCube(name="skinned", ch=False)[0]
        j = cmds.joint(p=(0, 0, 0))
        cmds.skinCluster(j, c)
        r = {"visible": visible_meshes(), "occluders_for_other": occluders_for(["|red"]) if cmds.objExists("|red") else occluders_for([])}
    '''))

    # H: timing on a 250k-face sphere
    ok("new_scene", {"confirm": True}); py(LIB + "\nr = 1")
    show("H_timing", py('''
        cmds.file(new=True, force=True)
        s = cmds.polySphere(name="big", sa=500, sh=500, r=3, ch=False)[0]
        c = cmds.polyCube(name="red", ch=False)[0]; cmds.xform(c, ws=True, t=[0, 0, 5])
        faces = cmds.polyEvaluate(s, face=True)
        first = ray_report([0, 0, -8], ["|red"], occluders_for(["|red"]))
        second = ray_report([0, 0, -8], ["|red"], occluders_for(["|red"]))
        r = {"faces": faces, "first_ms": first["ms"], "second_ms": second["ms"], "blocked": first["blocked"]}
    '''))

    # I: isolate hides the occluder
    ok("new_scene", {"confirm": True}); py(LIB + "\nr = 1")
    py("r = red_blue_scene()")
    shot = capture({"angles": ["back"], "target": "|red", "isolate": ["|red"]}, "I_isolate")
    show("I_isolate", {"capture": shot,
                       "rays_all": rays(shot["camera"], ["|red"]),
                       "rays_isolate": rays(shot["camera"], ["|red"], ["|red"])})
    # hidden occluder
    py("cmds.setAttr('|blue.visibility', False); r = 1")
    shot = capture({"angles": ["back"], "target": "|red"}, "I_hidden")
    show("I_hidden_occluder", {"capture": shot, "rays": rays(shot["camera"], ["|red"])})

    # J: the miss shape
    show("J_miss_shape", py('''
        sel = om.MSelectionList(); sel.add("|red"); dag = sel.getDagPath(0); dag.extendToShape()
        fn = om.MFnMesh(dag)
        miss = fn.closestIntersection(om.MFloatPoint(0, 50, 0), om.MFloatVector(0, 1, 0), om.MSpace.kWorld, 10.0, False)
        hit = fn.closestIntersection(om.MFloatPoint(0, 0, 10), om.MFloatVector(0, 0, -1), om.MSpace.kWorld, 100.0, False)
        r = {"miss": repr(miss), "hit": repr(hit)}
    '''))
    print("\nfindings ->", os.path.join(OUT, "findings.json"))


if __name__ == "__main__":
    main()
