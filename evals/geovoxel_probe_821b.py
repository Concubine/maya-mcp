"""#821 PROBE B: round A showed skinCluster(bindMethod=3) alone produces a
DEGENERATE bind (every vertex on the leaf joints), and that the geodesic voxel
work lives in `geomBind`. This round measures the geomBind route itself.

  B1. legs (4 cm gap): skinCluster(bm=0)+geomBind vs skinCluster(bm=3)+geomBind
      - are the weights identical; stats, bleed, tug
  B2. falloff sweep 0.0 / 0.2 / 0.5 / 1.0 at res 256: influences per vertex,
      knee blending (verts with 2+ influences)
  B3. maxInfluences 4 vs 8 on geomBind: max_held
  B4. open plane, dense sphere (~20k verts), overlapping shells (two united
      cubes that intersect): does geomBind 256 run, time, unweighted, bleed
  B5. what geomBind leaves in the scene (node diff), and whether undo reverts it
  B6. LAST, in the GUI Maya: heatMap on a CLOSED tube under a 60 s socket
      timeout - #797's hang was an open plane; mayapy refuses heatMap outright
      ("Unable to create an offscreen OpenGL buffer"). A hang here means kill
      the agent Maya.

Run:  MAYA_MCP_PORT=9878 python evals/geovoxel_probe_821b.py
"""
from __future__ import annotations

import json
import os
import socket
import sys
import textwrap
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402
from geovoxel_probe_821 import LIB  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877:
    raise SystemExit("refusing the user's Maya")
OUT = os.path.join(_HERE, "geovoxel_probe_821")
os.makedirs(OUT, exist_ok=True)
FINDINGS = {}


def ok(command, params, timeout_s=600.0):
    r = call(command, params, timeout_s=timeout_s, port=PORT)
    if r.get("status") != "ok":
        raise SystemExit("%s failed: %s" % (command, json.dumps(r.get("error"), indent=1)))
    return r.get("result") or {}


def py(code, what="r", timeout_s=600.0):
    code = textwrap.dedent(code).strip()
    if "r =" in code or "r=" in code:
        code += "\nr"
    else:
        code += "\nr = 0\nr"
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


LIB_B = LIB + r'''

def gbind(mesh, root, bm_skin=0, res=256, falloff=None, maxinf=4):
    t0 = time.time()
    sc = cmds.skinCluster(root, mesh, bindMethod=bm_skin, maximumInfluences=maxinf, obeyMaxInfluences=True,
                          toSelectedBones=False, name="probe_skin")[0]
    t1 = time.time()
    kw = dict(bindMethod=3, geodesicVoxelParams=(res, True), maxInfluences=maxinf)
    if falloff is not None:
        kw["falloff"] = falloff
    cmds.geomBind(sc, **kw)
    return sc, round(t1 - t0, 3), round(time.time() - t1, 3)

def held_hist(sc, mesh, tol=1e-4):
    infl, w, n = weights(sc, mesh)
    k = len(infl)
    hist = {}
    for v in range(n):
        held = sum(1 for j in range(k) if w[v*k+j] > tol)
        hist[held] = hist.get(held, 0) + 1
    return {str(a): b for a, b in sorted(hist.items())}

def build_overlap():
    """Two cubes that INTERSECT, united - overlapping shells, the case the tool text promises."""
    cmds.file(new=True, force=True)
    a = cmds.polyCube(name="blockA", w=1, h=1, d=1, sx=6, sy=6, sz=6, ch=False)[0]
    b = cmds.polyCube(name="blockB", w=1, h=1, d=1, sx=6, sy=6, sz=6, ch=False)[0]
    cmds.xform(b, ws=True, t=[0.6, 0.6, 0])
    m = cmds.polyUnite([a, b], name="blocks", ch=False)[0]
    cmds.makeIdentity(m, apply=True, t=1, r=1, s=1)
    j = _chain("blk", [[-0.4, -0.4, 0], [0.3, 0.3, 0], [1.0, 1.0, 0]])
    return {"mesh": cmds.ls(m, long=True)[0], "root": cmds.ls(j[0], long=True)[0],
            "shells": cmds.polyEvaluate(m, shell=True), "verts": cmds.polyEvaluate(m, v=True)}
'''


def main():
    py(LIB_B + "\nr = 1")

    # B1 --------------------------------------------------------------
    scene = py("r = build_legs(gap=0.04)", "r")
    b1 = {}
    tables = {}
    for label, bm in (("bm0_then_geomBind", 0), ("bm3_then_geomBind", 3)):
        b = py("r = gbind(%r, %r, bm_skin=%d)" % (scene["mesh"], scene["root"], bm), "r")
        sc = b[0]
        tables[label] = py("r = weights(%r, %r)[1]" % (sc, scene["mesh"]), "r")
        b1[label] = {"skin_s": b[1], "geomBind_s": b[2],
                     "stats": py("r = stats(%r, %r)" % (sc, scene["mesh"]), "r"),
                     "bleed": py("r = bleed(%r, %r)" % (sc, scene["mesh"]), "r"),
                     "held_hist": py("r = held_hist(%r, %r)" % (sc, scene["mesh"]), "r"),
                     "tug_hipL_45": py("r = pose_tug(%r, %r, 'legL_0', (0, 0, 45))" % (sc, scene["mesh"]), "r")}
        py("unbind(%r)" % sc)
    a, b = tables["bm0_then_geomBind"], tables["bm3_then_geomBind"]
    b1["weight_tables_identical"] = max(abs(x - y) for x, y in zip(a, b)) < 1e-6
    show("B1_geomBind_after_bm0_vs_bm3", b1)

    # B2 --------------------------------------------------------------
    b2 = {}
    for fo in (None, 0.0, 0.2, 0.5, 1.0):
        b = py("r = gbind(%r, %r, falloff=%r)" % (scene["mesh"], scene["root"], fo), "r")
        b2[str(fo)] = {"geomBind_s": b[2], "held_hist": py("r = held_hist(%r, %r)" % (b[0], scene["mesh"]), "r"),
                       "per_joint": py("r = stats(%r, %r)['per_joint']" % (b[0], scene["mesh"]), "r"),
                       "bleed_L_max": py("r = bleed(%r, %r)['L']['max_other_leg_weight']" % (b[0], scene["mesh"]), "r")}
        py("unbind(%r)" % b[0])
    show("B2_falloff_sweep_res256", b2)

    # B3 --------------------------------------------------------------
    b3 = {}
    for mi in (1, 4, 8):
        b = py("r = gbind(%r, %r, maxinf=%d)" % (scene["mesh"], scene["root"], mi), "r")
        b3[str(mi)] = {"held_hist": py("r = held_hist(%r, %r)" % (b[0], scene["mesh"]), "r"),
                       "skinCluster_maxInfluences_attr": py("r = cmds.getAttr(%r + '.maxInfluences')" % b[0], "r")}
        py("unbind(%r)" % b[0])
    show("B3_maxInfluences", b3)

    # B4 --------------------------------------------------------------
    b4 = {}
    for name, builder in (("open_plane", "build_plane()"), ("dense_sphere", "build_dense()"), ("overlap_cubes", "build_overlap()")):
        sc_ = py("r = " + builder, "r")
        try:
            b = py("r = gbind(%r, %r)" % (sc_["mesh"], sc_["root"]), "r", timeout_s=900)
        except SystemExit as exc:
            b4[name] = {"scene": sc_, "ERROR": str(exc)[:800]}
            continue
        entry = {"scene": sc_, "skin_s": b[1], "geomBind_s": b[2],
                 "stats": py("r = stats(%r, %r)" % (b[0], sc_["mesh"]), "r")}
        entry["stats"].pop("influences", None)
        b4[name] = entry
        py("unbind(%r)" % b[0])
    show("B4_other_meshes", b4)

    # B5 --------------------------------------------------------------
    scene = py("r = build_legs(gap=0.04)", "r")
    b5 = py('''
        before = set(cmds.ls())
        cmds.undoInfo(openChunk=True)
        sc, t_skin, t_geo = gbind(%r, %r)
        cmds.undoInfo(closeChunk=True)
        after = set(cmds.ls())
        w_geo = weights(sc, %r)[1]
        cmds.undo()
        still = cmds.objExists(sc)
        r = {"new_nodes": sorted(after - before), "skin_exists_after_undo": still,
             "history_after_undo": cmds.listHistory(%r, pdo=True)}
    ''' % (scene["mesh"], scene["root"], scene["mesh"], scene["mesh"]), "r")
    show("B5_nodes_and_undo", b5)

    # B6 --------------------------------------------------------------
    scene = py("r = build_tube()", "r")
    t0 = time.time()
    try:
        r = call("execute_python", {"code": textwrap.dedent('''
            import time
            t0 = time.time()
            sc = cmds.skinCluster(%r, %r, bindMethod=2, maximumInfluences=4, obeyMaxInfluences=True, toSelectedBones=False, name="heat")[0]
            r = {"bind_s": round(time.time() - t0, 3), "stats": stats(sc, %r)}
            r
        ''' % (scene["root"], scene["mesh"], scene["mesh"])).strip()}, timeout_s=60, port=PORT)
        heat = r.get("result") if r.get("status") == "ok" else {"ERROR": r.get("error")}
        if isinstance(heat, dict) and heat.get("traceback"):
            heat = {"traceback": heat["traceback"]}
        elif isinstance(heat, dict) and heat.get("result_repr"):
            heat = structured_result(heat, "heat")
    except (socket.timeout, TimeoutError, OSError) as exc:
        heat = {"HUNG_OR_TIMEOUT": repr(exc)}
    heat["wall_s"] = round(time.time() - t0, 1)
    show("B6_heatMap_closed_tube_gui", heat)

    print("\nfindings ->", os.path.join(OUT, "findings_b.json"))


if __name__ == "__main__":
    main()
