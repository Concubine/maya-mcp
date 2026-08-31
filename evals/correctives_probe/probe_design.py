"""#771 design probes — measure the unknowns that decide the correctives design.

Runs against the DISPOSABLE agent Maya (default port 9878; refuses 9877).
Mutates the answering Maya's scene freely (new_scene first).

Questions, each numbered section prints a JSON verdict:
  P1  poseInterpolator mechanics: what the command creates, how poses are
      added, what output[] reads at rest / trigger / half-angle.
  P2  wiring output -> blendShape weight alias: does the weight follow, what
      do setAttr / setKeyframe on the driven plug actually do (exact errors).
  P3  deltaMush: where cmds.deltaMush lands in the chain, measured edge-ratio
      effect at a bent elbow, and whether creating it while POSED differs
      from creating it at rest.
  P4  export: (a) does a live deltaMush change exported vertex bytes at bind
      pose (drop-proof); (b) does FBXExportBakeComplexAnimation bake a
      poseInterpolator-DRIVEN DeformPercent into curves (presence in bytes +
      reimport-and-evaluate values).

Usage (PowerShell):
  $env:MAYA_MCP_PORT='9878'; $env:MAYA_MCP_EXPECT_PID='<pid>'
  python evals/correctives_probe/probe_design.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
OUT_DIR = os.path.abspath(os.path.dirname(__file__))


def die(msg):
    print("PROBE ABORT: %s" % msg)
    raise SystemExit(1)


def ok(frame, what):
    if frame.get("status") != "ok":
        die("%s failed: %s" % (what, json.dumps(frame.get("error"))[:2000]))
    return frame.get("result")


def py(code, what, timeout_s=120):
    frame = call("execute_python", {"code": code}, timeout_s=timeout_s)
    result = ok(frame, what)
    if result.get("traceback"):
        die("%s raised:\n%s" % (what, result["traceback"]))
    return structured_result(result, what)


def section(name, payload):
    print("\n=== %s ===" % name)
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def main():
    if PORT == 9877:
        die("refusing to run against the user's Maya on 9877")

    ok(call("new_scene", {"confirm": True}), "new_scene")

    # ---- Fixture: 3-joint chain + skinned cylinder along +X -----------------
    skel = ok(call("create_skeleton", {
        "chain": [[0.0, 0.0, 0.0], [0.3, 0.0, 0.0], [0.6, 0.0, 0.0]],
        "chain_prefix": "arm",
    }), "create_skeleton")
    joints = [j["name"] for j in skel["joints"]]

    fixture = py(r"""
import json
# Cylinder along +X spanning the chain: polyCylinder builds along Y, rotate.
mesh, node = cmds.polyCylinder(name='armMesh', radius=0.05, height=0.6,
                               subdivisionsAxis=8, subdivisionsHeight=24,
                               subdivisionsCaps=1)
cmds.setAttr(mesh + '.rotateZ', -90)
cmds.setAttr(mesh + '.translateX', 0.3)
cmds.makeIdentity(mesh, apply=True, translate=True, rotate=True, scale=True)
cmds.delete(mesh, constructionHistory=True)
json.dumps({'mesh': cmds.ls(mesh, long=True)[0],
            'verts': cmds.polyEvaluate(mesh, vertex=True)})
""", "fixture mesh")
    fixture = json.loads(fixture)
    mesh = fixture["mesh"]

    ok(call("bind_skin", {"mesh": mesh, "root": joints[0]}), "bind_skin")

    # ---- P1: poseInterpolator mechanics ------------------------------------
    p1 = py(r"""
import json
rep = {}
elbow = %r
# What does the command create?
before = set(cmds.ls(long=True))
created = cmds.poseInterpolator(elbow, name='elbow_poseInterp')
after = set(cmds.ls(long=True))
rep['command_returned'] = created
rep['nodes_created'] = sorted(after - before)
shape = cmds.ls(cmds.listRelatives(created[0], shapes=True, fullPath=True)
                if isinstance(created, list) else [], long=True)
if not shape:
    # maybe the command returned the shape itself
    shape = created if isinstance(created, list) else [created]
interp = shape[0]
rep['interp'] = interp
rep['interp_type'] = cmds.nodeType(interp)
# Driver wiring
rep['driver_connections'] = cmds.listConnections(interp + '.driver[0].driverMatrix',
                                                 source=True, plugs=True) or []
# What MEL helpers exist
helpers = {}
for h in ('poseInterpolatorAddPose', 'poseInterpolatorAddShapePose',
          'poseInterpolatorSetPoseKernalFalloff', 'poseInterpolatorNeutralPose',
          'poseInterpolatorDeletePose', 'poseInterpolatorPoseNames'):
    helpers[h] = mel.eval('whatIs "%%s"' %% h)
rep['mel_helpers'] = helpers
# Command query surface
try:
    rep['q_poseNames_initial'] = cmds.poseInterpolator(interp, q=True, poseNames=True)
except Exception as e:
    rep['q_poseNames_initial'] = 'ERR:' + str(e)
json.dumps(rep)
""" % joints[1], "P1 anatomy")
    p1 = json.loads(p1)
    section("P1 poseInterpolator anatomy", p1)

    interp = p1["interp"]

    p1b = py(r"""
import json
rep = {}
elbow = %r
interp = %r
# Neutral pose(s) at rest (rotate is 0,0,0 now)
for nname, ntype in (('neutral', 'neutral'), ('neutralSwing', 'neutralswing'),
                     ('neutralTwist', 'neutraltwist')):
    try:
        idx = mel.eval('poseInterpolatorAddPose("%%s", "%%s")' %% (interp, nname))
        cmds.poseInterpolator(interp, edit=True, updatePose=nname)
        rep['add_' + nname] = idx
    except Exception as e:
        rep['add_' + nname] = 'ERR:' + str(e)
# Trigger pose at elbow rotate (0,0,-90)
cmds.setAttr(elbow + '.rotate', 0, 0, -90)
try:
    idx = mel.eval('poseInterpolatorAddPose("%%s", "%%s")' %% (interp, 'elbow_bent'))
    rep['add_elbow_bent'] = idx
except Exception as e:
    rep['add_elbow_bent'] = 'ERR:' + str(e)
rep['poseNames'] = cmds.poseInterpolator(interp, q=True, poseNames=True)
# output[] at trigger
def outputs():
    idxs = cmds.getAttr(interp + '.output', multiIndices=True) or []
    return {i: round(cmds.getAttr('%%s.output[%%d]' %% (interp, i)), 6) for i in idxs}
rep['outputs_at_90'] = outputs()
cmds.setAttr(elbow + '.rotate', 0, 0, 0)
rep['outputs_at_rest'] = outputs()
cmds.setAttr(elbow + '.rotate', 0, 0, -45)
rep['outputs_at_45'] = outputs()
cmds.setAttr(elbow + '.rotate', 0, 0, -60)
rep['outputs_at_60'] = outputs()
cmds.setAttr(elbow + '.rotate', 0, 0, 0)
# falloff attrs per pose
rep['pose_attrs_sample'] = {}
for a in ('poseName', 'poseType', 'poseFalloff', 'poseRotationFalloff'):
    try:
        rep['pose_attrs_sample'][a] = cmds.getAttr('%%s.pose[3].%%s' %% (interp, a))
    except Exception as e:
        rep['pose_attrs_sample'][a] = 'ERR:' + str(e)
rep['interpolation'] = cmds.getAttr(interp + '.interpolation')
json.dumps(rep)
""" % (joints[1], interp), "P1b poses")
    p1b = json.loads(p1b)
    section("P1b pose add + output evaluation", p1b)

    # ---- P2: drive a blendShape weight -------------------------------------
    # Author a target: duplicate, bulge a band of verts near the elbow.
    tgt = py(r"""
import json
mesh = %r
dup = cmds.duplicate(mesh, name='armMesh_bulge')[0]
# move a band of verts outward (bulge) around x=0.3
n = cmds.polyEvaluate(dup, vertex=True)
moved = 0
for i in range(n):
    p = cmds.pointPosition('%%s.vtx[%%d]' %% (dup, i), world=True)
    if 0.2 < p[0] < 0.4:
        cmds.move(0, p[1] * 0.5, p[2] * 0.5, '%%s.vtx[%%d]' %% (dup, i),
                  relative=True, worldSpace=True)
        moved += 1
json.dumps({'dup': cmds.ls(dup, long=True)[0], 'moved': moved})
""" % mesh, "P2 target sculpt")
    tgt = json.loads(tgt)

    bs = ok(call("create_blendshape", {
        "mesh": mesh,
        "targets": [{"name": "elbow_fix", "target_mesh": tgt["dup"]}],
    }), "create_blendshape")

    p2 = py(r"""
import json
rep = {}
elbow = %r
interp = %r
bs_node = %r
# find which output index is the elbow_bent pose
names = cmds.poseInterpolator(interp, q=True, poseNames=True)
idxs = cmds.getAttr(interp + '.output', multiIndices=True) or []
rep['poseNames'] = names
rep['output_indices'] = idxs
# pose index by name
pose_idx = None
for i in (cmds.getAttr(interp + '.pose', multiIndices=True) or []):
    if cmds.getAttr('%%s.pose[%%d].poseName' %% (interp, i)) == 'elbow_bent':
        pose_idx = i
rep['elbow_bent_pose_index'] = pose_idx
cmds.connectAttr('%%s.output[%%d]' %% (interp, pose_idx), bs_node + '.elbow_fix')
def w():
    return round(cmds.getAttr(bs_node + '.elbow_fix'), 6)
rep['weight_at_rest'] = w()
cmds.setAttr(elbow + '.rotate', 0, 0, -90)
rep['weight_at_90'] = w()
cmds.setAttr(elbow + '.rotate', 0, 0, -45)
rep['weight_at_45'] = w()
cmds.setAttr(elbow + '.rotate', 0, 0, 0)
# setAttr on the driven plug
try:
    cmds.setAttr(bs_node + '.elbow_fix', 0.5)
    rep['setAttr_on_driven'] = 'SUCCEEDED (value %%r)' %% w()
except Exception as e:
    rep['setAttr_on_driven'] = 'ERR: %%s' %% e
# setKeyframe on the driven plug
try:
    r = cmds.setKeyframe(bs_node, attribute='elbow_fix', t=1, v=0.0)
    rep['setKeyframe_on_driven'] = 'returned %%r' %% r
    rep['driven_conn_after_key'] = cmds.listConnections(
        bs_node + '.elbow_fix', source=True, plugs=True) or []
except Exception as e:
    rep['setKeyframe_on_driven'] = 'ERR: %%s' %% e
json.dumps(rep)
""" % (joints[1], interp, bs["blend_shape"]), "P2 drive weight")
    p2 = json.loads(p2)
    section("P2 driven weight behavior", p2)

    # ---- P3: deltaMush ------------------------------------------------------
    p3 = py(r"""
import json, maya.api.OpenMaya as om
rep = {}
mesh = %r
elbow = %r

def worst_edge_ratio(bind_lengths=None):
    sel = om.MSelectionList(); sel.add(mesh)
    dag = sel.getDagPath(0)
    it = om.MItMeshEdge(dag)
    lengths = []
    while not it.isDone():
        p0 = it.point(0, om.MSpace.kWorld); p1 = it.point(1, om.MSpace.kWorld)
        lengths.append((p0 - p1).length())
        it.next()
    if bind_lengths is None:
        return lengths, None
    worst = 0.0
    for a, b in zip(lengths, bind_lengths):
        if b > 1e-9:
            worst = max(worst, a / b)
    return lengths, worst

cmds.setAttr(elbow + '.rotate', 0, 0, 0)
bind_lengths, _ = worst_edge_ratio()
cmds.setAttr(elbow + '.rotate', 0, 0, -110)
_, before = worst_edge_ratio(bind_lengths)
rep['worst_ratio_posed_no_mush'] = round(before, 4)

# create deltaMush WHILE POSED (capture positions after)
dm = cmds.deltaMush(mesh, smoothingIterations=10, smoothingStep=0.5)[0]
rep['deltaMush_node'] = dm
hist = cmds.listHistory(mesh, pruneDagObjects=True)
rep['history_chain'] = [n for n in hist
                       if cmds.nodeType(n) in ('blendShape', 'skinCluster', 'deltaMush')]
_, posed_create = worst_edge_ratio(bind_lengths)
rep['worst_ratio_mush_created_posed'] = round(posed_create, 4)
import maya.cmds as mc
posed_pts = [cmds.pointPosition('%%s.vtx[%%d]' %% (mesh, i), world=True)
             for i in range(0, cmds.polyEvaluate(mesh, vertex=True), 7)]
cmds.delete(dm)

# create deltaMush AT REST, then pose
cmds.setAttr(elbow + '.rotate', 0, 0, 0)
dm2 = cmds.deltaMush(mesh, smoothingIterations=10, smoothingStep=0.5)[0]
cmds.setAttr(elbow + '.rotate', 0, 0, -110)
_, rest_create = worst_edge_ratio(bind_lengths)
rep['worst_ratio_mush_created_rest'] = round(rest_create, 4)
rest_pts = [cmds.pointPosition('%%s.vtx[%%d]' %% (mesh, i), world=True)
            for i in range(0, cmds.polyEvaluate(mesh, vertex=True), 7)]
maxdiff = max(sum((a - b) ** 2 for a, b in zip(p, q)) ** 0.5
              for p, q in zip(posed_pts, rest_pts))
rep['posed_vs_rest_creation_max_vertex_diff'] = round(maxdiff, 6)
# does the mush at rest move anything at rest? (identity-at-rest check)
cmds.setAttr(elbow + '.rotate', 0, 0, 0)
_, at_rest = worst_edge_ratio(bind_lengths)
rep['worst_ratio_at_rest_with_mush'] = round(at_rest, 4)
rep['mush_node_kept'] = dm2
json.dumps(rep)
""" % (mesh, joints[1]), "P3 deltaMush", timeout_s=180)
    p3 = json.loads(p3)
    section("P3 deltaMush placement + effect", p3)

    # ---- P4a: deltaMush export A/B ------------------------------------------
    path_a = os.path.join(OUT_DIR, "probe_mush.fbx")
    path_b = os.path.join(OUT_DIR, "probe_nomush.fbx")
    py(r"""
cmds.setAttr(%r + '.rotate', 0, 0, 0)
'ok'
""" % joints[1], "reset pose for export")
    ok(call("export_fbx", {"path": path_a, "metres_per_unit": 1.0,
                           "include_skins": True, "nodes": [mesh, joints[0]]},
            timeout_s=300), "export with mush")
    py("cmds.delete(%r)\n'ok'" % p3["mush_node_kept"], "delete mush")
    ok(call("export_fbx", {"path": path_b, "metres_per_unit": 1.0,
                           "include_skins": True, "nodes": [mesh, joints[0]]},
            timeout_s=300), "export without mush")

    from maya_plugin.handlers import fbxbytes  # noqa: E402
    fa = fbxbytes.read_fbx(path_a)
    fb = fbxbytes.read_fbx(path_b)
    va = [round(c, 6) for m in fa.meshes for c in m]
    vb = [round(c, 6) for m in fb.meshes for c in m]
    section("P4a deltaMush export A/B", {
        "vertex_floats_with_mush": len(va), "vertex_floats_without": len(vb),
        "identical_vertices": va == vb,
        "max_component_diff": max((abs(a - b) for a, b in zip(va, vb)),
                                  default=None),
        "bytes_a": os.path.getsize(path_a), "bytes_b": os.path.getsize(path_b),
    })

    # ---- P4b: driven DeformPercent bake -------------------------------------
    # Key the elbow over frames 1..24 (raw keys; probe measures Maya's
    # exporter, not the clip contract), then export with animation.
    py(r"""
elbow = %r
for f, rz in ((1, 0.0), (12, -90.0), (24, 0.0)):
    cmds.setKeyframe(elbow, attribute='rotateZ', t=f, v=rz)
    cmds.setKeyframe(elbow, attribute='rotateX', t=f, v=0.0)
    cmds.setKeyframe(elbow, attribute='rotateY', t=f, v=0.0)
cmds.playbackOptions(minTime=1, maxTime=24)
'ok'
""" % joints[1], "key elbow")
    path_c = os.path.join(OUT_DIR, "probe_driven.fbx")
    frame = call("export_fbx", {"path": path_c, "metres_per_unit": 1.0,
                                "include_skins": True, "include_animation": True,
                                "nodes": [mesh, joints[0]]}, timeout_s=300)
    if frame.get("status") != "ok":
        section("P4b export refused (fallback to raw FBXExport)",
                {"error": frame.get("error")})
        py(r"""
import maya.mel as m
cmds.select(%r, %r, replace=True)
m.eval('FBXResetExport')
m.eval('FBXExportBakeComplexAnimation -v true')
m.eval('FBXExportBakeComplexStart -v 1')
m.eval('FBXExportBakeComplexEnd -v 24')
m.eval('FBXExportBakeResampleAnimation -v true')
m.eval('FBXExport -f "%%s" -s' %% %r.replace(chr(92), '/'))
'ok'
""" % (mesh, joints[0], path_c), "raw FBXExport")
    fc = fbxbytes.read_fbx(path_c)
    anim = fbxbytes.anim_facts(fc)
    deform = [t for t in anim["targets"] if t["property"] == "DeformPercent"]
    section("P4b driven DeformPercent in bytes", {
        "takes": anim["takes"], "curve_nodes": anim["curve_nodes"],
        "deform_percent_targets": deform,
        "all_targets": anim["targets"],
    })

    # Reimport and evaluate values per frame.
    reimport = py(r"""
import json
cmds.file(new=True, force=True)
cmds.file(%r, i=True, namespace='probe')
bs = cmds.ls('probe:*', type='blendShape')
rep = {'blendshape_nodes': bs}
if bs:
    node = bs[0]
    aliases = cmds.listAttr(node + '.w', multi=True) or []
    rep['aliases'] = aliases
    vals = {}
    for f in (1, 6, 12, 18, 24):
        cmds.currentTime(f)
        vals[f] = {a: round(cmds.getAttr('%%s.%%s' %% (node, a)), 4)
                   for a in aliases}
    rep['weights_by_frame'] = vals
json.dumps(rep)
""" % path_c, "P4b reimport evaluate", timeout_s=180)
    section("P4b reimported weight evaluation", json.loads(reimport))

    print("\nPROBE COMPLETE")


if __name__ == "__main__":
    main()
