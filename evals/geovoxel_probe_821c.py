"""#821 PROBE C: the geomBind node, the open-mesh failure signature, and heatMap
on the harder closed meshes in the GUI Maya.

  C1. geomBind1: node type, connections, in the mesh's history?, delete it ->
      weights unchanged?; export_fbx over the wire on a real geodesic bind;
      does the .fbx carry a geomBind record
  C2. open plane: geomBind's return value and any stdout/stderr; boundary edge
      counts (API MItMeshEdge.onBoundary) for plane / tube / legs / overlap
  C3. heatMap in the GUI Maya under a socket timeout: legs (two closed shells),
      overlap cubes (self-intersecting closed shells), dense sphere. A hang
      means kill the agent Maya.

Run:  MAYA_MCP_PORT=9878 python evals/geovoxel_probe_821c.py
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
from geovoxel_probe_821b import LIB_B  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877:
    raise SystemExit("refusing the user's Maya")
OUT = os.path.join(_HERE, "geovoxel_probe_821")
FINDINGS = {}


def ok(command, params, timeout_s=600.0):
    r = call(command, params, timeout_s=timeout_s, port=PORT)
    if r.get("status") != "ok":
        raise SystemExit("%s failed: %s" % (command, json.dumps(r.get("error"), indent=1)))
    return r.get("result") or {}


def result_or_error(command, params, timeout_s=600.0):
    r = call(command, params, timeout_s=timeout_s, port=PORT)
    return (r.get("result") or {}) if r.get("status") == "ok" else {"ERROR": r.get("error")}


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
    with open(os.path.join(OUT, "findings_c.json"), "w", encoding="utf-8") as fh:
        json.dump(FINDINGS, fh, indent=1, default=str)
    print("\n--- %s ---" % label)
    print(json.dumps(value, indent=1, sort_keys=True, default=str))


LIB_C = LIB_B + r'''

def boundary_edges(mesh):
    shape = cmds.listRelatives(mesh, s=True, f=True, ni=True)[0]
    sel = om.MSelectionList(); sel.add(shape)
    it = om.MItMeshEdge(sel.getDagPath(0))
    n = 0
    while not it.isDone():
        n += it.onBoundary()
        it.next()
    return n
'''


def timed_heat(scene, timeout_s):
    t0 = time.time()
    try:
        r = call("execute_python", {"code": textwrap.dedent('''
            import time
            t0 = time.time()
            sc = cmds.skinCluster(%r, %r, bindMethod=2, maximumInfluences=4, obeyMaxInfluences=True, toSelectedBones=False, name="heat")[0]
            st = stats(sc, %r)
            st.pop("influences", None)
            r = {"bind_s": round(time.time() - t0, 3), "stats": st}
            r
        ''' % (scene["root"], scene["mesh"], scene["mesh"])).strip()}, timeout_s=timeout_s, port=PORT)
        heat = r.get("result") if r.get("status") == "ok" else {"ERROR": r.get("error")}
        if isinstance(heat, dict) and heat.get("traceback"):
            heat = {"traceback": heat["traceback"][-1500:]}
        elif isinstance(heat, dict) and heat.get("result_repr"):
            heat = structured_result(heat, "heat")
    except (socket.timeout, TimeoutError, OSError) as exc:
        heat = {"HUNG_OR_TIMEOUT": repr(exc)}
    heat["wall_s"] = round(time.time() - t0, 1)
    return heat


def main():
    py(LIB_C + "\nr = 1")

    # C1 --------------------------------------------------------------
    scene = py("r = build_legs(gap=0.04)", "r")
    c1 = py('''
        sc, ts, tg = gbind(%r, %r)
        gb = cmds.ls(type="geomBind")
        node = gb[0]
        w1 = weights(sc, %r)[1]
        r = {"geomBind_nodes": gb, "nodeType": cmds.nodeType(node),
             "attrs": {a: cmds.getAttr(node + "." + a) for a in (cmds.listAttr(node, keyable=False, userDefined=False) or []) if a in ("bindMethod","falloff","geodesicVoxelParams","maxInfluences","resolution","validate","gvp","fo")},
             "all_attrs": [a for a in (cmds.listAttr(node) or []) if not a.startswith(("message","caching","frozen","isHistoricallyInteresting","nodeState","binMembership"))][:40],
             "connections": cmds.listConnections(node, connections=True, plugs=True) or [],
             "in_mesh_history": node in (cmds.listHistory(%r, pdo=True) or []),
             "in_skin_history": node in (cmds.listHistory(sc) or [])}
        cmds.delete(node)
        w2 = weights(sc, %r)[1]
        r["weights_unchanged_after_delete"] = max(abs(a - b) for a, b in zip(w1, w2)) < 1e-9
        r["skin_alive_after_delete"] = cmds.objExists(sc)
        SC = sc
    ''' % (scene["mesh"], scene["root"], scene["mesh"], scene["mesh"], scene["mesh"]), "r")
    show("C1_geomBind_node", c1)

    # export with the geomBind node PRESENT (re-bind), via the wire
    scene = py("r = build_legs(gap=0.04)", "r")
    py("sc, ts, tg = gbind(%r, %r)" % (scene["mesh"], scene["root"]))
    path = os.path.join(OUT, "legs_geomBind.fbx").replace("\\", "/")
    exp = result_or_error("export_fbx", {"path": path, "metres_per_unit": 1.0, "include_skins": True}, timeout_s=300)
    fbx_has_geombind = None
    if os.path.exists(path):
        with open(path, "rb") as fh:
            fbx_has_geombind = b"geomBind" in fh.read()
    show("C1b_export_with_geomBind", {"export": {k: exp.get(k) for k in ("bytes", "skin", "warnings", "ERROR")},
                                      "fbx_mentions_geomBind": fbx_has_geombind})

    # C2 --------------------------------------------------------------
    scene = py("r = build_plane()", "r")
    c2 = ok("execute_python", {"code": textwrap.dedent('''
        sc = cmds.skinCluster(%r, %r, bindMethod=0, maximumInfluences=4, obeyMaxInfluences=True, toSelectedBones=False, name="probe_skin")[0]
        w0 = weights(sc, %r)[1]
        ret = cmds.geomBind(sc, bindMethod=3, geodesicVoxelParams=(256, True), maxInfluences=4)
        w1 = weights(sc, %r)[1]
        r = {"geomBind_return": ret, "weights_changed_by_geomBind": max(abs(a - b) for a, b in zip(w0, w1)) > 1e-9,
             "stats_after": stats(sc, %r)}
        r
    ''' % (scene["root"], scene["mesh"], scene["mesh"], scene["mesh"], scene["mesh"])).strip()})
    show("C2_open_plane_geomBind", {"stdout": c2.get("stdout"), "stderr": c2.get("stderr"), "traceback": c2.get("traceback"),
                                    "result": structured_result(c2, "c2") if c2.get("result_repr") else None})
    show("C2b_boundary_edges", {
        "plane": py("s = build_plane(); r = boundary_edges(s['mesh'])", "r"),
        "tube": py("s = build_tube(); r = boundary_edges(s['mesh'])", "r"),
        "legs": py("s = build_legs(); r = boundary_edges(s['mesh'])", "r"),
        "overlap": py("s = build_overlap(); r = boundary_edges(s['mesh'])", "r"),
        "open_cylinder_no_caps": py('''
            cmds.file(new=True, force=True)
            m = cmds.polyCylinder(name="pipe", radius=0.3, height=2.0, subdivisionsY=6, ch=False)[0]
            cmds.delete(m + ".f[120:121]")  # both caps of a 20x6 cylinder
            r = {"boundary": boundary_edges(m), "faces": cmds.polyEvaluate(m, f=True)}
        ''', "r"),
    })
    # geodesic on the open pipe (a tube with the caps deleted - the typical modelled-limb case)
    pipe = py('''
        cmds.file(new=True, force=True)
        m = cmds.polyCylinder(name="pipe", radius=0.3, height=2.0, subdivisionsY=6, ch=False)[0]
        cmds.delete(m + ".f[120:121]")
        cmds.xform(m, ws=True, t=[0, 1, 0]); cmds.makeIdentity(m, apply=True, t=1, r=1, s=1)
        j = _chain("pipe", [[0, 0, 0], [0, 1, 0], [0, 2, 0]])
        sc, ts, tg = gbind(cmds.ls(m, long=True)[0], j[0])
        st = stats(sc, m); st.pop("influences", None)
        r = {"boundary_edges": boundary_edges(m), "geomBind_s": tg, "stats": st}
    ''', "r")
    show("C2c_open_pipe_geomBind", pipe)

    # C3 --------------------------------------------------------------
    for name, builder, tmo in (("legs", "build_legs(gap=0.04)", 60), ("overlap", "build_overlap()", 60), ("dense", "build_dense()", 120)):
        scene = py("r = " + builder, "r")
        heat = timed_heat(scene, tmo)
        show("C3_heatMap_gui_" + name, heat)
        if "HUNG_OR_TIMEOUT" in heat:
            print("agent Maya is hung - stopping here; kill pid and relaunch")
            break

    print("\nfindings ->", os.path.join(OUT, "findings_c.json"))


if __name__ == "__main__":
    main()
