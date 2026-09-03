"""#814: the four probes #797 listed and never ran. MEASURE, do not assert -
each answer decides a row (refuse / document / keep the warning).

  A. pose_ik on a STRAIGHT chain: where does the knee go with no pole, with a
     pole on +Z, -Z, +X? Does the pole choose the fold side?
  B. deform sculpt: is params.rotate inert on the sculptor sphere? Vertex A/B.
  C. retarget_clip's .fbx route (never run live): bake a BVH walk, export it
     with animation, retarget the FBX onto a clean rig, compare; then measure
     what Maya itself does to the FBX's keys under a different time unit.
  D. capture_viewport under VP2: shadows under smoothShaded / flatShaded /
     wireframe, ssao under smoothShaded / wireframe, lighting=scene with no
     lights - pixel diffs between the flag on and off.

DESTRUCTIVE: calls new_scene. Agent Maya on 9878 only, launched with the repo
as cwd.  Run:  MAYA_MCP_PORT=9878 python evals/p797_probes.py
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

from PIL import Image  # noqa: E402

from live_call import call, structured_result  # noqa: E402
import humanoid_live  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877:
    raise SystemExit("refusing the user's Maya")
OUT = os.path.join(_HERE, "p797_probes_814")
os.makedirs(OUT, exist_ok=True)
WALK_BVH = os.path.join(_HERE, "mocap_fixtures", "cmu_walk.bvh").replace("\\", "/")
FINDINGS = {}
PARTS = os.environ.get("PARTS", "ABCD").upper()


def save():
    with open(os.path.join(OUT, "findings.json"), "w", encoding="utf-8") as fh:
        json.dump(FINDINGS, fh, indent=1, default=str)


def ok(command, params, timeout_s=600.0):
    r = call(command, params, timeout_s=timeout_s, port=PORT)
    if r.get("status") != "ok":
        raise SystemExit("%s failed: %s" % (command, json.dumps(r.get("error"), indent=1)))
    return r.get("result") or {}


def err(command, params, timeout_s=600.0):
    r = call(command, params, timeout_s=timeout_s, port=PORT)
    return None if r.get("status") == "ok" else r.get("error")


def py(code, what="r", timeout_s=600.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s), what)


def show(label, value):
    FINDINGS[label] = value
    save()
    print("\n--- %s ---" % label)
    print(json.dumps(value, indent=1, sort_keys=True, default=str))


def fresh():
    ok("new_scene", {"confirm": True})


def summary(m):
    """The parts of a measure_clip result that decide whether two takes are
    the same motion: sampling, height, per-joint path/peak, contact slide."""
    return {
        "fps": m.get("fps"), "frames_sampled": m.get("frames_sampled"),
        "rig_height": m.get("rig_height"), "warnings": m.get("warnings"),
        "path_length": {j: round(v["path_length"], 3) for j, v in (m.get("joints") or {}).items()},
        "peak_speed": {j: round(v["peak_speed"], 3) for j, v in (m.get("joints") or {}).items()},
        "max_slide": {j: round(v["max_slide"], 4) for j, v in (m.get("contacts") or {}).items()},
    }


ident = py("import os, maya_plugin\n{'file': maya_plugin.__file__, 'cwd': os.getcwd()}", "identity")
print("live plugin:", ident)
assert os.path.normcase(ident["file"]).startswith(os.path.normcase(REPO)), "wrong code"

# =========================================================================== A


def part_a():
    print("\n=== A. pose_ik fold sign on a straight chain ===")


    def solve(pole):
        fresh()
        sk = ok("create_skeleton", {"chain": [[0, 1, 0], [0, 0.5, 0], [0, 0, 0]],
                                    "chain_prefix": "leg"})
        root, joints = sk["root"], [j["name"] for j in sk["joints"]]
        params = {"root": root, "joint": joints[-1], "target": [0, 0.3, 0]}
        if pole is not None:
            params["pole"] = pole
        r = call("pose_ik", params, timeout_s=120, port=PORT)
        if r.get("status") != "ok":
            return {"refused": r.get("error")}
        res = r["result"]
        pos = py("import maya.cmds as cmds\n{j: [round(v, 4) for v in cmds.xform(j, q=True, ws=True, t=True)] for j in %r}"
                 % (joints,), "pos")
        return {"positions": pos, "residual": res.get("residual"),
                "warnings": res.get("warnings"), "pole_used": res.get("pole_used")}


    for label, pole in (("A1 no pole", None), ("A2 pole +Z", [0, 0.5, 1.0]),
                        ("A3 pole -Z", [0, 0.5, -1.0]), ("A4 pole +X", [1.0, 0.5, 0]),
                        ("A5 pole -X", [-1.0, 0.5, 0])):
        show(label, solve(pole))

    # a chain that is already bent slightly toward -Z: does the pole on +Z flip it?
    fresh()
    sk = ok("create_skeleton", {"chain": [[0, 1, 0], [0, 0.5, -0.05], [0, 0, 0]],
                                "chain_prefix": "bent"})
    root, joints = sk["root"], [j["name"] for j in sk["joints"]]
    r = ok("pose_ik", {"root": root, "joint": joints[-1], "target": [0, 0.3, 0], "pole": [0, 0.5, 1.0]})
    pos = py("import maya.cmds as cmds\n{j: [round(v, 4) for v in cmds.xform(j, q=True, ws=True, t=True)] for j in %r}"
             % (joints,), "pos")
    show("A6 pre-bent toward -Z, pole +Z", {"positions": pos, "warnings": r.get("warnings"),
                                           "residual": r.get("residual")})



if 'A' in PARTS:
    part_a()


# =========================================================================== B


def part_b():
    print("\n=== B. deform sculpt: is params.rotate inert? ===")


    def sculpt_verts(params):
        fresh()
        py("import maya.cmds as cmds\ncmds.polyPlane(name='slab', w=4, h=4, sx=20, sy=20)\nTrue", "slab")
        res = ok("deform", {"mesh": "|slab", "deformer": "sculpt", "params": params})
        verts = py("import maya.cmds as cmds\n"
                   "[tuple(round(v, 5) for v in cmds.xform('|slab.vtx[%d]' % i, q=True, ws=True, t=True)) "
                   "for i in range(cmds.polyEvaluate('|slab', v=True))]", "verts")
        handle = py("import maya.cmds as cmds\n"
                    "h = %r\n{'t': cmds.xform(h, q=True, ws=True, t=True), 'r': cmds.xform(h, q=True, ws=True, ro=True), "
                    "'type': cmds.nodeType(h), 'shape': cmds.listRelatives(h, s=True)}" % res["deformer_nodes"][1]
                    if len(res.get("deformer_nodes") or []) > 1 else "None", "handle")
        return verts, res, handle


    vA, rA, hA = sculpt_verts({"translate": [0, 0.3, 0]})
    vB, rB, hB = sculpt_verts({"translate": [0, 0.3, 0], "rotate": [45, 30, 0]})
    vC, rC, hC = sculpt_verts({"translate": [0, 0.3, 0], "rotate": [0, 0, 90]})
    vD, rD, hD = sculpt_verts({"translate": [0.5, 0.3, 0]})   # control: translate DOES matter


    def maxdiff(a, b):
        return max(max(abs(x - y) for x, y in zip(p, q)) for p, q in zip(a, b))


    show("B. sculpt rotate A/B", {
        "A translate only": {"max_displacement": rA.get("max_displacement"), "handle": hA, "warnings": rA.get("warnings")},
        "B rotate 45,30,0": {"max_displacement": rB.get("max_displacement"), "handle": hB, "warnings": rB.get("warnings")},
        "C rotate 0,0,90": {"max_displacement": rC.get("max_displacement"), "handle": hC},
        "maxdiff A vs B": maxdiff(vA, vB), "maxdiff A vs C": maxdiff(vA, vC),
        "CONTROL maxdiff A vs D (translate moved)": maxdiff(vA, vD),
        "A moved vertices": sum(1 for p in vA if abs(p[1]) > 1e-6),
    })



if 'B' in PARTS:
    part_b()


# =========================================================================== C


def part_c():
    print("\n=== C. retarget_clip .fbx route ===")
    fresh()
    units = py("from maya_plugin.handlers import clipmath, mocapmath\n"
               "{'FPS_UNITS': clipmath.FPS_UNITS, 'nearest_120': mocapmath.nearest_bake_fps(120.0, set(clipmath.FPS_UNITS))}", "units")
    show("C0 fps units", units)
    rig_a = ok("create_skeleton", {"joints": humanoid_live.JOINTS})["root"]
    walk = ok("retarget_clip", {"file": WALK_BVH, "root": rig_a, "clip": "walk", "start": 1}, 900)
    show("C1 BVH retarget", {k: walk.get(k) for k in ("clip", "fps", "start_frame", "end_frame", "frames", "duration_s", "warnings")})
    m_bvh = ok("measure_clip", {"root": rig_a, "name": "walk"}, 600)
    show("C1 measure (bvh)", summary(m_bvh))
    fbx_path = os.path.join(OUT, "walk_take.fbx").replace("\\", "/")
    exp = ok("export_fbx", {"path": fbx_path, "include_animation": True, "include_skins": False,
                            "metres_per_unit": 1.0, "nodes": [rig_a]}, 600)
    anim = exp.get("animation") or {}
    by_take = {}
    for t in anim.get("targets") or []:
        key = "%s / %s" % (t.get("take"), t.get("property"))
        by_take.setdefault(key, {"targets": 0, "with_keys": 0})
        by_take[key]["targets"] += 1
        by_take[key]["with_keys"] += 1 if t.get("key_count") else 0
    show("C2 export", {"path": exp.get("path"), "takes": anim.get("takes"), "clips": anim.get("clips"),
                       "targets by take/property": by_take, "warnings": exp.get("warnings")})

    # what Maya does with the file, before any tool: import it, read unit + range
    raw = py(textwrap.dedent(r'''
    import maya.cmds as cmds
    before_unit = cmds.currentUnit(q=True, time=True)
    cmds.file(new=True, force=True)
    cmds.file(%r, i=True, namespace="probe", type="FBX", ignoreVersion=True, preserveReferences=False)
    js = cmds.ls(type="joint")   # MEASURED: fbxmaya ignores the file command's namespace flag
    t = cmds.keyframe(js, q=True) or []
    after_unit = cmds.currentUnit(q=True, time=True)
    r1 = {"unit_before": before_unit, "unit_after_import": after_unit, "keys": len(t), "range": [min(t), max(t)]}
    cmds.currentUnit(time="film")   # 24 fps, updateAnimation default
    t2 = cmds.keyframe(js, q=True) or []
    r1["after_unit_film_range"] = [min(t2), max(t2)]
    r1["after_unit_film_unit"] = cmds.currentUnit(q=True, time=True)
    cmds.file(new=True, force=True)
    cmds.currentUnit(time="film")
    cmds.file(%r, i=True, namespace="probe2", type="FBX", ignoreVersion=True, preserveReferences=False)
    js = cmds.ls(type="joint"); t3 = cmds.keyframe(js, q=True) or []
    r1["import_into_film_scene"] = {"unit_after": cmds.currentUnit(q=True, time=True), "range": [min(t3), max(t3)], "keys": len(t3)}
    cmds.file(new=True, force=True)
    r1
    ''').strip() % (fbx_path, fbx_path), "raw", 600)
    show("C3 raw FBX import behaviour", raw)

    fresh()
    rig_b = ok("create_skeleton", {"joints": humanoid_live.JOINTS})["root"]
    fbx_take = call("retarget_clip", {"file": fbx_path, "root": rig_b, "clip": "walk"}, timeout_s=900, port=PORT)
    if fbx_take.get("status") == "ok":
        res = fbx_take["result"]
        show("C4 FBX retarget (fps omitted)", {k: res.get(k) for k in ("clip", "fps", "start_frame", "end_frame", "frames", "duration_s", "warnings")})
        m_fbx = ok("measure_clip", {"root": rig_b, "name": "walk"}, 600)
        show("C4 measure (fbx)", summary(m_fbx))
    else:
        show("C4 FBX retarget REFUSED/FAILED", fbx_take.get("error"))
    fresh()
    rig_c = ok("create_skeleton", {"joints": humanoid_live.JOINTS})["root"]
    show("C5 FBX retarget with fps=24 (row 25)", err("retarget_clip", {"file": fbx_path, "root": rig_c, "clip": "walk", "fps": 24}, 900))



if 'C' in PARTS:
    part_c()


# =========================================================================== D


def part_d():
    print("\n=== D. VP2 shadows / ssao / no-light ===")


    def png_of(res):
        return base64.b64decode(res["images"][0]["png_b64"])


    def stats(png):
        img = Image.open(io.BytesIO(png)).convert("RGB")
        px = list(img.getdata())
        lum = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in px]
        mean = sum(lum) / len(lum)
        var = sum((v - mean) ** 2 for v in lum) / len(lum)
        return {"mean": round(mean, 2), "std": round(var ** 0.5, 2), "size": img.size}


    def diff(p1, p2):
        a = Image.open(io.BytesIO(p1)).convert("RGB")
        b = Image.open(io.BytesIO(p2)).convert("RGB")
        da, db = list(a.getdata()), list(b.getdata())
        n = sum(1 for x, y in zip(da, db) if max(abs(x[i] - y[i]) for i in range(3)) > 8)
        return {"changed_pixels": n, "of": len(da), "pct": round(100.0 * n / len(da), 2)}


    def cap(**kw):
        params = {"angles": ["three_quarter"], "resolution": 256}
        params.update(kw)
        res = ok("capture_viewport", params, 300)
        return png_of(res), res.get("warnings") or [], res["images"][0].get("blank")


    fresh()
    py("import maya.cmds as cmds\n"
       "cmds.polyPlane(name='ground', w=6, h=6); cmds.polyCube(name='box'); cmds.xform('box', t=(0, 0.5, 0))\n"
       "sh = cmds.shadingNode('lambert', asShader=True, name='grey'); sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name='greySG')\n"
       "cmds.connectAttr(sh + '.outColor', sg + '.surfaceShader'); cmds.sets('ground', 'box', e=True, forceElement=sg)\nTrue", "scene")
    d_default, w1, b1 = cap(lighting="default")
    d_scene_nolight, w2, b2 = cap(lighting="scene")
    show("D1 no lights: default vs scene", {"default": stats(d_default), "scene": stats(d_scene_nolight),
                                           "diff": diff(d_default, d_scene_nolight), "scene warnings": w2, "blank": [b1, b2]})
    open(os.path.join(OUT, "D1_default.png"), "wb").write(d_default)
    open(os.path.join(OUT, "D1_scene_nolight.png"), "wb").write(d_scene_nolight)

    py("import maya.cmds as cmds\n"
       "l = cmds.directionalLight(name='sun', intensity=1.2); t = cmds.listRelatives(l, p=True)[0]\n"
       "cmds.xform(t, ro=(-55, 35, 0)); cmds.setAttr(l + '.useDepthMapShadows', 1)\nTrue", "light")
    out = {}
    for shading in ("smoothShaded", "flatShaded", "wireframe"):
        off, w_off, _ = cap(lighting="scene", shading=shading, shadows=False)
        on, w_on, _ = cap(lighting="scene", shading=shading, shadows=True)
        open(os.path.join(OUT, "D2_%s_shadows_off.png" % shading), "wb").write(off)
        open(os.path.join(OUT, "D2_%s_shadows_on.png" % shading), "wb").write(on)
        out[shading] = {"off": stats(off), "on": stats(on), "diff": diff(off, on), "on warnings": w_on}
    show("D2 shadows on/off per shading (scene light with depth-map shadows)", out)

    out = {}
    for shading in ("smoothShaded", "wireframe"):
        beauty, _, _ = cap(lighting="scene", shading=shading, buffer="beauty")
        ssao, w_ssao, _ = cap(lighting="scene", shading=shading, buffer="ssao")
        open(os.path.join(OUT, "D3_%s_beauty.png" % shading), "wb").write(beauty)
        open(os.path.join(OUT, "D3_%s_ssao.png" % shading), "wb").write(ssao)
        out[shading] = {"beauty": stats(beauty), "ssao": stats(ssao), "diff": diff(beauty, ssao), "ssao warnings": w_ssao}
    show("D3 ssao vs beauty per shading", out)


if 'D' in PARTS:
    part_d()



fresh()
print("findings ->", os.path.join(OUT, "findings.json"))
