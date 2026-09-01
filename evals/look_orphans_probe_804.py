"""#804 PROBE - measure before designing (the #796 rule).

The ticket rests on four Maya claims. Record each verbatim:
  1. connectAttr(new.outColor, mat.baseColor, force=True) leaves the OLD file
     node (and its place2dTexture) in the scene, disconnected from the shader
     but still wired to Maya's defaultTextureList1 / defaultRenderUtilityList1.
     Which listConnections forms find the old source before, and the orphan
     after? Does deleting the old file node take its place2dTexture?
  2. setAttr on a shader plug a file node feeds raises; what about a CHILD
     plug (baseColorR) when the compound is fed, and the compound when only a
     child is fed? What does getAttr(lock=True) say for each?
  3. Deleting an aiSkyDomeLight's shape and transform leaves the ramp feeding
     its .color in the scene; same for an hdri file node. What does
     listConnections(shape + ".color", source=True) answer before the delete,
     and what real outputs does the ramp have after?
  4. listConnections(None, ...) - which exception type/message.
  5. Bonus: a normal slot behind a reverse: connectAttr(file.outColor,
     mat.normalCamera, force=True) is ACCEPTED (both float3)?

Run:  MAYA_MCP_PORT=9878 MAYA_MCP_EXPECT_PID=<pid> python evals/look_orphans_probe_804.py
Refuses 9877 (calls new_scene).
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
from live_call import call  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
    print("refusing 9877 (the user's Maya): this probe calls new_scene",
          file=sys.stderr)
    raise SystemExit(2)

CODE = r'''
import json
import maya.cmds as cmds
out = {}

def rec(label, fn):
    try:
        out[label] = {"repr": repr(fn())}
    except Exception as e:  # noqa: BLE001 - the measurement includes failures
        out[label] = {"raised": "%s: %s" % (type(e).__name__, e)}

def lc(*a, **k):
    return cmds.listConnections(*a, **k) or []

# ---- 1. re-texture a slot
cmds.file(new=True, force=True)
mat = cmds.shadingNode("standardSurface", asShader=True, name="kit")
sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="kitSG")
cmds.connectAttr(mat + ".outColor", sg + ".surfaceShader", force=True)
f1 = cmds.shadingNode("file", asTexture=True, name="kit_color_tex")
p1 = cmds.shadingNode("place2dTexture", asUtility=True, name="kit_color_p2d")
cmds.connectAttr(p1 + ".outUV", f1 + ".uvCoord", force=True)
cmds.connectAttr(p1 + ".outUvFilterSize", f1 + ".uvFilterSize", force=True)
cmds.connectAttr(f1 + ".outColor", mat + ".baseColor", force=True)
out["1a_src_plugs_before"] = lc(mat + ".baseColor", source=True, destination=False, plugs=True)
out["1a_src_nodes_before"] = lc(mat + ".baseColor", source=True, destination=False)
out["1b_f1_outputs_before"] = lc(f1, source=False, destination=True)
out["1b_f1_outputs_before_plugs"] = lc(f1, source=False, destination=True, plugs=True)
out["1b_p1_outputs_before"] = lc(p1, source=False, destination=True)
f2 = cmds.shadingNode("file", asTexture=True, name="kit_color_tex2")
p2 = cmds.shadingNode("place2dTexture", asUtility=True, name="kit_color_p2d2")
cmds.connectAttr(p2 + ".outUV", f2 + ".uvCoord", force=True)
cmds.connectAttr(f2 + ".outColor", mat + ".baseColor", force=True)
out["1c_src_plugs_after_force"] = lc(mat + ".baseColor", source=True, destination=False, plugs=True)
out["1c_f1_exists_after"] = cmds.objExists(f1)
out["1c_f1_outputs_after"] = lc(f1, source=False, destination=True)
out["1c_f1_outputs_after_plugs"] = lc(f1, source=False, destination=True, plugs=True)
out["1c_f1_inputs_after"] = lc(f1, source=True, destination=False)
out["1c_p1_outputs_after"] = lc(p1, source=False, destination=True)
out["1c_scene_files"] = cmds.ls(type="file")
out["1c_scene_p2d"] = cmds.ls(type="place2dTexture")
cmds.delete(f1)
out["1d_after_delete_f1_p2d_exists"] = cmds.objExists(p1)
out["1d_p1_outputs_after_f1_deleted"] = lc(p1, source=False, destination=True)
out["1d_p1_outputs_plugs"] = lc(p1, source=False, destination=True, plugs=True)
# a reverse between file and slot (invert=True maps)
inv = cmds.shadingNode("reverse", asUtility=True, name="kit_rough_inv")
f3 = cmds.shadingNode("file", asTexture=True, name="kit_rough_tex")
cmds.connectAttr(f3 + ".outColorR", inv + ".inputX", force=True)
cmds.connectAttr(inv + ".outputX", mat + ".specularRoughness", force=True)
out["1e_rough_src_plugs"] = lc(mat + ".specularRoughness", source=True, destination=False, plugs=True)
out["1e_inv_inputs"] = lc(inv, source=True, destination=False)
out["1e_inv_outputs"] = lc(inv, source=False, destination=True)

# ---- 2. setAttr against a fed plug, compound vs child
rec("2a_setAttr_compound_fed", lambda: cmds.setAttr(mat + ".baseColor", 1, 0, 0, type="double3"))
rec("2b_setAttr_child_of_fed_compound", lambda: cmds.setAttr(mat + ".baseColorR", 1.0))
rec("2c_getAttr_lock_compound", lambda: cmds.getAttr(mat + ".baseColor", lock=True))
rec("2d_getAttr_lock_child", lambda: cmds.getAttr(mat + ".baseColorR", lock=True))
rec("2e_setAttr_scalar_fed_via_reverse", lambda: cmds.setAttr(mat + ".specularRoughness", 0.3))
# child fed only
cmds.connectAttr(f2 + ".outColorR", mat + ".emissionColorR", force=True)
rec("2f_setAttr_compound_with_child_fed", lambda: cmds.setAttr(mat + ".emissionColor", 1, 1, 1, type="double3"))
rec("2g_setAttr_sibling_of_fed_child", lambda: cmds.setAttr(mat + ".emissionColorG", 0.5))
out["2h_emission_src_plugs_compound_query"] = lc(mat + ".emissionColor", source=True, destination=False, plugs=True)
out["2i_emission_src_plugs_child_query"] = lc(mat + ".emissionColorR", source=True, destination=False, plugs=True)
# an unfed plug: setAttr works
rec("2j_setAttr_unfed", lambda: cmds.setAttr(mat + ".metalness", 0.5))

# ---- 3. dome + ramp
cmds.file(new=True, force=True)
if not cmds.pluginInfo("mtoa", query=True, loaded=True):
    cmds.loadPlugin("mtoa")
shape = cmds.shadingNode("aiSkyDomeLight", asLight=True, name="mcpLight_domeShape")
if cmds.nodeType(shape) != "aiSkyDomeLight":
    shape = cmds.listRelatives(shape, shapes=True, fullPath=True)[0]
transform = cmds.listRelatives(shape, parent=True, fullPath=True)[0]
ramp = cmds.shadingNode("ramp", asTexture=True, name="mcpLight_domeRamp")
cmds.connectAttr(ramp + ".outColor", shape + ".color", force=True)
out["3a_color_src_before"] = lc(shape + ".color", source=True, destination=False)
out["3a_color_src_before_plugs"] = lc(shape + ".color", source=True, destination=False, plugs=True)
out["3a_ramp_outputs_before"] = lc(ramp, source=False, destination=True)
out["3a_ramp_inputs"] = lc(ramp, source=True, destination=False)
cmds.delete(shape)
out["3b_after_delete_shape_transform_exists"] = cmds.objExists(transform)
out["3b_after_delete_shape_ramp_exists"] = cmds.objExists(ramp)
if cmds.objExists(transform):
    cmds.delete(transform)
out["3c_after_delete_transform_ramp_exists"] = cmds.objExists(ramp)
out["3c_ramp_outputs_after"] = lc(ramp, source=False, destination=True)
out["3c_ramp_outputs_after_plugs"] = lc(ramp, source=False, destination=True, plugs=True)
out["3c_scene_ramps"] = cmds.ls(type="ramp")
# hdri form: file -> shape.color, plus the place2d a file usually carries
shape2 = cmds.shadingNode("aiSkyDomeLight", asLight=True, name="mcpLight_domeShape")
if cmds.nodeType(shape2) != "aiSkyDomeLight":
    shape2 = cmds.listRelatives(shape2, shapes=True, fullPath=True)[0]
t2 = cmds.listRelatives(shape2, parent=True, fullPath=True)[0]
tex = cmds.shadingNode("file", asTexture=True, name="mcpLight_domeTex")
cmds.connectAttr(tex + ".outColor", shape2 + ".color", force=True)
out["3d_hdri_color_src"] = lc(shape2 + ".color", source=True, destination=False)
out["3d_tex_inputs"] = lc(tex, source=True, destination=False)
cmds.delete(t2)
out["3e_after_delete_transform_tex_exists"] = cmds.objExists(tex)
out["3e_tex_outputs_after"] = lc(tex, source=False, destination=True)
# what does a light shape created by shadingNode(asLight=True) connect to, by default?
shape3 = cmds.shadingNode("aiSkyDomeLight", asLight=True, name="probe_domeShape")
if cmds.nodeType(shape3) != "aiSkyDomeLight":
    shape3 = cmds.listRelatives(shape3, shapes=True, fullPath=True)[0]
out["3f_fresh_dome_outputs"] = lc(shape3, source=False, destination=True)
out["3f_fresh_dome_inputs"] = lc(shape3, source=True, destination=False)

# ---- 4. listConnections(None)
rec("4a_listConnections_None", lambda: cmds.listConnections(None, source=True, destination=False))
rec("4b_listConnections_missing_node", lambda: cmds.listConnections("no_such_node", source=True, destination=False))

# ---- 5. a normal slot fed through a reverse; outColor into normalCamera accepted?
cmds.file(new=True, force=True)
m = cmds.shadingNode("standardSurface", asShader=True, name="skin_mat")
noise = cmds.shadingNode("noise", asTexture=True, name="mcpTex_noise")
bump = cmds.shadingNode("bump2d", asUtility=True, name="mcpTex_bump")
inv = cmds.shadingNode("reverse", asUtility=True, name="mcpTex_inv")
cmds.connectAttr(noise + ".outColorR", bump + ".bumpValue", force=True)
cmds.connectAttr(bump + ".outNormal", inv + ".input", force=True)
cmds.connectAttr(inv + ".output", m + ".normalCamera", force=True)
out["5a_normal_direct_sources"] = lc(m + ".normalCamera", source=True, destination=False)
fx = cmds.shadingNode("file", asTexture=True, name="baked")
rec("5b_connect_file_outColor_to_normalCamera", lambda: cmds.connectAttr(fx + ".outColor", m + ".normalCamera", force=True))
out["5b_normal_sources_after"] = lc(m + ".normalCamera", source=True, destination=False, plugs=True)
out["5c_inv_outputs_after_force"] = lc(inv, source=False, destination=True)

out["maya_version"] = cmds.about(version=True)
json.dumps(out)
'''


def main() -> int:
    frame = call("execute_python", {"code": CODE, "timeout_s": 120},
                 timeout_s=150.0, port=PORT)
    if frame.get("status") != "ok":
        print(json.dumps(frame, indent=1)); return 1
    res = frame["result"]
    if res.get("traceback"):
        print(res["traceback"]); return 1
    data = json.loads(eval(res["result_repr"]))
    out_dir = os.path.join(_HERE, "look_orphans_probe_804")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "readings.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    for k in sorted(data):
        print("%-42s %s" % (k, json.dumps(data[k])))
    print("written", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
