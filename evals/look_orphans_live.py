"""#804 LIVE GATE: the look handlers clean up, or refuse, what an earlier call
built - measured in the scene graph and on disk, over the wire.

  1. assign_pbr re-texturing a slot leaves ONE file node and ONE
     place2dTexture for it, named as the first call named them, wired to the
     new image; the old ones are gone. Controls: a second slot keeps its own
     nodes; a file node another slot still uses survives, and is named.
  2. assign_pbr with a param aimed at a slot an EARLIER call mapped is
     refused, naming the param and the map; no node is built and the mesh is
     not moved. Control: a param on a free slot lands.
  3. assign_material reusing a mapped shader is refused BEFORE the mesh is
     moved - on the compound, and on a compound with one fed child. Control:
     a param on a free plug lands and the mesh moves.
  4. setup_lighting(environment) twice leaves ONE ramp; the replaced ramp is
     named in `removed`; an hdri dome's file node is swept the same way.
     Control: a ramp something else still uses survives, and is named.
  5. bake_textures on a normal slot fed THROUGH a reverse is refused at plan
     time - no PNG on disk, no checkpoint spent, the wiring untouched.
     Control: the same slot with the bump2d feeding it directly bakes.

DESTRUCTIVE: calls maya_new_scene. Runs against the disposable agent Maya on
9878 and REFUSES 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1. The live Maya must
import THIS working tree (launch it with the repo as its working directory).
Phase 0 asserts exactly that.

Run:  MAYA_MCP_PORT=9878 MAYA_MCP_EXPECT_PID=<pid> python evals/look_orphans_live.py
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

OUT = os.path.join(_HERE, "look_orphans_live")
os.makedirs(OUT, exist_ok=True)
RESULTS = []


def check(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    print("%-4s %-70s %s" % ("PASS" if ok else "FAIL", label, detail),
          flush=True)


def send(command, params, timeout_s=300.0):
    return call(command, params, timeout_s=timeout_s, port=PORT)


def ok(command, params, timeout_s=300.0):
    response = send(command, params, timeout_s)
    if response.get("status") != "ok":
        raise SystemExit("%s failed: %s" % (command, response.get("error")))
    return response.get("result") or {}


def refusal(command, params, timeout_s=300.0):
    response = send(command, params, timeout_s)
    if response.get("status") == "ok":
        return None
    return response.get("error") or {}


def py(code, what, timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s),
                             what)


def png(name):
    """A tiny real PNG on disk - assign_pbr checks the path exists; a file
    node reads whatever it finds."""
    import struct
    import zlib
    path = os.path.join(OUT, name)
    raw = b"".join(b"\x00" + bytes([r, 0, 255 - r]) * 4 for r in (10, 200, 90, 40))
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
                 + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path.replace("\\", "/")


A, B, MASK, NORMAL = png("a.png"), png("b.png"), png("mask.png"), png("n.png")
HDR = png("sky.png")

STATE = r'''
import maya.cmds as cmds
def sg_of(shape):
    return sorted(cmds.listSets(object=shape, type=1) or [])
{"files": sorted(cmds.ls(type="file")), "p2d": sorted(cmds.ls(type="place2dTexture")),
 "reverse": sorted(cmds.ls(type="reverse")), "bump": sorted(cmds.ls(type="bump2d")),
 "ramps": sorted(cmds.ls(type="ramp")),
 "torso_sg": sg_of("|torso|torsoShape") if cmds.objExists("|torso|torsoShape") else None,
 "arm_sg": sg_of("|arm|armShape") if cmds.objExists("|arm|armShape") else None,
 "arm2_sg": sg_of("|arm2|arm2Shape") if cmds.objExists("|arm2|arm2Shape") else None,
 "baseColor_src": cmds.listConnections("kit.baseColor", s=True, d=False, plugs=True) if cmds.objExists("kit") else None,
 "color_tex_path": cmds.getAttr("kit_color_tex.fileTextureName") if cmds.objExists("kit_color_tex") else None,
 "metalness": cmds.getAttr("kit.metalness") if cmds.objExists("kit") else None,
 "roughness": cmds.getAttr("kit.specularRoughness") if cmds.objExists("kit") else None}
'''


def state():
    return py(STATE, "state")


def fresh_meshes():
    ok("new_scene", {"confirm": True})
    py("""
import maya.cmds as cmds
for n, x in (("torso", 0), ("arm", 3), ("arm2", 6)):
    t = cmds.polyCube(name=n)[0]; cmds.xform(t, ws=True, t=(x, 0, 0))
True
""", "setup")


# --------------------------------------------------------------- phase 0
print("=== 0. who answered, and whose code is it ===", flush=True)
ident = py("import os, maya_plugin\n"
           "{'file': maya_plugin.__file__, 'cwd': os.getcwd()}", "identity")
loaded = os.path.normcase(os.path.abspath(ident["file"]))
expected = os.path.normcase(os.path.join(REPO, "maya_plugin", "__init__.py"))
if loaded != expected:
    print("WRONG CODE: live Maya imports %s, not %s. Relaunch it with the "
          "repo as its working directory." % (loaded, expected), file=sys.stderr)
    raise SystemExit(2)
print("live plugin: %s" % loaded, flush=True)
has = py("from maya_plugin.handlers import orphans\nsorted(orphans.SWEEPABLE_TYPES)", "orphans")
check("0. the orphans module is loaded in the live Maya", "file" in has and "ramp" in has)

# --------------------------------------------------------------- phase 1
print("\n=== 1. re-texturing a slot strands nothing ===", flush=True)
fresh_meshes()
first = ok("assign_pbr", {"mesh": "|torso", "name": "kit", "maps": {"color": A}})
s1 = state()
check("1a. first texture: one file, one p2d, replaced nothing",
      s1["files"] == ["kit_color_tex"] and s1["p2d"] == ["kit_color_p2d"]
      and first["maps"]["color"]["replaced"] == [],
      "files %r p2d %r" % (s1["files"], s1["p2d"]))
second = ok("assign_pbr", {"mesh": "|torso", "name": "kit", "maps": {"color": B}})
s2 = state()
check("1b. re-texture: STILL one file and one p2d, under the same names",
      s2["files"] == ["kit_color_tex"] and s2["p2d"] == ["kit_color_p2d"],
      "files %r p2d %r" % (s2["files"], s2["p2d"]))
check("1c. ... and it is the NEW image feeding baseColor",
      s2["color_tex_path"] == B and s2["baseColor_src"] == ["kit_color_tex.outColor"],
      "path %r src %r" % (s2["color_tex_path"], s2["baseColor_src"]))
check("1d. ... reported: replaced names the old pair, file is kit_color_tex",
      second["maps"]["color"]["replaced"] == ["kit_color_tex", "kit_color_p2d"]
      and second["maps"]["color"]["file"] == "kit_color_tex",
      "replaced %r file %r" % (second["maps"]["color"]["replaced"], second["maps"]["color"]["file"]))
third = ok("assign_pbr", {"mesh": "|torso", "name": "kit",
                          "maps": {"roughness": {"path": MASK, "channel": "g"}}})
s3 = state()
check("1e. CONTROL: a second slot adds its own file, replaces nothing",
      s3["files"] == ["kit_color_tex", "kit_roughness_tex"]
      and third["maps"]["roughness"]["replaced"] == [],
      "files %r" % (s3["files"],))
# shared image, two raw slots -> one file node; re-map one slot -> survives
shared = ok("assign_pbr", {"mesh": "|arm", "name": "kit2",
                           "maps": {"metalness": {"path": MASK, "channel": "r"},
                                    "roughness": {"path": MASK, "channel": "g"}}})
shared_file = shared["maps"]["metalness"]["file"]
remap = ok("assign_pbr", {"mesh": "|arm", "name": "kit2",
                          "maps": {"metalness": {"path": A, "channel": "r"}}})
s4 = state()
check("1f. CONTROL: a file node another slot still uses survives, and is named",
      shared_file in s4["files"] and remap["maps"]["metalness"]["replaced"] == []
      and any(shared_file in w and "still used" in w for w in remap["warnings"]),
      "files %r warnings %r" % (s4["files"], remap["warnings"]))

# --------------------------------------------------------------- phase 2
print("\n=== 2. a param that fights an earlier call's map ===", flush=True)
before = state()
err = refusal("assign_pbr", {"mesh": "|arm2", "name": "kit", "maps": {"normal": NORMAL},
                             "params": {"baseColor": [1, 0, 0]}})
after = state()
check("2a. refused, naming the param and the map",
      err is not None and err.get("type") == "HandlerError"
      and "baseColor" in err.get("message", "") and "kit_color_tex" in err.get("message", ""),
      (err or {}).get("message", "SUCCEEDED")[:120])
check("2b. ... the hint sends the caller to assign_pbr's re-map, not to a rig",
      "assign_pbr" in (err or {}).get("hint", "") and "constraint" not in (err or {}).get("hint", ""),
      (err or {}).get("hint", "")[:120])
check("2c. ... nothing built, arm2 not moved",
      after["files"] == before["files"] and after["bump"] == before["bump"]
      and after["arm2_sg"] == before["arm2_sg"],
      "files %r->%r sg %r->%r" % (before["files"], after["files"], before["arm2_sg"], after["arm2_sg"]))
res = ok("assign_pbr", {"mesh": "|arm2", "name": "kit", "maps": {"normal": NORMAL},
                        "params": {"metalness": 1.0}})
s5 = state()
check("2d. CONTROL: a param on a free slot lands and arm2 wears kit",
      s5["metalness"] == 1.0 and s5["arm2_sg"] == s1["torso_sg"] and res["material"] == "kit",
      "metalness %r sg %r" % (s5["metalness"], s5["arm2_sg"]))

# --------------------------------------------------------------- phase 3
print("\n=== 3. assign_material reuse asks before it moves the mesh ===", flush=True)
fresh_meshes()
ok("assign_pbr", {"mesh": "|torso", "name": "kit", "maps": {"color": A}})
before = state()
err = refusal("assign_material", {"mesh": "|arm", "name": "kit",
                                  "params": {"baseColor": [1, 0, 0]}})
after = state()
check("3a. a mapped compound is refused, naming plug and map",
      err is not None and err.get("type") == "HandlerError"
      and "kit.baseColor" in err.get("message", "") and "kit_color_tex" in err.get("message", ""),
      (err or {}).get("message", "SUCCEEDED")[:120])
check("3b. ... and the mesh was NOT moved",
      after["arm_sg"] == before["arm_sg"], "sg %r->%r" % (before["arm_sg"], after["arm_sg"]))
py("import maya.cmds as cmds\ncmds.connectAttr('kit_color_tex.outColorR', 'kit.emissionColorR', force=True)\nTrue", "wire")
err = refusal("assign_material", {"mesh": "|arm", "name": "kit",
                                  "params": {"emissionColor": [1, 1, 1]}})
check("3c. a compound with ONE fed child is refused, naming the child",
      err is not None and "emissionColorR" in err.get("message", ""),
      (err or {}).get("message", "SUCCEEDED")[:120])
res = ok("assign_material", {"mesh": "|arm", "name": "kit", "params": {"roughness": 0.4}})
s6 = state()
check("3d. CONTROL: a free plug lands and the mesh moves",
      abs(s6["roughness"] - 0.4) < 1e-6 and s6["arm_sg"] == s6["torso_sg"],
      "roughness %r sg %r" % (s6["roughness"], s6["arm_sg"]))

# --------------------------------------------------------------- phase 4
print("\n=== 4. a re-light takes the old dome's feed with it ===", flush=True)
ok("new_scene", {"confirm": True})
ok("setup_lighting", {"preset": "environment"})
relit = ok("setup_lighting", {"preset": "environment"})
s7 = state()
dome_src = py("import maya.cmds as cmds\n"
              "cmds.listConnections(cmds.ls(type='aiSkyDomeLight')[0] + '.color', s=True, d=False)", "dome")
check("4a. two environment lights in a row: ONE ramp in the scene",
      s7["ramps"] == ["mcpLight_domeRamp"], "ramps %r" % (s7["ramps"],))
check("4b. ... the replaced ramp is named in `removed`, the new dome is fed",
      "mcpLight_domeRamp" in relit["removed"] and dome_src == ["mcpLight_domeRamp"],
      "removed %r dome<- %r" % (relit["removed"], dome_src))
# #797 row 19: `environment` is the dome that needs no file and now refuses
# an hdri_path; the file-driven dome is the `hdri` preset.
ok("setup_lighting", {"preset": "hdri", "hdri_path": HDR})
ok("setup_lighting", {"preset": "hdri", "hdri_path": HDR})
s8 = state()
check("4c. hdri domes: one file node, no ramp left",
      s8["files"] == ["mcpLight_domeTex"] and s8["ramps"] == [],
      "files %r ramps %r" % (s8["files"], s8["ramps"]))
py("import maya.cmds as cmds\n"
   "m = cmds.shadingNode('lambert', asShader=True, name='keeper')\n"
   "cmds.connectAttr('mcpLight_domeTex.outColor', m + '.color', force=True)\nTrue", "keeper")
relit = ok("setup_lighting", {"preset": "environment"})
s9 = state()
check("4d. CONTROL: a feed something else still uses survives, and is named",
      "mcpLight_domeTex" in s9["files"] and "mcpLight_domeTex" not in relit["removed"]
      and any("mcpLight_domeTex" in w and "still used" in w for w in relit["warnings"]),
      "files %r warnings %r" % (s9["files"], relit["warnings"]))

# --------------------------------------------------------------- phase 5
print("\n=== 5. a normal slot behind a reverse is refused before anything bakes ===", flush=True)
bake_dir = os.path.join(OUT, "bake").replace("\\", "/")
os.makedirs(bake_dir, exist_ok=True)
for stale in os.listdir(bake_dir):
    os.remove(os.path.join(bake_dir, stale))
ok("new_scene", {"confirm": True})
py("""
import maya.cmds as cmds
b = cmds.polyCube(name="body")[0]
True
""", "setup")
ok("assign_material", {"mesh": "|body", "name": "skin_mat", "params": {}})
py("""
import maya.cmds as cmds
noise = cmds.shadingNode("noise", asTexture=True, name="mcpTex_noise")
bump = cmds.shadingNode("bump2d", asUtility=True, name="mcpTex_bump")
inv = cmds.shadingNode("reverse", asUtility=True, name="mcpTex_inv")
cmds.connectAttr(noise + ".outColorR", bump + ".bumpValue", force=True)
cmds.connectAttr(bump + ".outNormal", inv + ".input", force=True)
cmds.connectAttr(inv + ".output", "skin_mat.normalCamera", force=True)
True
""", "wire")
cps_before = py("from maya_plugin.handlers import session\nimport maya.cmds as cmds\n"
                "len(session._existing(session._checkpoint_dir(cmds)))", "cps")
err = refusal("bake_textures", {"meshes": ["|body"], "out_dir": bake_dir})
cps_after = py("from maya_plugin.handlers import session\nimport maya.cmds as cmds\n"
               "len(session._existing(session._checkpoint_dir(cmds)))", "cps")
wiring = py("import maya.cmds as cmds\n"
            "cmds.listConnections('skin_mat.normalCamera', s=True, d=False, plugs=True)", "wiring")
pngs = sorted(os.listdir(bake_dir)) if os.path.isdir(bake_dir) else []
check("5a. refused at plan time, naming the bump2d and the reverse",
      err is not None and err.get("type") == "HandlerError"
      and "bump2d" in err.get("message", "") and "reverse" in err.get("message", ""),
      (err or {}).get("message", "SUCCEEDED")[:140])
check("5b. ... no PNG written, no checkpoint spent, wiring untouched",
      pngs == [] and cps_after == cps_before and wiring == ["mcpTex_inv.output"],
      "pngs %r cps %d->%d wiring %r" % (pngs, cps_before, cps_after, wiring))
py("import maya.cmds as cmds\n"
   "cmds.connectAttr('mcpTex_bump.outNormal', 'skin_mat.normalCamera', force=True)\n"
   "cmds.delete('mcpTex_inv')\nTrue", "direct")
baked = ok("bake_textures", {"meshes": ["|body"], "out_dir": bake_dir, "resolution": 256}, timeout_s=600.0)
pngs = sorted(os.listdir(bake_dir)) if os.path.isdir(bake_dir) else []
wiring = py("import maya.cmds as cmds\n"
            "{'slot': cmds.listConnections('skin_mat.normalCamera', s=True, d=False, plugs=True),"
            " 'bump_in': cmds.listConnections('mcpTex_bump.bumpValue', s=True, d=False, plugs=True)}", "wiring")
check("5c. CONTROL: with the bump2d feeding the slot directly, the bake lands",
      any(p.endswith("_normal_baked.png") for p in pngs)
      and wiring["slot"] == ["mcpTex_bump.outNormal"]
      and (wiring["bump_in"] or [""])[0].endswith(".outColorR"),
      "pngs %r wiring %r" % (pngs, wiring))

# --------------------------------------------------------------- summary
ok("new_scene", {"confirm": True})
passed = sum(1 for _, okv, _ in RESULTS if okv)
print("\n%d/%d checks passed" % (passed, len(RESULTS)), flush=True)
for label, okv, detail in RESULTS:
    if not okv:
        print("  FAILED: %s  %s" % (label, detail))
with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as fh:
    json.dump([{"check": l, "ok": o, "detail": d} for l, o, d in RESULTS], fh, indent=1)
raise SystemExit(0 if passed == len(RESULTS) else 1)
