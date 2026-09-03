"""THROWAWAY PROBE (#812: apply_texture_recipe re-apply orphans) - measure
BEFORE designing. What does the scene hold after a recipe is applied twice on
one slot, after a recipe lands on a slot assign_pbr mapped, and after
assign_pbr lands on a recipe slot? Nothing here asserts; it records.

DESTRUCTIVE: calls new_scene. Agent Maya on 9878 only.
Run:  MAYA_MCP_PORT=9878 python evals/recipe_orphans_probe.py
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
if PORT == 9877:
    raise SystemExit("refusing the user's Maya")

OUT = os.path.join(_HERE, "recipe_orphans_probe_812")
os.makedirs(OUT, exist_ok=True)


def png(name):
    """A tiny real PNG on disk (look_orphans_live's helper)."""
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


A, B = png("a.png"), png("b.png")


def ok(command, params, timeout_s=120.0):
    r = call(command, params, timeout_s=timeout_s, port=PORT)
    if r.get("status") != "ok":
        raise SystemExit("%s failed: %s" % (command, json.dumps(r.get("error"), indent=1)))
    return r.get("result") or {}


def err(command, params, timeout_s=120.0):
    r = call(command, params, timeout_s=timeout_s, port=PORT)
    return None if r.get("status") == "ok" else r.get("error")


def py(code, what="r"):
    return structured_result(ok("execute_python", {"code": code}), what)


STATE = r'''
import maya.cmds as cmds
def feeds(plug):
    return cmds.listConnections(plug, s=True, d=False, plugs=True) if cmds.objExists(plug.split(".")[0]) else None
def outs(node):
    return sorted(set(cmds.listConnections(node, s=False, d=True) or []))
nodes = {t: sorted(cmds.ls(type=t)) for t in ("ramp", "noise", "bump2d", "layeredTexture", "file", "place2dTexture", "reverse")}
{"nodes": nodes,
 "outs": {n: outs(n) for t in nodes for n in nodes[t]},
 "baseColor": feeds("clay.baseColor"), "normalCamera": feeds("clay.normalCamera"),
 "roughness": feeds("clay.specularRoughness")}
'''


def state():
    return py(STATE, "state")


def show(label, value):
    print("\n--- %s ---" % label)
    print(json.dumps(value, indent=1, sort_keys=True))


def fresh():
    ok("new_scene", {"confirm": True})
    py("import maya.cmds as cmds\ncmds.polyCube(name='torso')\nTrue", "setup")
    ok("assign_material", {"mesh": "|torso", "shader": "standardSurface",
                           "name": "clay", "params": {}})


ident = py("import os, maya_plugin\n{'file': maya_plugin.__file__, 'cwd': os.getcwd()}", "identity")
print("live plugin:", ident)

# 1. ramp_gradient twice on color
fresh()
r1 = ok("apply_texture_recipe", {"mesh": "|torso", "recipe": "ramp_gradient"})
show("1a. ramp once: result", r1)
show("1a. ramp once: state", state())
r2 = ok("apply_texture_recipe", {"mesh": "|torso", "recipe": "ramp_gradient"})
show("1b. ramp twice: result", r2)
show("1b. ramp twice: state", state())

# 2. noise_bump twice on normal, then layered_mask twice on color
fresh()
ok("apply_texture_recipe", {"mesh": "|torso", "recipe": "noise_bump"})
n2 = ok("apply_texture_recipe", {"mesh": "|torso", "recipe": "noise_bump",
                                 "params": {"scale": 2.0}})
show("2a. noise_bump twice: result", n2)
show("2a. noise_bump twice: state", state())
ok("apply_texture_recipe", {"mesh": "|torso", "recipe": "layered_mask"})
l2 = ok("apply_texture_recipe", {"mesh": "|torso", "recipe": "layered_mask"})
show("2b. layered_mask twice: result", l2)
show("2b. layered_mask twice: state", state())

# 3. recipe over a slot assign_pbr mapped (file + p2d two hops up)
fresh()
p = ok("assign_pbr", {"mesh": "|torso", "name": "clay", "maps": {"color": A}})
show("3a. pbr colour: result", p)
show("3a. pbr colour: state", state())
r3 = ok("apply_texture_recipe", {"mesh": "|torso", "recipe": "ramp_gradient"})
show("3b. ramp over pbr: result", r3)
show("3b. ramp over pbr: state", state())

# 4. control: assign_pbr over a recipe slot (does #804's sweep take the ramp?)
fresh()
ok("apply_texture_recipe", {"mesh": "|torso", "recipe": "ramp_gradient"})
p4 = ok("assign_pbr", {"mesh": "|torso", "name": "clay", "maps": {"color": A}})
show("4. pbr over ramp: result", p4)
show("4. pbr over ramp: state", state())

# 5. a recipe node something else still uses
fresh()
ok("apply_texture_recipe", {"mesh": "|torso", "recipe": "ramp_gradient"})
py("""
import maya.cmds as cmds
other = cmds.shadingNode("lambert", asShader=True, name="other")
ramp = cmds.ls(type="ramp")[0]
cmds.connectAttr(ramp + ".outColor", other + ".color", force=True)
True
""", "share")
r5 = ok("apply_texture_recipe", {"mesh": "|torso", "recipe": "ramp_gradient"})
show("5. ramp over a SHARED ramp: result", r5)
show("5. ramp over a SHARED ramp: state", state())

# 6. file_texture over ramp: does the file recipe make a p2d at all?
fresh()
ok("apply_texture_recipe", {"mesh": "|torso", "recipe": "ramp_gradient"})
f6 = ok("apply_texture_recipe", {"mesh": "|torso", "recipe": "file_texture",
                                 "params": {"file_path": B}})
show("6. file_texture over ramp: result", f6)
show("6. file_texture over ramp: state", state())

# 7. explicit slot: ramp on roughness (scalar) twice
fresh()
ok("apply_texture_recipe", {"mesh": "|torso", "recipe": "ramp_gradient", "slot": "roughness"})
s7 = ok("apply_texture_recipe", {"mesh": "|torso", "recipe": "ramp_gradient", "slot": "roughness"})
show("7. ramp on roughness twice: result", s7)
show("7. ramp on roughness twice: state", state())
