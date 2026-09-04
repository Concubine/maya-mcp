"""#821 LIVE GATE: bind_skin method=geodesicVoxel does a geodesic bind, and the
two methods that need a volume refuse a flat sheet before Maya sees it.

  1. two legs 4 cm apart in ONE mesh, each with its own 3-joint chain under a
     pelvis, bound geodesicVoxel over the wire: unweighted 0, every leg joint
     owns vertices, a geomBind node hangs off the skinCluster, NO left-leg
     vertex carries right-leg weight, and bending the left hip 45 deg moves
     no right-leg vertex more than 1 mm.
  2. the same rig bound closestDistance: the right leg IS dragged (>10 cm) -
     the discriminator is real, not a tautology.
  3. an open pipe (cylinder, caps deleted): geodesicVoxel binds and every
     joint owns vertices (boundary edges are not what fails).
  4. a flat polyPlane: geodesicVoxel and heatMap both refuse with "flat", the
     scene holds no skinCluster/geomBind afterwards, closestDistance binds.
  5. heatMap on a closed tube over the wire: binds, unweighted 0 (first live
     heatMap call).
  6. export_fbx(include_skins) on the geodesic legs: 0 unweighted file
     vertices, max influences <= 4.
  7. undo(steps=1) after the geodesic bind removes the skinCluster AND the
     geomBind node (one tool call, one undo step - #820).

No captures. DESTRUCTIVE: calls maya_new_scene. Agent Maya on 9878 only;
refuses 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1. Phase 0 asserts the live
Maya imports THIS working tree.

Run:  MAYA_MCP_PORT=9878 python evals/geodesic_voxel_live.py
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
          "calls new_scene. Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.",
          file=sys.stderr)
    raise SystemExit(2)

OUT = os.path.join(_HERE, "geodesic_voxel_live")
os.makedirs(OUT, exist_ok=True)
RESULTS = []


def check(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    print("%-4s %-76s %s" % ("PASS" if ok else "FAIL", label, detail), flush=True)


def raw(command, params, timeout_s=300.0):
    return call(command, params, timeout_s=timeout_s, port=PORT)


def ok(command, params, timeout_s=300.0):
    response = raw(command, params, timeout_s=timeout_s)
    if response.get("status") != "ok":
        raise SystemExit("%s failed: %s" % (command, response.get("error")))
    return response.get("result") or {}


def py(code, what, timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s), what)


def refused(response):
    return response.get("status") != "ok", json.dumps(response.get("error") or {})[:300]


LIB = '''
import maya.cmds as cmds
import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma

def legs_mesh(gap=0.04, r=0.12):
    x = r + gap / 2.0
    parts = []
    for side, sx in (("L", -x), ("R", x)):
        c = cmds.polyCylinder(name="leg_" + side, radius=r, height=1.0, subdivisionsY=12, subdivisionsX=16, ch=False)[0]
        cmds.xform(c, ws=True, t=[sx, 0.5, 0])
        parts.append(c)
    m = cmds.polyUnite(parts, name="legs", ch=False)[0]
    cmds.makeIdentity(m, apply=True, t=1, r=1, s=1)
    return cmds.ls(m, long=True)[0], x

def positions(mesh):
    shape = cmds.listRelatives(mesh, s=True, f=True, ni=True)[0]
    sel = om.MSelectionList(); sel.add(shape)
    return [(p.x, p.y, p.z) for p in om.MFnMesh(sel.getDagPath(0)).getPoints(om.MSpace.kWorld)]

def table(mesh):
    shape = cmds.listRelatives(mesh, s=True, f=True, ni=True)[0]
    sc = cmds.ls(cmds.listHistory(shape, pdo=True) or [], type="skinCluster")[0]
    sel = om.MSelectionList(); sel.add(shape); sel.add(sc)
    dag = sel.getDagPath(0)
    fn = oma.MFnSkinCluster(sel.getDependNode(1))
    cf = om.MFnSingleIndexedComponent(); comp = cf.create(om.MFn.kMeshVertComponent)
    n = om.MFnMesh(dag).numVertices
    cf.setCompleteData(n)
    w, _ = fn.getWeights(dag, comp)
    return [dp.partialPathName() for dp in fn.influenceObjects()], list(w), n

def cross_leg_bleed(mesh):
    infl, w, n = table(mesh)
    pos = positions(mesh)
    k = len(infl)
    right_cols = [j for j, name in enumerate(infl) if name.startswith("legR")]
    left = [v for v in range(n) if pos[v][0] < 0]
    return max(sum(w[v * k + j] for j in right_cols) for v in left)

def right_leg_move(mesh, before):
    after = positions(mesh)
    return max(((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2) ** 0.5
               for a, b in zip(after, before) if b[0] > 0)
'''

LEG_JOINTS = lambda x: [  # noqa: E731
    {"name": "pelvis", "position": [0, 1.05, 0], "parent": None},
    {"name": "legL_0", "position": [-x, 1.0, 0], "parent": "pelvis"},
    {"name": "legL_1", "position": [-x, 0.5, 0], "parent": "legL_0"},
    {"name": "legL_2", "position": [-x, 0.0, 0], "parent": "legL_1"},
    {"name": "legR_0", "position": [x, 1.0, 0], "parent": "pelvis"},
    {"name": "legR_1", "position": [x, 0.5, 0], "parent": "legR_0"},
    {"name": "legR_2", "position": [x, 0.0, 0], "parent": "legR_1"},
]


def build_legs():
    ok("new_scene", {"confirm": True})
    mesh, x = py(LIB + "\nlegs_mesh()", "legs")
    skel = ok("create_skeleton", {"joints": LEG_JOINTS(x)})
    joints = {j["name"].split("|")[-1]: j["name"] for j in skel["joints"]}
    return mesh, skel["root"], joints


# --------------------------------------------------------------- phase 0
print("=== 0. who answered, and whose code is it ===", flush=True)
ident = py("import os, maya_plugin\n{'file': maya_plugin.__file__, 'cwd': os.getcwd()}", "identity")
loaded = os.path.normcase(os.path.abspath(ident["file"]))
expected = os.path.normcase(os.path.join(REPO, "maya_plugin", "__init__.py"))
if loaded != expected:
    print("WRONG CODE: live Maya imports %s, not %s." % (loaded, expected), file=sys.stderr)
    raise SystemExit(2)
has = py("from maya_plugin.handlers import rigging\nhasattr(rigging, 'GEODESIC_RESOLUTION')", "loaded")
check("0. the #821 rigging handler is loaded in the live Maya", has is True)

# --------------------------------------------------------------- phase 1
print("\n=== 1. geodesicVoxel on two legs 4 cm apart ===", flush=True)
mesh, root, joints = build_legs()
res = ok("bind_skin", {"mesh": mesh, "root": root, "method": "geodesicVoxel"})
leg_rows = [p for p in res["per_joint"] if "leg" in p["joint"]]
check("1a. unweighted 0 and every leg joint owns vertices",
      res["unweighted_vertices"] == 0 and all(p["vertices"] > 0 for p in leg_rows),
      json.dumps({p["joint"].split("|")[-1]: p["vertices"] for p in res["per_joint"]}))
check("1b. no 'own no vertices' warning", not any("own no vertices" in w for w in res["warnings"]),
      json.dumps(res["warnings"]))
geom = py("cmds.ls(type='geomBind'), cmds.listConnections(%r + '.geomBind') or []" % res["skin_cluster"], "geom")
check("1c. a geomBind node is wired to the skinCluster", len(geom[0]) == 1 and geom[0][0] in geom[1], json.dumps(geom))
bleed = py("cross_leg_bleed(%r)" % mesh, "bleed")
check("1d. no left-leg vertex carries right-leg weight", bleed < 1e-6, "max %.6f" % bleed)
before = py("BEFORE = positions(%r); len(BEFORE)" % mesh, "n")
ok("pose_skeleton", {"root": root, "rotations": {joints["legL_0"]: [0, 0, 45]}})
move = py("right_leg_move(%r, BEFORE)" % mesh, "move")
check("1e. left hip bent 45 deg moves no right-leg vertex more than 1 mm", move < 0.001, "max %.4f m" % move)
ok("reset_pose", {"root": root})
GEO_MESH, GEO_ROOT = mesh, root

# --------------------------------------------------------------- phase 2
print("\n=== 2. the same rig, closestDistance ===", flush=True)
mesh, root, joints = build_legs()
res = ok("bind_skin", {"mesh": mesh, "root": root, "method": "closestDistance"})
py("BEFORE = positions(%r); len(BEFORE)" % mesh, "n")
ok("pose_skeleton", {"root": root, "rotations": {joints["legL_0"]: [0, 0, 45]}})
move_cd = py("right_leg_move(%r, BEFORE)" % mesh, "move")
check("2. closestDistance drags the right leg (>10 cm) - the discriminator is real",
      move_cd > 0.10, "max %.4f m" % move_cd)

# --------------------------------------------------------------- phase 3
print("\n=== 3. an open pipe ===", flush=True)
ok("new_scene", {"confirm": True})
pipe = py(LIB + '''
m = cmds.polyCylinder(name="pipe", radius=0.3, height=2.0, subdivisionsY=6, ch=False)[0]
cmds.delete(m + ".f[120:121]")
cmds.xform(m, ws=True, t=[0, 1, 0]); cmds.makeIdentity(m, apply=True, t=1, r=1, s=1)
cmds.ls(m, long=True)[0]
''', "pipe")
skel = ok("create_skeleton", {"chain": [[0, 0, 0], [0, 1, 0], [0, 2, 0]], "chain_prefix": "pipe"})
res = ok("bind_skin", {"mesh": pipe, "root": skel["root"], "method": "geodesicVoxel"})
check("3. open pipe: geodesicVoxel binds, every joint owns vertices, unweighted 0",
      res["unweighted_vertices"] == 0 and all(p["vertices"] > 0 for p in res["per_joint"]),
      json.dumps({p["joint"].split("|")[-1]: p["vertices"] for p in res["per_joint"]}))

# --------------------------------------------------------------- phase 4
print("\n=== 4. a flat sheet ===", flush=True)
ok("new_scene", {"confirm": True})
sheet = py(LIB + "\ncmds.ls(cmds.polyPlane(name='sheet', width=2, height=2, subdivisionsX=10, subdivisionsY=10, ch=False)[0], long=True)[0]", "sheet")
skel = ok("create_skeleton", {"chain": [[-1, 0, 0], [0, 0, 0], [1, 0, 0]], "chain_prefix": "sheet"})
for method in ("geodesicVoxel", "heatMap"):
    r = raw("bind_skin", {"mesh": sheet, "root": skel["root"], "method": method}, timeout_s=60)
    was_refused, detail = refused(r)
    check("4a. %s on a flat sheet is refused with 'flat'" % method, was_refused and "flat" in detail, detail)
left = py("cmds.ls(type=('skinCluster', 'geomBind'))", "left")
check("4b. nothing was bound: no skinCluster, no geomBind node", left == [], json.dumps(left))
res = ok("bind_skin", {"mesh": sheet, "root": skel["root"], "method": "closestDistance"})
check("4c. closestDistance still binds the sheet", res["unweighted_vertices"] == 0, json.dumps(res["warnings"]))

# --------------------------------------------------------------- phase 5
print("\n=== 5. heatMap on a closed tube, over the wire ===", flush=True)
ok("new_scene", {"confirm": True})
tube = py(LIB + '''
m = cmds.polyCylinder(name="tube", radius=0.3, height=2.0, subdivisionsY=6, ch=False)[0]
cmds.xform(m, ws=True, t=[0, 1, 0]); cmds.makeIdentity(m, apply=True, t=1, r=1, s=1)
cmds.ls(m, long=True)[0]
''', "tube")
skel = ok("create_skeleton", {"chain": [[0, 0, 0], [0, 1, 0], [0, 2, 0]], "chain_prefix": "tube"})
res = ok("bind_skin", {"mesh": tube, "root": skel["root"], "method": "heatMap"}, timeout_s=120)
check("5. heatMap binds a closed tube: unweighted 0, the two bone joints own vertices",
      res["unweighted_vertices"] == 0 and sum(1 for p in res["per_joint"] if p["vertices"] > 0) >= 2,
      json.dumps({p["joint"].split("|")[-1]: p["vertices"] for p in res["per_joint"]}))

# --------------------------------------------------------------- phase 6
print("\n=== 6. export the geodesic legs ===", flush=True)
mesh, root, joints = build_legs()
res = ok("bind_skin", {"mesh": mesh, "root": root, "method": "geodesicVoxel"})
path = os.path.join(OUT, "legs_geodesic.fbx").replace("\\", "/")
exp = ok("export_fbx", {"path": path, "metres_per_unit": 1.0, "include_skins": True})
skin = exp.get("skin") or {}
check("6. export_fbx(include_skins): 0 unweighted file vertices, max influences <= 4",
      skin.get("unweighted_file_vertices") == 0 and (skin.get("max_influences") or 99) <= 4,
      json.dumps(skin))

# --------------------------------------------------------------- phase 7
print("\n=== 7. one undo removes the bind and its geomBind node ===", flush=True)
mesh, root, joints = build_legs()
ok("bind_skin", {"mesh": mesh, "root": root, "method": "geodesicVoxel"})
res = ok("undo", {"steps": 1})
left = py("cmds.ls(type=('skinCluster', 'geomBind'))", "left")
check("7. undo(steps=1) after geodesic bind_skin: undone 1, no skinCluster, no geomBind",
      res["undone"] == 1 and left == [], json.dumps({"undone": res["undone"], "left": left}))

# --------------------------------------------------------------- summary
passed = sum(1 for _, r, _ in RESULTS if r)
print("\n%d / %d passed" % (passed, len(RESULTS)))
with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as fh:
    json.dump([{"check": label, "ok": r, "detail": d} for label, r, d in RESULTS], fh, indent=1)
raise SystemExit(0 if passed == len(RESULTS) else 1)
