"""#775 probes. P1 headless: python evals/surfdetail_probe_775.py p1
P2 live (agent Maya on 9878): set MAYA_MCP_PORT=9878 first, then
python evals/surfdetail_probe_775.py p2 -- MUTATES the answering scene."""
from __future__ import annotations
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from maya_plugin.handlers import sculpt_math

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "surfdetail_probe")

def p1():
    """fbm cost at 1024^2 and 256^2 - decides full-res vs upsample."""
    for size in (256, 1024):
        t0 = time.time()
        vals = [sculpt_math.fbm((i % size) / 64.0, (i // size) / 64.0, 0.0)
                for i in range(size * size)]
        dt = time.time() - t0
        print("P1 %dx%d: %.1fs (%d samples, min %.3f max %.3f)"
              % (size, size, dt, len(vals), min(vals), max(vals)), flush=True)

def p2():
    """file->bump2d(interp 0)->standardSurface: does the PNG ride the FBX?"""
    from live_call import call
    os.makedirs(OUT, exist_ok=True)
    height_png = os.path.join(OUT, "p2_height.png")
    from maya_plugin.handlers import pngwrite
    px = [((x * 7 + y * 13) % 256,) * 3 for y in range(64) for x in range(64)]
    pngwrite.write_png(height_png, 64, 64, px)
    fbx = os.path.join(OUT, "p2_bump.fbx").replace("\\", "/")
    r = call("execute_python", {"code": """
import maya.cmds as cmds
cmds.file(new=True, force=True)
t = cmds.polyCube(name='p2_cube', constructionHistory=False)[0]
cmds.makeIdentity(t, apply=True)
sh = cmds.shadingNode('standardSurface', asShader=True, name='p2_mat')
sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name='p2_sg')
cmds.connectAttr(sh + '.outColor', sg + '.surfaceShader')
cmds.sets(t, edit=True, forceElement=sg)
f = cmds.shadingNode('file', asTexture=True, name='p2_heightfile')
cmds.setAttr(f + '.fileTextureName', %r, type='string')
b = cmds.shadingNode('bump2d', asUtility=True, name='p2_bump')
cmds.setAttr(b + '.bumpInterp', 0)
cmds.connectAttr(f + '.outAlpha', b + '.bumpValue', force=True)
cmds.connectAttr(b + '.outNormal', sh + '.normalCamera', force=True)
result = 'wired'
""" % height_png.replace("\\", "/")})
    print("P2 wire:", r.get("status"), r.get("result"), flush=True)
    r = call("export_fbx", {"path": fbx, "metres_per_unit": 1.0,
                            "nodes": ["p2_cube"],
                            "require_baked_textures": True}, timeout_s=300.0)
    print("P2 export:", r.get("status"),
          (r.get("result") or {}).get("textures"), flush=True)
    if r.get("status") == "ok":
        with open(fbx.replace("/", os.sep), "rb") as fh:
            data = fh.read()
        print("P2 basename in FBX bytes:", b"p2_height.png" in data, flush=True)

if __name__ == "__main__":
    {"p1": p1, "p2": p2}.get(sys.argv[1] if len(sys.argv) > 1 else "",
        lambda: sys.exit(__doc__))()
