"""#822 PROBE B: the follow-ups round A raised.

  F1 empty results under the OTHER ops: difference with a inside b; union of
     disjoint cubes (two shells, should be fine)
  F2 shading-group membership after intersection vs difference on the same
     scene (round A saw ['initialShadingGroup', 'redSG', 'redSG'])
  F3 polyProjection planar md="z": object space or world space? A polyPlane
     rotated 90 about X by TRANSFORM (local +Y, world +-Z). Also md="x"/"y".
  F4 nonLinear handle sizing on a 4x1x1 box and on a mesh off the origin
  F5 wave deformer: h=2 vs h=10, amplitude 0.2 - same handle scaling as sine?

Run:  MAYA_MCP_PORT=9878 python evals/item4_probe_822b.py
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
from item4_probe_822 import LIB  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877:
    raise SystemExit("refusing the user's Maya")
OUT = os.path.join(_HERE, "item4_probe_822")
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
    with open(os.path.join(OUT, "findings_b.json"), "w", encoding="utf-8") as fh:
        json.dump(FINDINGS, fh, indent=1, default=str)
    print("\n--- %s ---" % label)
    print(json.dumps(value, indent=1, sort_keys=True, default=str))


def cubes(b_offset, b_scale=1.0):
    ok("new_scene", {"confirm": True})
    py(LIB + "\nr = 1")
    ok("create_primitive", {"kind": "cube", "name": "a"})
    ok("create_primitive", {"kind": "cube", "name": "b", "translate": b_offset, "scale": [b_scale] * 3})
    ok("assign_material", {"mesh": "|a", "shader": "lambert", "name": "red", "params": {"color": [1, 0, 0]}})


def main():
    # F1
    for label, off, scale, op in (("F1_difference_a_inside_b", [0, 0, 0], 3.0, "difference"),
                                  ("F1_union_disjoint", [3, 0, 0], 1.0, "union"),
                                  ("F1_difference_disjoint", [3, 0, 0], 1.0, "difference")):
        cubes(off, scale)
        res = result_or_error("boolean_op", {"a": "|a", "b": "|b", "op": op, "new_name": "cut"})
        after = py("r = {'cut': mesh_state('|cut'), 'a_exists': cmds.objExists('|a'), 'b_exists': cmds.objExists('|b')}", "r")
        show(label, {"result": {k: res.get(k) for k in ("name", "tris", "watertight", "warnings", "ERROR")}, "after": after})

    # F2
    for op in ("intersection", "difference"):
        cubes([0.5, 0.5, 0.5])
        result_or_error("boolean_op", {"a": "|a", "b": "|b", "op": op, "new_name": "cut"})
        show("F2_shading_" + op, py('''
            sh = cmds.listRelatives("|cut", s=True, f=True, ni=True)[0]
            r = {"listSets": cmds.listSets(object=sh, type=1),
                 "listSets_ec": cmds.listSets(object=sh, type=1, extendToShape=True),
                 "members_by_sg": {sg: [m for m in (cmds.sets(sg, q=True) or []) if "cut" in m] for sg in ("initialShadingGroup", "redSG")},
                 "shape_connections_to_sg": cmds.listConnections(sh + ".instObjGroups", type="shadingEngine", plugs=True)}
        ''', "r"))

    # F3
    ok("new_scene", {"confirm": True}); py(LIB + "\nr = 1")
    show("F3_projection_space", py('''
        out = {}
        p = cmds.polyPlane(name="tilt", w=2, h=2, sx=4, sy=4, ch=False)[0]
        cmds.xform(p, ro=[90, 0, 0])   # local +Y, world +-Z, NOT frozen
        sh = cmds.listRelatives(p, s=True, f=True)[0]
        cmds.polyProjection(sh + ".f[*]", type="Planar", ch=False, md="z")
        out["transform_rotated_local_Y_world_Z_md_z"] = uv_face_report(p)
        for md in ("x", "y", "z", "b", "p", "c"):
            q = cmds.polyPlane(name="flat_" + md, w=2, h=2, sx=4, sy=4, ch=False)[0]
            shq = cmds.listRelatives(q, s=True, f=True)[0]
            try:
                cmds.polyProjection(shq + ".f[*]", type="Planar", ch=False, md=md)
                out["unrotated_plane_md_" + md] = uv_face_report(q)["zero_area_faces"]
            except Exception as exc:
                out["unrotated_plane_md_" + md] = "ERR " + str(exc)[:120]
        h = cmds.help("polyProjection")
        out["help_md"] = [l.strip() for l in h.splitlines() if "-md" in l or "mapDirection" in l]
        r = out
    ''', "r"))

    # F4
    ok("new_scene", {"confirm": True}); py(LIB + "\nr = 1")
    show("F4_handle_sizing", py('''
        out = {}
        b = cmds.polyCube(name="slab", w=4, h=1, d=1, sx=8, sy=2, sz=2, ch=False)[0]
        cmds.xform(b, ws=True, t=[3, 0, 0]); cmds.makeIdentity(b, apply=True, t=1, r=1, s=1)
        nodes = cmds.nonLinear(b, type="sine")
        out["slab_4x1x1_at_x3"] = {"bbox": cmds.exactWorldBoundingBox(b), "handle_t": cmds.xform(nodes[1], q=True, ws=True, t=True), "handle_s": cmds.xform(nodes[1], q=True, r=True, s=True)}
        c = cmds.polyCube(name="tallbox", w=1, h=6, d=2, ch=False)[0]
        nodes = cmds.nonLinear(c, type="sine")
        out["box_1x6x2"] = {"handle_t": cmds.xform(nodes[1], q=True, ws=True, t=True), "handle_s": cmds.xform(nodes[1], q=True, r=True, s=True)}
        r = out
    ''', "r"))

    # F5
    for h in (2.0, 10.0):
        ok("new_scene", {"confirm": True}); py(LIB + "\nr = 1")
        mesh = py("r = cylinder('tube', %r)" % h, "r")
        py("BEFORE_PTS = points(%r); r = 1" % mesh)
        res = result_or_error("deform", {"mesh": mesh, "deformer": "wave", "params": {"amplitude": 0.2, "wavelength": 1.0}})
        show("F5_wave_h%g" % h, {"max_displacement": res.get("max_displacement"), "warnings": res.get("warnings"),
                                  "handle": py('''
            hh = [t for t in cmds.ls(type="transform") if "Handle" in t]
            r = {"scale": cmds.xform(hh[0], q=True, r=True, s=True), "translate": cmds.xform(hh[0], q=True, ws=True, t=True)} if hh else None
        ''', "r")})

    print("\nfindings ->", os.path.join(OUT, "findings_b.json"))


if __name__ == "__main__":
    main()
