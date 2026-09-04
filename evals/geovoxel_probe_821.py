"""#821 PROBE: bind_skin method=geodesicVoxel has never been sent to a Maya.
Records, does not assert.

  P0. the skinCluster flags Maya 2027 actually has for bindMethod 3 / 2
  P1. fixture tube (3-joint chain): closestDistance vs geodesicVoxel OVER THE
      WIRE - the first live geodesicVoxel call; bind time, per_joint, weight
      delta between the two methods
  P2. two legs in ONE mesh, 4 cm apart, each with its own 3-joint chain under a
      pelvis: how much of the LEFT leg's weight lands on RIGHT-leg joints under
      each method (the reason geodesicVoxel exists)
  P3. pose the left hip 45 deg under each bind: how far do RIGHT-leg vertices
      move (the consumer-visible symptom of P2's bleed)
  P4. resolution sweep, direct cmds.skinCluster(bindMethod=3,
      geodesicVoxelParams=(res, True)): time and bleed at 64..1024
  P5. open plane and a dense sphere (~20k verts): does geodesicVoxel bind, how
      long, unweighted count
  P6. export_fbx(include_skins) over the wire on the geodesic legs bind
  P7. heatMap in a SEPARATE mayapy process under a kill timeout (it hung the
      GUI Maya in #797): closed tube, open plane, two-shell legs

No captures. Agent Maya on 9878 only, repo cwd.
Run:  MAYA_MCP_PORT=9878 python evals/geovoxel_probe_821.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877:
    raise SystemExit("refusing the user's Maya")
OUT = os.path.join(_HERE, "geovoxel_probe_821")
os.makedirs(OUT, exist_ok=True)
FINDINGS = {}
MAYAPY = r"E:\Autodesk\Maya2027\bin\mayapy.exe"


def ok(command, params, timeout_s=600.0):
    r = call(command, params, timeout_s=timeout_s, port=PORT)
    if r.get("status") != "ok":
        raise SystemExit("%s failed: %s" % (command, json.dumps(r.get("error"), indent=1)))
    return r.get("result") or {}


def result_or_error(command, params, timeout_s=600.0):
    t0 = time.time()
    r = call(command, params, timeout_s=timeout_s, port=PORT)
    dt = round(time.time() - t0, 2)
    if r.get("status") == "ok":
        out = dict(r.get("result") or {})
        out["_wire_s"] = dt
        return out
    return {"ERROR": r.get("error"), "_wire_s": dt}


def py(code, what="r", timeout_s=600.0):
    code = textwrap.dedent(code).strip()
    # execute_python only sends a value back for a trailing bare expression.
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
    with open(os.path.join(OUT, "findings.json"), "w", encoding="utf-8") as fh:
        json.dump(FINDINGS, fh, indent=1, default=str)
    print("\n--- %s ---" % label)
    print(json.dumps(value, indent=1, sort_keys=True, default=str))


# Scene builders + measurement helpers, defined once in the persistent namespace.
LIB = r'''
import time
import maya.cmds as cmds
import maya.mel as mel
import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma

def _chain(prefix, pts, parent=None):
    cmds.select(clear=True)
    if parent:
        cmds.select(parent)
    names = []
    for i, p in enumerate(pts):
        j = cmds.joint(name="%s_%d" % (prefix, i), position=p)
        cmds.setAttr(j + ".segmentScaleCompensate", 0)
        names.append(j)
    cmds.joint(names[0], edit=True, orientJoint="xyz", secondaryAxisOrient="yup", children=True, zeroScaleOrient=True)
    return names

def build_tube():
    cmds.file(new=True, force=True)
    m = cmds.polyCylinder(name="tube", radius=0.3, height=2.0, subdivisionsY=6, ch=False)[0]
    cmds.xform(m, ws=True, t=[0, 1, 0])
    cmds.makeIdentity(m, apply=True, t=1, r=1, s=1)
    j = _chain("tube", [[0, 0, 0], [0, 1, 0], [0, 2, 0]])
    return {"mesh": cmds.ls(m, long=True)[0], "root": cmds.ls(j[0], long=True)[0]}

def build_legs(gap=0.04, sy=12):
    """Two legs, radius 0.12, 1.0 tall, GAP apart, united into one mesh.
    Chains: pelvis at (0,1.05,0) -> hip_L/hip_R at top of each leg -> knee -> ankle."""
    cmds.file(new=True, force=True)
    r = 0.12
    x = r + gap / 2.0
    parts = []
    for side, sx in (("L", -x), ("R", x)):
        c = cmds.polyCylinder(name="leg_" + side, radius=r, height=1.0, subdivisionsY=sy, subdivisionsX=16, ch=False)[0]
        cmds.xform(c, ws=True, t=[sx, 0.5, 0])
        parts.append(c)
    m = cmds.polyUnite(parts, name="legs", ch=False)[0]
    cmds.makeIdentity(m, apply=True, t=1, r=1, s=1)
    cmds.select(clear=True)
    pelvis = cmds.joint(name="pelvis", position=[0, 1.05, 0])
    cmds.setAttr(pelvis + ".segmentScaleCompensate", 0)
    for side, sx in (("L", -x), ("R", x)):
        _chain("leg" + side, [[sx, 1.0, 0], [sx, 0.5, 0], [sx, 0.0, 0]], parent=pelvis)
    return {"mesh": cmds.ls(m, long=True)[0], "root": cmds.ls(pelvis, long=True)[0], "x": x, "gap": gap}

def build_plane():
    cmds.file(new=True, force=True)
    m = cmds.polyPlane(name="sheet", width=2, height=2, subdivisionsX=10, subdivisionsY=10, ch=False)[0]
    j = _chain("sheet", [[-1, 0, 0], [0, 0, 0], [1, 0, 0]])
    return {"mesh": cmds.ls(m, long=True)[0], "root": cmds.ls(j[0], long=True)[0]}

def build_dense():
    cmds.file(new=True, force=True)
    m = cmds.polySphere(name="ball", radius=1, subdivisionsAxis=200, subdivisionsHeight=100, ch=False)[0]
    j = _chain("ball", [[0, -1, 0], [0, 0, 0], [0, 1, 0]])
    return {"mesh": cmds.ls(m, long=True)[0], "root": cmds.ls(j[0], long=True)[0], "verts": cmds.polyEvaluate(m, v=True)}

def weights(sc, mesh):
    shape = cmds.listRelatives(mesh, s=True, f=True, ni=True)[0]
    sel = om.MSelectionList(); sel.add(shape); sel.add(sc)
    dag = sel.getDagPath(0)
    fn = oma.MFnSkinCluster(sel.getDependNode(1))
    cf = om.MFnSingleIndexedComponent(); comp = cf.create(om.MFn.kMeshVertComponent)
    n = om.MFnMesh(dag).numVertices
    cf.setCompleteData(n)
    w, ncols = fn.getWeights(dag, comp)
    infl = [dp.partialPathName() for dp in fn.influenceObjects()]
    return infl, list(w), n

def positions(mesh):
    shape = cmds.listRelatives(mesh, s=True, f=True, ni=True)[0]
    sel = om.MSelectionList(); sel.add(shape)
    return [(p.x, p.y, p.z) for p in om.MFnMesh(sel.getDagPath(0)).getPoints(om.MSpace.kWorld)]

def stats(sc, mesh, tol=1e-4):
    infl, w, n = weights(sc, mesh)
    k = len(infl)
    unweighted = 0; counts = [0]*k; sums = [0.0]*k; maxinfl = 0
    for v in range(n):
        held = 0
        for j in range(k):
            x = w[v*k+j]
            if x > tol:
                held += 1; counts[j] += 1; sums[j] += x
        unweighted += (held == 0); maxinfl = max(maxinfl, held)
    return {"influences": infl, "verts": n, "unweighted": unweighted, "max_held": maxinfl,
            "per_joint": {infl[j]: {"verts": counts[j], "mean": round(sums[j]/counts[j], 4) if counts[j] else 0.0} for j in range(k)}}

def bleed(sc, mesh):
    """Left-leg vertices (x<0): total weight on RIGHT-leg joints, and vice versa."""
    infl, w, n = weights(sc, mesh)
    pos = positions(mesh)
    k = len(infl)
    out = {}
    for side, other, sign in (("L", "R", -1), ("R", "L", 1)):
        cols = [j for j, name in enumerate(infl) if name.startswith("leg" + other)]
        verts = [v for v in range(n) if sign * pos[v][0] > 0]
        per = [sum(w[v*k+j] for j in cols) for v in verts]
        bad = [b for b in per if b > 0.01]
        out[side] = {"verts": len(verts), "verts_with_other_leg_weight_gt_0.01": len(bad),
                     "max_other_leg_weight": round(max(per), 4) if per else 0.0,
                     "mean_other_leg_weight": round(sum(per)/len(per), 4) if per else 0.0}
    return out

def bind(mesh, root, method, res=None, maxinf=4):
    kw = dict(bindMethod=method, maximumInfluences=maxinf, obeyMaxInfluences=True, toSelectedBones=False, name="probe_skin")
    t0 = time.time()
    sc = cmds.skinCluster(root, mesh, **kw)[0]
    if res is not None:
        # skinCluster has no resolution flag; geomBind is where the voxel
        # parameters live (bindMethod 3 = geodesic voxel).
        cmds.geomBind(sc, bindMethod=3, geodesicVoxelParams=(res, True), maxInfluences=maxinf)
    return sc, round(time.time() - t0, 3)

def unbind(sc):
    cmds.skinCluster(sc, edit=True, unbind=True)

def pose_tug(sc, mesh, joint, rot):
    """Rotate JOINT by ROT, return max displacement of right-leg (x>0) and left-leg verts, then reset."""
    before = positions(mesh)
    cmds.setAttr(joint + ".rotate", *rot)
    after = positions(mesh)
    cmds.setAttr(joint + ".rotate", 0, 0, 0)
    d = [((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2) ** 0.5 for a, b in zip(after, before)]
    r = [d[i] for i in range(len(d)) if before[i][0] > 0]
    l = [d[i] for i in range(len(d)) if before[i][0] < 0]
    return {"right_leg_max_move": round(max(r), 4), "right_leg_verts_moved_gt_1mm": sum(1 for v in r if v > 0.001),
            "left_leg_max_move": round(max(l), 4)}
'''


def main():
    py(LIB + "\nr = 1")

    # P0 --------------------------------------------------------------
    show("P0_flags", py('''
        h = mel.eval("help skinCluster")
        lines = [l.strip() for l in h.splitlines() if any(k in l.lower() for k in ("geodesic", "heat", "bindmethod", "smoothweights", "voxel"))]
        g = mel.eval("help geomBind")
        r = {"skinCluster_flag_lines": lines, "geomBind_help": g, "maya": cmds.about(version=True)}
    ''', "r"))

    # P1 --------------------------------------------------------------
    scene = py(LIB + "\nr = build_tube()", "r")
    close = result_or_error("bind_skin", {"mesh": scene["mesh"], "root": scene["root"], "method": "closestDistance"})
    w_close = py("r = weights(%r, %r)" % (close.get("skin_cluster"), scene["mesh"]), "r")
    py("unbind(%r)" % close.get("skin_cluster"))
    py("BEFORE = set(cmds.ls()); r = len(BEFORE)")
    geo = result_or_error("bind_skin", {"mesh": scene["mesh"], "root": scene["root"], "method": "geodesicVoxel"})
    w_geo = py("r = weights(%r, %r)" % (geo.get("skin_cluster"), scene["mesh"]), "r") if "ERROR" not in geo else None
    delta = None
    if w_geo:
        a, b = w_close[1], w_geo[1]
        diffs = [abs(x - y) for x, y in zip(a, b)]
        delta = {"same_influence_order": w_close[0] == w_geo[0], "max_abs_weight_delta": round(max(diffs), 4),
                 "mean_abs_weight_delta": round(sum(diffs) / len(diffs), 5),
                 "verts_changed_gt_0.05": sum(1 for v in range(w_close[2]) if max(diffs[v * 3:(v + 1) * 3]) > 0.05)}
    extra_nodes = py("r = sorted(set(cmds.ls()) - BEFORE)")
    show("P1_tube_wire", {"closestDistance": close, "geodesicVoxel": geo, "weight_delta": delta,
                          "history_after_geo": py("r = cmds.listHistory(%r, pdo=True)" % scene["mesh"], "r"),
                          "unusual_nodes": extra_nodes})

    # P2 / P3 ---------------------------------------------------------
    scene = py(LIB + "\nr = build_legs(gap=0.04)", "r")
    legs = {"scene": scene}
    for method, code in (("closestDistance", 0), ("geodesicVoxel", 3)):
        b = py("r = bind(%r, %r, %d)" % (scene["mesh"], scene["root"], code), "r")
        sc = b[0]
        entry = {"bind_s": b[1], "stats": py("r = stats(%r, %r)" % (sc, scene["mesh"]), "r"),
                 "bleed": py("r = bleed(%r, %r)" % (sc, scene["mesh"]), "r"),
                 "tug_hipL_45": py("r = pose_tug(%r, %r, 'legL_0', (0, 0, 45))" % (sc, scene["mesh"]), "r")}
        legs[method] = entry
        py("unbind(%r)" % sc)
    show("P2_P3_legs_gap4cm", legs)

    # bigger gap: does closestDistance still bleed at 20 cm?
    scene2 = py("r = build_legs(gap=0.20)", "r")
    wide = {}
    for method, code in (("closestDistance", 0), ("geodesicVoxel", 3)):
        b = py("r = bind(%r, %r, %d)" % (scene2["mesh"], scene2["root"], code), "r")
        wide[method] = {"bind_s": b[1], "bleed": py("r = bleed(%r, %r)" % (b[0], scene2["mesh"]), "r"),
                        "tug_hipL_45": py("r = pose_tug(%r, %r, 'legL_0', (0, 0, 45))" % (b[0], scene2["mesh"]), "r")}
        py("unbind(%r)" % b[0])
    show("P2b_legs_gap20cm", wide)

    # P4 --------------------------------------------------------------
    scene = py("r = build_legs(gap=0.04)", "r")
    sweep = {}
    for res in (64, 128, 256, 512, 1024):
        try:
            b = py("r = bind(%r, %r, 3, res=%d)" % (scene["mesh"], scene["root"], res), "r", timeout_s=900)
        except SystemExit as exc:
            sweep[str(res)] = {"ERROR": str(exc)[:600]}
            continue
        sweep[str(res)] = {"bind_s": b[1], "bleed": py("r = bleed(%r, %r)" % (b[0], scene["mesh"]), "r"),
                           "unweighted": py("r = stats(%r, %r)['unweighted']" % (b[0], scene["mesh"]), "r")}
        py("unbind(%r)" % b[0])
    show("P4_resolution_sweep", sweep)

    # P5 --------------------------------------------------------------
    scene = py("r = build_plane()", "r")
    plane = {}
    for method in ("closestDistance", "geodesicVoxel"):
        r = result_or_error("bind_skin", {"mesh": scene["mesh"], "root": scene["root"], "method": method})
        plane[method] = {k: r.get(k) for k in ("_wire_s", "unweighted_vertices", "warnings", "per_joint", "ERROR")}
        if r.get("skin_cluster"):
            py("unbind(%r)" % r["skin_cluster"])
    show("P5a_open_plane", plane)

    scene = py("r = build_dense()", "r")
    dense = {"verts": scene["verts"]}
    for method in ("closestDistance", "geodesicVoxel"):
        r = result_or_error("bind_skin", {"mesh": scene["mesh"], "root": scene["root"], "method": method}, timeout_s=900)
        dense[method] = {k: r.get(k) for k in ("_wire_s", "unweighted_vertices", "warnings", "ERROR")}
        if r.get("skin_cluster"):
            py("unbind(%r)" % r["skin_cluster"])
    show("P5b_dense_sphere", dense)

    # P6 --------------------------------------------------------------
    scene = py("r = build_legs(gap=0.04)", "r")
    geo = result_or_error("bind_skin", {"mesh": scene["mesh"], "root": scene["root"], "method": "geodesicVoxel"})
    path = os.path.join(OUT, "legs_geodesic.fbx").replace("\\", "/")
    exp = result_or_error("export_fbx", {"path": path, "metres_per_unit": 1.0, "include_skins": True}, timeout_s=300)
    show("P6_export", {"bind": {k: geo.get(k) for k in ("_wire_s", "unweighted_vertices", "warnings", "ERROR")},
                       "export": {k: exp.get(k) for k in ("bytes", "skin", "warnings", "ERROR", "_wire_s")}})

    # P7 --------------------------------------------------------------
    heat = {}
    for case in ("tube", "plane", "legs"):
        script = os.path.join(OUT, "heatmap_%s.py" % case)
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent('''
                import json, sys, time
                import maya.standalone
                maya.standalone.initialize(name="python")
                import maya.cmds as cmds
                exec(open(%r, encoding="utf-8").read())
                scene = {"tube": build_tube, "plane": build_plane, "legs": build_legs}[%r]()
                t0 = time.time()
                try:
                    sc = cmds.skinCluster(scene["root"], scene["mesh"], bindMethod=2, maximumInfluences=4, obeyMaxInfluences=True, toSelectedBones=False, name="heat")[0]
                    out = {"ok": True, "bind_s": round(time.time() - t0, 3), "stats": stats(sc, scene["mesh"])}
                    if %r == "legs":
                        out["bleed"] = bleed(sc, scene["mesh"])
                except Exception as exc:
                    out = {"ok": False, "bind_s": round(time.time() - t0, 3), "error": str(exc)}
                print("RESULT=" + json.dumps(out))
                sys.stdout.flush()
            ''') % (os.path.join(OUT, "lib.py"), case, case))
        with open(os.path.join(OUT, "lib.py"), "w", encoding="utf-8") as fh:
            fh.write(LIB)
        t0 = time.time()
        try:
            p = subprocess.run([MAYAPY, script], capture_output=True, text=True, timeout=180)
            line = [l for l in p.stdout.splitlines() if l.startswith("RESULT=")]
            heat[case] = json.loads(line[0][7:]) if line else {"no_result": True, "rc": p.returncode, "stdout_tail": p.stdout[-800:], "stderr_tail": p.stderr[-800:]}
        except subprocess.TimeoutExpired:
            heat[case] = {"HUNG": True, "killed_after_s": round(time.time() - t0, 1)}
        heat[case]["wall_s"] = round(time.time() - t0, 1)
        show("P7_heatMap_" + case, heat[case])

    print("\nfindings ->", os.path.join(OUT, "findings.json"))


if __name__ == "__main__":
    main()
