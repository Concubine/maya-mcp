"""#822 PROBE: three value-selected routes no gate has ever sent to a Maya.
Records, does not assert.

boolean_op op=intersection (polyCBoolOp op=3)
  B1 two overlapping unit cubes (b at +0.5 on every axis), a carrying a red
     lambert: bbox / signed volume / tris / watertight / pivot / uv_bounds /
     shading of the result; what the operands and the node diff look like
  B2 two DISJOINT cubes: what an empty intersection produces - a result? an
     error? are the operands consumed either way?
  B3 a entirely inside b: result == a?
  B4 cubes sharing exactly one face: result?

uv_atlas project=planar (polyProjection type=Planar md="z", ch=False, then
polyNormalizeUV collective)
  U1 a cube: per-face UV area, how many faces collapse to zero area
  U2 a plane facing +Z (rotated & frozen) vs the same plane facing +X (rotated
     & frozen) vs a plane facing +X by TRANSFORM only (not frozen): is md="z"
     object space or world space, and which orientation collapses
  U3 a sphere: zero-area faces, and how many faces land mirrored (negative UV
     winding - the back half stacked on the front)
  U4 node diff / history after the call

deform deformer=sine (nonLinear type=sine)
  S1 cylinder h=2 (40 rings): amplitude 0.2 wavelength 1 - the handle's
     scale/bounds, attr types, returned max_displacement vs measured, wave
     periods along the height
  S2 cylinder h=10, same params: does displacement scale with the mesh (is
     "amplitude is in scene units" true?)
  S3 wavelength 2 vs 1 on h=2: period count
  S4 offset 0.5, S5 dropoff 1.0: recorded
  S6 rotate=[0,0,90] on the handle: does the wave direction change
  S7 delete_history_after=True: node diff, displacement persists
  S8 amplitude 0.001: the inert warning

Run:  MAYA_MCP_PORT=9878 python evals/item4_probe_822.py
"""
from __future__ import annotations

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
OUT = os.path.join(_HERE, "item4_probe_822")
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


LIB = r'''
import maya.cmds as cmds
import maya.api.OpenMaya as om

def snapshot():
    return set(cmds.ls())

def new_nodes(before):
    return sorted(n for n in set(cmds.ls()) - before)

def mesh_state(t):
    if not cmds.objExists(t):
        return {"exists": False}
    shapes = cmds.listRelatives(t, s=True, f=True, ni=True) or []
    if not shapes:
        return {"exists": True, "shapes": [], "children": cmds.listRelatives(t, c=True, f=True) or []}
    sh = shapes[0]
    sel = om.MSelectionList(); sel.add(sh)
    fn = om.MFnMesh(sel.getDagPath(0))
    pts = fn.getPoints(om.MSpace.kWorld)
    vol = 0.0
    tri_counts, tri_ids = fn.getTriangles()
    for i in range(0, len(tri_ids), 3):
        a, b, c = pts[tri_ids[i]], pts[tri_ids[i+1]], pts[tri_ids[i+2]]
        vol += (a.x*(b.y*c.z - b.z*c.y) - a.y*(b.x*c.z - b.z*c.x) + a.z*(b.x*c.y - b.y*c.x)) / 6.0
    return {"exists": True, "faces": fn.numPolygons, "verts": fn.numVertices,
            "bbox": [round(v, 4) for v in cmds.exactWorldBoundingBox(t)],
            "signed_volume": round(vol, 5),
            "sg": sorted(cmds.listSets(object=sh, type=1) or []),
            "history": [n for n in (cmds.listHistory(t, pdo=True) or []) if cmds.nodeType(n) != "mesh"],
            "parent": (cmds.listRelatives(t, p=True, f=True) or [None])[0]}

def uv_face_report(t):
    sh = cmds.listRelatives(t, s=True, f=True, ni=True)[0]
    sel = om.MSelectionList(); sel.add(sh)
    fn = om.MFnMesh(sel.getDagPath(0))
    zero = 0; flipped = 0; missing = 0; areas = []
    for f in range(fn.numPolygons):
        try:
            uvs = [fn.getPolygonUV(f, i) for i in range(fn.polygonVertexCount(f))]
        except Exception:
            missing += 1; continue
        a = 0.0
        for i in range(len(uvs)):
            u1, v1 = uvs[i]; u2, v2 = uvs[(i + 1) % len(uvs)]
            a += u1 * v2 - u2 * v1
        a *= 0.5
        areas.append(a)
        if abs(a) < 1e-9: zero += 1
        elif a < 0: flipped += 1
    us = cmds.polyEditUV(sh + ".map[*]", q=True) or []
    return {"faces": fn.numPolygons, "zero_area_faces": zero, "flipped_faces": flipped, "faces_without_uvs": missing,
            "uv_count": len(us) // 2, "uv_bounds": [round(min(us[0::2]), 4), round(min(us[1::2]), 4), round(max(us[0::2]), 4), round(max(us[1::2]), 4)] if us else None,
            "total_abs_area": round(sum(abs(a) for a in areas), 5)}

def points(t):
    sh = cmds.listRelatives(t, s=True, f=True, ni=True)[0]
    sel = om.MSelectionList(); sel.add(sh)
    return [(p.x, p.y, p.z) for p in om.MFnMesh(sel.getDagPath(0)).getPoints(om.MSpace.kWorld)]

def cylinder(name, h, rings=40):
    m = cmds.polyCylinder(name=name, radius=0.2, height=h, subdivisionsY=rings, subdivisionsX=12, ch=False)[0]
    cmds.xform(m, ws=True, t=[0, h / 2.0, 0]); cmds.makeIdentity(m, apply=True, t=1, r=1, s=1)
    return cmds.ls(m, long=True)[0]

def wave_report(t, before):
    """Displacement of the +X column of vertices along the height: periods, max, direction."""
    after = points(t)
    col = [(b[1], a[0] - b[0], a[1] - b[1], a[2] - b[2]) for a, b in zip(after, before) if abs(b[2]) < 1e-6 and b[0] > 0.1]
    col.sort()
    dx = [c[1] for c in col]
    signs = [1 if d > 1e-6 else (-1 if d < -1e-6 else 0) for d in dx]
    nz = [s for s in signs if s]
    crossings = sum(1 for i in range(1, len(nz)) if nz[i] != nz[i-1])
    mx = max(((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2) ** 0.5 for a, b in zip(after, before))
    return {"column_verts": len(col), "sign_crossings_along_height": crossings, "max_dx": round(max(dx), 4), "min_dx": round(min(dx), 4),
            "max_dy": round(max(abs(c[2]) for c in col), 5), "max_dz": round(max(abs(c[3]) for c in col), 5), "max_move": round(mx, 5),
            "dx_bottom": round(dx[0], 4), "dx_top": round(dx[-1], 4)}
'''


def main():
    py(LIB + "\nr = 1")

    # ---------------------------------------------------------------- boolean
    def cubes(b_offset, b_scale=1.0):
        ok("new_scene", {"confirm": True})
        py(LIB + "\nr = 1")
        ok("create_primitive", {"kind": "cube", "name": "a"})
        ok("create_primitive", {"kind": "cube", "name": "b", "translate": b_offset, "scale": [b_scale] * 3})
        ok("assign_material", {"mesh": "|a", "shader": "lambert", "name": "red", "params": {"color": [1, 0, 0]}})
        return py("BEFORE = snapshot(); r = {'a': mesh_state('|a'), 'b': mesh_state('|b')}", "r")

    for label, off, scale in (("B1_overlap", [0.5, 0.5, 0.5], 1.0), ("B2_disjoint", [3, 0, 0], 1.0),
                              ("B3_a_inside_b", [0, 0, 0], 3.0), ("B4_share_a_face", [1, 0, 0], 1.0)):
        ops = cubes(off, scale)
        res = result_or_error("boolean_op", {"a": "|a", "b": "|b", "op": "intersection", "new_name": "cut"})
        after = py('''
            r = {"new_nodes": new_nodes(BEFORE), "a": mesh_state("|a"), "b": mesh_state("|b"), "cut": mesh_state("|cut"),
                 "transforms": sorted(t for t in cmds.ls(type="transform", long=True) if not cmds.listRelatives(t, s=True, type="camera")),
                 "empty_meshes": [s for s in cmds.ls(type="mesh", long=True) if cmds.polyEvaluate(s, v=True) == 0]}
        ''', "r")
        show(label, {"operands_before": ops, "result": res, "scene_after": after})

    # ---------------------------------------------------------------- uv planar
    ok("new_scene", {"confirm": True})
    py(LIB + "\nr = 1")
    ok("create_primitive", {"kind": "cube", "name": "box"})
    py("BEFORE = snapshot(); r = 1")
    res = result_or_error("uv_atlas", {"names": ["|box"], "project": "planar"})
    show("U1_cube_planar", {"result": res, "faces": py("r = uv_face_report('|box')", "r"),
                            "new_nodes": py("r = new_nodes(BEFORE)", "r"), "history": py("r = mesh_state('|box')['history']", "r")})
    box_default = None
    ok("new_scene", {"confirm": True}); py(LIB + "\nr = 1")
    ok("create_primitive", {"kind": "cube", "name": "box"})
    res = result_or_error("uv_atlas", {"names": ["|box"]})
    box_default = {"result_projection": res.get("projection"), "faces": py("r = uv_face_report('|box')", "r")}
    show("U1b_cube_box_for_contrast", box_default)

    ok("new_scene", {"confirm": True}); py(LIB + "\nr = 1")
    planes = py('''
        out = {}
        z = cmds.polyPlane(name="faceZ", w=2, h=2, sx=4, sy=4, ch=False)[0]; cmds.xform(z, ro=[90, 0, 0]); cmds.makeIdentity(z, apply=True, t=1, r=1, s=1)
        x = cmds.polyPlane(name="faceX", w=2, h=2, sx=4, sy=4, ch=False)[0]; cmds.xform(x, ro=[0, 0, 90]); cmds.makeIdentity(x, apply=True, t=1, r=1, s=1)
        xt = cmds.polyPlane(name="faceX_xform", w=2, h=2, sx=4, sy=4, ch=False)[0]; cmds.xform(xt, ro=[0, 0, 90])
        y = cmds.polyPlane(name="faceY", w=2, h=2, sx=4, sy=4, ch=False)[0]
        r = {"faceZ_normal": list(cmds.polyInfo(z + ".f[0]", fn=True)[0].split()[-3:]), "faceX_normal": list(cmds.polyInfo(x + ".f[0]", fn=True)[0].split()[-3:])}
    ''', "r")
    u2 = {"normals": planes}
    for name in ("faceZ", "faceX", "faceX_xform", "faceY"):
        res = result_or_error("uv_atlas", {"names": ["|" + name], "project": "planar"})
        u2[name] = {"inside_patch": (res.get("meshes") or [{}])[0].get("inside_patch"), "uv_bounds": (res.get("meshes") or [{}])[0].get("uv_bounds"),
                    "ERROR": res.get("ERROR"), "faces": py("r = uv_face_report('|%s')" % name, "r")}
    show("U2_planes_by_facing", u2)

    ok("new_scene", {"confirm": True}); py(LIB + "\nr = 1")
    ok("create_primitive", {"kind": "sphere", "name": "ball"})
    res = result_or_error("uv_atlas", {"names": ["|ball"], "project": "planar"})
    show("U3_sphere_planar", {"result_meshes": res.get("meshes"), "warnings": res.get("warnings"), "faces": py("r = uv_face_report('|ball')", "r")})

    # ---------------------------------------------------------------- deform sine
    def sine_case(label, h, params, bake=False, extra=None):
        ok("new_scene", {"confirm": True}); py(LIB + "\nr = 1")
        mesh = py("r = cylinder('tube', %r)" % h, "r")
        py("BEFORE_PTS = points(%r); BEFORE = snapshot(); r = 1" % mesh)
        p = {"mesh": mesh, "deformer": "sine", "params": params}
        if bake:
            p["delete_history_after"] = True
        res = result_or_error("deform", p)
        info = py('''
            nodes = %r
            r = {"wave": wave_report(%r, BEFORE_PTS), "new_nodes": new_nodes(BEFORE)}
            d = [n for n in cmds.ls(type="nonLinear") ]
            if d:
                n = d[0]
                r["deformer_attrs"] = {a: cmds.getAttr(n + "." + a) for a in ("amplitude", "wavelength", "offset", "dropoff", "lowBound", "highBound")}
                r["attr_types"] = {a: cmds.getAttr(n + "." + a, type=True) for a in ("amplitude", "wavelength", "offset", "dropoff", "lowBound", "highBound")}
                h = [t for t in cmds.ls(type="transform") if "Handle" in t]
                if h:
                    r["handle"] = {"name": h[0], "translate": cmds.xform(h[0], q=True, ws=True, t=True), "scale": cmds.xform(h[0], q=True, r=True, s=True), "rotate": cmds.xform(h[0], q=True, ws=True, ro=True)}
        ''' % (res.get("deformer_nodes"), mesh), "r")
        show(label, {"params": params, "bake": bake, "result": res, "measured": info})
        return res, info

    sine_case("S1_h2_amp0.2_wl1", 2.0, {"amplitude": 0.2, "wavelength": 1.0})
    sine_case("S2_h10_amp0.2_wl1", 10.0, {"amplitude": 0.2, "wavelength": 1.0})
    sine_case("S3_h2_amp0.2_wl2", 2.0, {"amplitude": 0.2, "wavelength": 2.0})
    sine_case("S3b_h2_amp0.2_wl0.5", 2.0, {"amplitude": 0.2, "wavelength": 0.5})
    sine_case("S4_offset0.5", 2.0, {"amplitude": 0.2, "wavelength": 1.0, "offset": 0.5})
    sine_case("S5_dropoff1", 2.0, {"amplitude": 0.2, "wavelength": 1.0, "dropoff": 1.0})
    sine_case("S6_rotate_z90", 2.0, {"amplitude": 0.2, "wavelength": 1.0, "rotate": [0, 0, 90]})
    sine_case("S6b_translate_y1", 2.0, {"amplitude": 0.2, "wavelength": 1.0, "translate": [0, 1.5, 0]})
    sine_case("S7_baked", 2.0, {"amplitude": 0.2, "wavelength": 1.0}, bake=True)
    sine_case("S8_inert", 2.0, {"amplitude": 0.001, "wavelength": 1.0})
    sine_case("S9_bounds_half", 2.0, {"amplitude": 0.2, "wavelength": 1.0, "lowBound": 0.0, "highBound": 1.0})

    print("\nfindings ->", os.path.join(OUT, "findings.json"))


if __name__ == "__main__":
    main()
