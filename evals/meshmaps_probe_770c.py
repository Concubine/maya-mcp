"""#770 probe round 3: the last two design constants.

Run:  E:\\Autodesk\\Maya2027\\bin\\mayapy.exe evals/meshmaps_probe_770c.py

  T1  MImage's EXR->PNG transfer: bake aiAmbientOcclusion with white=0.5 on
      an unoccluded plane. Every texel is linear 0.5. PNG value 128 = the
      conversion is LINEAR; ~188 = it applies sRGB. Decides how the AO
      composite decodes its own map.
  T2  Dense-mesh timing: a ~125k-tri sphere at 1024 (golem-class budget).
  T3  extend_edges alpha: does padding extend the alpha mask too? Decides
      whether alpha>0 is a usable "this texel was baked" mask.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import maya.standalone

maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402

from maya_plugin.handlers import pngprobe  # noqa: E402

OUT = os.path.join(tempfile.gettempdir(), "meshmaps_probe_770c")
os.makedirs(OUT, exist_ok=True)


def probe(name, value):
    print("PROBE %s: %r" % (name, value), flush=True)


def clean():
    for f in os.listdir(OUT):
        try:
            os.unlink(os.path.join(OUT, f))
        except OSError:
            pass


def to_png():
    files = [f for f in sorted(os.listdir(OUT)) if f.endswith(".exr")]
    src = os.path.join(OUT, files[0])
    dst = src[:-4] + ".converted.png"
    import maya.OpenMaya as om1
    img = om1.MImage()
    img.readFromFile(src)
    img.writeToFile(dst, "png")
    return dst


cmds.loadPlugin("mtoa", quiet=True)

# ---- T1: transfer function --------------------------------------------------
try:
    cmds.file(new=True, force=True)
    plane = cmds.polyPlane(width=10, height=10, constructionHistory=False)[0]
    ao = cmds.shadingNode("aiAmbientOcclusion", asShader=True, name="probe_ao")
    cmds.setAttr(ao + ".white", 0.5, 0.5, 0.5, type="double3")
    clean()
    cmds.select(plane, replace=True)
    cmds.arnoldRenderToTexture(folder=OUT, resolution=64, shader="probe_ao")
    png = pngprobe.read_png(to_png())
    from collections import Counter
    c = Counter(p[0] for p in png["pixels"])
    probe("half_white_ao_R_histogram_top", c.most_common(5))
    # 128 => linear passthrough; ~188 => sRGB encode on write
except Exception:
    traceback.print_exc()

# ---- T2: dense mesh timing --------------------------------------------------
try:
    cmds.file(new=True, force=True)
    sphere = cmds.polySphere(radius=2, subdivisionsAxis=250,
                             subdivisionsHeight=250,
                             constructionHistory=False)[0]
    probe("dense_tris", cmds.polyEvaluate(sphere, triangle=True))
    floor = cmds.polyPlane(width=10, height=10, constructionHistory=False)[0]
    cmds.setAttr(sphere + ".translateY", 2.0)
    ao = cmds.shadingNode("aiAmbientOcclusion", asShader=True, name="probe_ao")
    clean()
    cmds.select(sphere, replace=True)
    t0 = time.time()
    cmds.arnoldRenderToTexture(folder=OUT, resolution=1024, shader="probe_ao",
                               extend_edges=True)
    probe("dense_1024_ao_seconds", round(time.time() - t0, 1))
except Exception:
    traceback.print_exc()

# ---- T3: extend_edges and the alpha mask ------------------------------------
try:
    cmds.file(new=True, force=True)
    sphere = cmds.polySphere(radius=2, constructionHistory=False)[0]
    ao = cmds.shadingNode("aiAmbientOcclusion", asShader=True, name="probe_ao")
    for flag in (False, True):
        clean()
        cmds.select(sphere, replace=True)
        cmds.arnoldRenderToTexture(folder=OUT, resolution=128,
                                   shader="probe_ao", extend_edges=flag)
        png = pngprobe.read_png(to_png())
        alphas = [p[3] for p in png["pixels"]]
        opaque = sum(1 for a in alphas if a > 0)
        probe("extend_edges_%s_opaque_fraction" % flag,
              round(opaque / len(alphas), 3))
except Exception:
    traceback.print_exc()

print("DONE", flush=True)
