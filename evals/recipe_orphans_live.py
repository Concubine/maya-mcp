"""#812 LIVE GATE: apply_texture_recipe re-applied on a slot sweeps the network
it displaces - measured in the scene graph, over the wire.

  1. ramp_gradient twice on colour: ONE ramp in the scene, under the base
     name, feeding baseColor; `replaced` names the old one.
  2. noise_bump twice on normal: one noise, one bump2d (the noise is two hops
     up - the fixpoint); the new noise carries the new scale.
  3. layered_mask twice: one layeredTexture, one mask noise.
  4. A recipe over a slot assign_pbr mapped takes the file node AND its
     place2dTexture; the colour-management singleton is untouched.
  5. CONTROL: an old ramp a second shader still reads survives, is named in
     warnings, and the new ramp keeps its suffix.
  6. CONTROL: a recipe on a DIFFERENT slot replaces nothing.
  7. CONTROL: a scalar slot (roughness) sweeps the same way.
  8. A builder that fails after the capture leaves the previous network
     wired and deletes only what the failed call built.

DESTRUCTIVE: calls maya_new_scene. Runs against the disposable agent Maya on
9878 and REFUSES 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1. The live Maya must
import THIS working tree (launch it with the repo as its working directory).
Phase 0 asserts exactly that.

Run:  MAYA_MCP_PORT=9878 python evals/recipe_orphans_live.py
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

OUT = os.path.join(_HERE, "recipe_orphans_live")
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
    """A tiny real PNG on disk - assign_pbr checks the path exists."""
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


A = png("a.png")

STATE = r'''
import maya.cmds as cmds
def feeds(plug):
    return cmds.listConnections(plug, s=True, d=False, plugs=True)
nodes = {t: sorted(cmds.ls(type=t)) for t in ("ramp", "noise", "bump2d", "layeredTexture", "file", "place2dTexture")}
{"nodes": nodes,
 "baseColor": feeds("clay.baseColor"), "normalCamera": feeds("clay.normalCamera"),
 "roughness": feeds("clay.specularRoughness"),
 "cmg": cmds.objExists("defaultColorMgtGlobals"),
 "freq": {n: cmds.getAttr(n + ".frequency") for n in cmds.ls(type="noise")}}
'''


def state():
    return py(STATE, "state")


def fresh():
    ok("new_scene", {"confirm": True})
    py("import maya.cmds as cmds\ncmds.polyCube(name='torso')\nTrue", "setup")
    ok("assign_material", {"mesh": "|torso", "shader": "standardSurface",
                           "name": "clay", "params": {}})


def recipe(name, **extra):
    return ok("apply_texture_recipe", {"mesh": "|torso", "recipe": name, **extra})


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
has = py("from maya_plugin.handlers import texture_recipes\n"
         "hasattr(texture_recipes, '_node') and 'orphans' in dir(texture_recipes)", "loaded")
check("0. the #812 recipe handler is loaded in the live Maya", has is True)

# --------------------------------------------------------------- phase 1
print("\n=== 1. ramp_gradient twice ===", flush=True)
fresh()
first = recipe("ramp_gradient")
check("1a. first ramp: replaced nothing, named mcpTex_ramp",
      first["replaced"] == [] and first["nodes"] == ["mcpTex_ramp"], json.dumps(first["nodes"]))
second = recipe("ramp_gradient")
s = state()
check("1b. second ramp: ONE ramp in the scene, under the base name",
      s["nodes"]["ramp"] == ["mcpTex_ramp"], json.dumps(s["nodes"]["ramp"]))
check("1c. ... it is the NEW one feeding baseColor, and replaced names the old",
      s["baseColor"] == ["mcpTex_ramp.outColor"] and second["replaced"] == ["mcpTex_ramp"]
      and second["nodes"] == ["mcpTex_ramp"],
      "src %r replaced %r nodes %r" % (s["baseColor"], second["replaced"], second["nodes"]))

# --------------------------------------------------------------- phase 2
print("\n=== 2. noise_bump twice ===", flush=True)
fresh()
recipe("noise_bump")
second = recipe("noise_bump", params={"scale": 2.0})
s = state()
check("2a. one noise and one bump2d, base names",
      s["nodes"]["noise"] == ["mcpTex_noise"] and s["nodes"]["bump2d"] == ["mcpTex_bump"],
      json.dumps({k: s["nodes"][k] for k in ("noise", "bump2d")}))
check("2b. replaced names both old nodes (the noise via the fixpoint)",
      sorted(second["replaced"]) == ["mcpTex_bump", "mcpTex_noise"], json.dumps(second["replaced"]))
check("2c. the surviving noise carries the NEW scale and feeds normalCamera through the bump",
      s["freq"].get("mcpTex_noise") == 16.0 and s["normalCamera"] == ["mcpTex_bump.outNormal"],
      "freq %r normal %r" % (s["freq"], s["normalCamera"]))

# --------------------------------------------------------------- phase 3
print("\n=== 3. layered_mask twice ===", flush=True)
fresh()
recipe("layered_mask")
second = recipe("layered_mask")
s = state()
check("3a. one layeredTexture and one mask noise, base names",
      s["nodes"]["layeredTexture"] == ["mcpTex_layered"] and s["nodes"]["noise"] == ["mcpTex_mask"],
      json.dumps({k: s["nodes"][k] for k in ("layeredTexture", "noise")}))
check("3b. replaced names both", sorted(second["replaced"]) == ["mcpTex_layered", "mcpTex_mask"],
      json.dumps(second["replaced"]))

# --------------------------------------------------------------- phase 4
print("\n=== 4. a recipe over a slot assign_pbr mapped ===", flush=True)
fresh()
ok("assign_pbr", {"mesh": "|torso", "name": "clay", "maps": {"color": A}})
before = state()
second = recipe("ramp_gradient")
s = state()
check("4a. before: the pbr file node and its p2d are on the slot",
      before["nodes"]["file"] == ["clay_color_tex"] and before["nodes"]["place2dTexture"] == ["clay_color_p2d"])
check("4b. after: both gone, the ramp feeds baseColor, replaced names them in walk order",
      s["nodes"]["file"] == [] and s["nodes"]["place2dTexture"] == []
      and s["baseColor"] == ["mcpTex_ramp.outColor"]
      and second["replaced"] == ["clay_color_tex", "clay_color_p2d"],
      "files %r p2d %r replaced %r" % (s["nodes"]["file"], s["nodes"]["place2dTexture"], second["replaced"]))
check("4c. ... the colour-management singleton is untouched", s["cmg"] is True)

# --------------------------------------------------------------- phase 5
print("\n=== 5. CONTROL: an old ramp something else still reads ===", flush=True)
fresh()
recipe("ramp_gradient")
py("""
import maya.cmds as cmds
other = cmds.shadingNode("lambert", asShader=True, name="other")
cmds.connectAttr("mcpTex_ramp.outColor", other + ".color", force=True)
True
""", "share")
second = recipe("ramp_gradient")
s = state()
check("5a. the shared ramp survives, replaced is empty",
      s["nodes"]["ramp"] == ["mcpTex_ramp", "mcpTex_ramp_001"] and second["replaced"] == [],
      json.dumps(s["nodes"]["ramp"]))
check("5b. ... and a warning names it and what still uses it",
      any("mcpTex_ramp" in w and "still used by" in w and "other" in w for w in second["warnings"]),
      json.dumps(second["warnings"]))
check("5c. ... the new ramp keeps its suffix and feeds the slot",
      second["nodes"] == ["mcpTex_ramp_001"] and s["baseColor"] == ["mcpTex_ramp_001.outColor"],
      "nodes %r src %r" % (second["nodes"], s["baseColor"]))
still = py("import maya.cmds as cmds\ncmds.listConnections('other.color', s=True, d=False, plugs=True)", "still")
check("5d. ... and the other shader still reads it", still == ["mcpTex_ramp.outColor"], json.dumps(still))

# --------------------------------------------------------------- phase 6
print("\n=== 6. CONTROL: a different slot replaces nothing ===", flush=True)
fresh()
recipe("ramp_gradient")
second = recipe("noise_bump")
s = state()
check("6. ramp on colour then noise_bump on normal: both stand, replaced empty",
      s["nodes"]["ramp"] == ["mcpTex_ramp"] and s["nodes"]["bump2d"] == ["mcpTex_bump"]
      and second["replaced"] == [], json.dumps(second["replaced"]))

# --------------------------------------------------------------- phase 7
print("\n=== 7. CONTROL: a scalar slot ===", flush=True)
fresh()
recipe("ramp_gradient", slot="roughness")
second = recipe("ramp_gradient", slot="roughness")
s = state()
check("7. roughness twice: one ramp, outColorR feeds the scalar, replaced names the old",
      s["nodes"]["ramp"] == ["mcpTex_ramp"] and s["roughness"] == ["mcpTex_ramp.outColorR"]
      and second["replaced"] == ["mcpTex_ramp"],
      "ramps %r src %r" % (s["nodes"]["ramp"], s["roughness"]))

# --------------------------------------------------------------- phase 8
print("\n=== 8. a failure after the capture ===", flush=True)
fresh()
recipe("noise_bump")
before = state()
# make the SECOND node's creation fail: reserve every bump2d name the
# builder could mint, so unique_name raises after the noise exists
py("""
import maya.cmds as cmds
from maya_plugin.handlers import texture_recipes, naming
_real = cmds.shadingNode
def _boom(node_type, **kw):
    if node_type == "bump2d":
        raise RuntimeError("probe: bump2d creation refused")
    return _real(node_type, **kw)
cmds.shadingNode = _boom
True
""", "arm")
err = refusal("apply_texture_recipe", {"mesh": "|torso", "recipe": "noise_bump"})
py("import maya.cmds as cmds\ncmds.shadingNode = _real\nTrue", "disarm")
s = state()
check("8a. the call failed", err is not None and "bump2d" in json.dumps(err))
check("8b. the previous network is exactly as it was, still wired",
      s["nodes"]["noise"] == before["nodes"]["noise"] == ["mcpTex_noise"]
      and s["nodes"]["bump2d"] == before["nodes"]["bump2d"] == ["mcpTex_bump"]
      and s["normalCamera"] == ["mcpTex_bump.outNormal"],
      "noise %r bump %r normal %r" % (s["nodes"]["noise"], s["nodes"]["bump2d"], s["normalCamera"]))

# --------------------------------------------------------------- summary
ok("new_scene", {"confirm": True})
passed = sum(1 for _, r, _ in RESULTS if r)
print("\n%d / %d passed" % (passed, len(RESULTS)))
with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as fh:
    json.dump([{"check": label, "ok": r, "detail": d} for label, r, d in RESULTS], fh, indent=1)
raise SystemExit(0 if passed == len(RESULTS) else 1)
