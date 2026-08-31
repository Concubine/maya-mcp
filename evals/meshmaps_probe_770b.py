"""#770 probe round 2: anomalies and design questions left by round 1.

Run:  E:\\Autodesk\\Maya2027\\bin\\mayapy.exe evals/meshmaps_probe_770b.py

  Q1  Round 1's every converted PNG reported distinct_values=2 - even a
      sphere's world-normal bake, which cannot honestly be binary. What are
      the ACTUAL values? Is the loss in the EXR (sampling) or in the MImage
      conversion? Does aa_samples change it?
  Q2  The -shader flag: can a bake run WITHOUT assigning the shader to the
      mesh (no assign/restore dance)?
  Q3  aiCurvature output enum names; convex vs concave region means.
  Q4  Multi-mesh select: one file per shape? Short-name COLLISIONS?
  Q5  A UV-less mesh: raise, no file, or flat file?
  Q6  extend_edges flag runs and pads shells?
  Q7  Is maketx/oiiotool on disk (fallback converters)?
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

OUT = os.path.join(tempfile.gettempdir(), "meshmaps_probe_770b")
os.makedirs(OUT, exist_ok=True)


def probe(name, value):
    print("PROBE %s: %r" % (name, value), flush=True)


def section(title):
    print("=" * 10, title, "=" * 10, flush=True)


def listdir(folder):
    return sorted(os.listdir(folder))


def clean(folder):
    for f in os.listdir(folder):
        try:
            os.unlink(os.path.join(folder, f))
        except OSError:
            pass


def assign_shader(mesh, shader):
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                   name=shader + "SG")
    cmds.connectAttr(shader + ".outColor", sg + ".surfaceShader", force=True)
    cmds.sets(mesh, edit=True, forceElement=sg)
    return sg


def to_png(folder, exr_name=None):
    files = [f for f in listdir(folder) if f.endswith(".exr")]
    src = os.path.join(folder, exr_name or files[0])
    dst = src[:-4] + ".converted.png"
    import maya.OpenMaya as om1
    img = om1.MImage()
    img.readFromFile(src)
    img.writeToFile(dst, "png")
    return dst


def value_census(png_path, cap=24):
    png = pngprobe.read_png(png_path)
    from collections import Counter
    c = Counter(png["pixels"])
    common = c.most_common(cap)
    return {"colour_type": png["colour_type"], "distinct": len(c),
            "top": common[:8], "channels_min_max": [
                (min(p[i] for p in png["pixels"]),
                 max(p[i] for p in png["pixels"]))
                for i in range(len(png["pixels"][0]))]}


cmds.loadPlugin("mtoa", quiet=True)

# ============================================================================
section("Q1: what is actually in the sphere normal bake")
# ============================================================================
try:
    cmds.file(new=True, force=True)
    sphere = cmds.polySphere(radius=2, constructionHistory=False)[0]
    util = cmds.shadingNode("aiUtility", asShader=True, name="probe_util")
    cmds.setAttr(util + ".shadeMode", 2)   # flat
    cmds.setAttr(util + ".colorMode", 3)   # 'n' (world normal)
    assign_shader(sphere, util)
    clean(OUT)
    cmds.select(sphere, replace=True)
    cmds.arnoldRenderToTexture(folder=OUT, resolution=256)
    probe("normal_default_census", value_census(to_png(OUT)))

    clean(OUT)
    cmds.select(sphere, replace=True)
    cmds.arnoldRenderToTexture(folder=OUT, resolution=256, aa_samples=3)
    probe("normal_aa3_census", value_census(to_png(OUT)))

    # Is the EXR itself rich and only the conversion binary? Use imageInfo?
    # Try MImage pixel readback directly.
    import maya.OpenMaya as om1
    exr = [f for f in listdir(OUT) if f.endswith(".exr")][0]
    img = om1.MImage()
    img.readFromFile(os.path.join(OUT, exr))
    ptr = img.pixels()
    w, h = om1.MScriptUtil(), om1.MScriptUtil()
    wp, hp = w.asUintPtr(), h.asUintPtr()
    img.getSize(wp, hp)
    width = om1.MScriptUtil.getUint(wp)
    height = om1.MScriptUtil.getUint(hp)
    probe("mimage_size", (width, height))
    vals = set()
    for i in range(0, width * height * 4, 997 * 4):
        vals.add(om1.MScriptUtil.getUcharArrayItem(ptr, i))
        if len(vals) > 40:
            break
    probe("mimage_direct_sampled_distinct_R", sorted(vals))
except Exception:
    traceback.print_exc()

# ============================================================================
section("Q2: the -shader flag - bake without assigning")
# ============================================================================
try:
    cmds.file(new=True, force=True)
    plane = cmds.polyPlane(width=10, height=10, constructionHistory=False)[0]
    box = cmds.polyCube(width=2, height=2, depth=2,
                        constructionHistory=False)[0]
    cmds.setAttr(box + ".translateY", 1.0)
    ao = cmds.shadingNode("aiAmbientOcclusion", asShader=True, name="probe_ao")
    # NOT assigned to anything. Plane keeps default lambert.
    clean(OUT)
    cmds.select(plane, replace=True)
    cmds.arnoldRenderToTexture(folder=OUT, resolution=128, shader="probe_ao")
    probe("shader_flag_wrote", listdir(OUT))
    png = to_png(OUT)
    census = value_census(png)
    probe("shader_flag_census", census)
    # region means: center (under box) should be dark if AO really ran
    png_data = pngprobe.read_png(png)
    w, h, px = png_data["width"], png_data["height"], png_data["pixels"]
    center = [px[y * w + x][0] for y in range(h) for x in range(w)
              if 0.4 <= (x + 0.5) / w <= 0.6 and 0.4 <= 1 - (y + 0.5) / h <= 0.6]
    corner = [px[y * w + x][0] for y in range(h) for x in range(w)
              if (x + 0.5) / w <= 0.15 and 1 - (y + 0.5) / h <= 0.15]
    probe("shader_flag_ao_center_mean", round(sum(center) / len(center), 1))
    probe("shader_flag_ao_corner_mean", round(sum(corner) / len(corner), 1))
except Exception:
    traceback.print_exc()

# ============================================================================
section("Q3: aiCurvature output modes")
# ============================================================================
try:
    cmds.file(new=True, force=True)
    cube = cmds.polyCube(width=2, height=2, depth=2,
                         constructionHistory=False)[0]
    cmds.polyBevel3(cube, offset=0.15, segments=2, constructionHistory=False)
    cmds.polyAutoProjection(cube, layoutMethod=0, insertBeforeDeformers=True,
                            scaleMode=1, constructionHistory=False)
    curv = cmds.shadingNode("aiCurvature", asShader=True, name="probe_curv")
    probe("aiCurvature_output_enums",
          cmds.attributeQuery("output", node=curv, listEnum=True))
    for mode in (0, 1, 2):
        try:
            cmds.setAttr(curv + ".output", mode)
            cmds.setAttr(curv + ".radius", 0.3)
            clean(OUT)
            cmds.select(cube, replace=True)
            cmds.arnoldRenderToTexture(folder=OUT, resolution=128,
                                       shader="probe_curv", aa_samples=3)
            png = to_png(OUT)
            data = pngprobe.read_png(png)
            rs = [p[0] for p in data["pixels"]]
            probe("curvature_mode%d_r_min_mean_max_distinct" % mode,
                  (min(rs), round(sum(rs) / len(rs), 1), max(rs),
                   len(set(rs))))
        except Exception as exc:  # noqa: BLE001
            probe("curvature_mode%d" % mode, "FAILED: %s" % exc)
except Exception:
    traceback.print_exc()

# ============================================================================
section("Q4: multi-mesh select and short-name collisions")
# ============================================================================
try:
    cmds.file(new=True, force=True)
    a = cmds.polyCube(constructionHistory=False, name="part")[0]
    g1 = cmds.group(a, name="left")
    b = cmds.polyCube(constructionHistory=False, name="part")[0]
    g2 = cmds.group(b, name="right")
    cmds.setAttr("right|part.translateX", 3)
    shapes = cmds.ls(type="mesh", long=True)
    probe("collision_shapes", shapes)
    clean(OUT)
    cmds.select(shapes, replace=True)
    cmds.arnoldRenderToTexture(folder=OUT, resolution=64, shader=None
                               if False else "initialShadingGroup")
except Exception as exc:  # noqa: BLE001
    probe("collision_bake_with_sg_shader", "FAILED: %s" % exc)
try:
    clean(OUT)
    cmds.select(cmds.ls(type="mesh", long=True), replace=True)
    cmds.arnoldRenderToTexture(folder=OUT, resolution=64)
    probe("collision_bake_wrote", listdir(OUT))
except Exception:
    traceback.print_exc()

# ============================================================================
section("Q5: a UV-less mesh")
# ============================================================================
try:
    cmds.file(new=True, force=True)
    cube = cmds.polyCube(constructionHistory=False)[0]
    shape = cmds.listRelatives(cube, shapes=True, fullPath=True)[0]
    cmds.polyMapDel(shape + ".map[*]")
    probe("uvless_uv_count", cmds.polyEvaluate(shape, uvcoord=True))
    clean(OUT)
    cmds.select(cube, replace=True)
    try:
        cmds.arnoldRenderToTexture(folder=OUT, resolution=64)
        probe("uvless_bake_wrote", listdir(OUT))
        if any(f.endswith(".exr") for f in listdir(OUT)):
            probe("uvless_census", value_census(to_png(OUT)))
    except Exception as exc:  # noqa: BLE001
        probe("uvless_bake", "RAISED: %s" % exc)
except Exception:
    traceback.print_exc()

# ============================================================================
section("Q6: extend_edges")
# ============================================================================
try:
    cmds.file(new=True, force=True)
    sphere = cmds.polySphere(radius=2, constructionHistory=False)[0]
    ao = cmds.shadingNode("aiAmbientOcclusion", asShader=True, name="probe_ao")
    clean(OUT)
    cmds.select(sphere, replace=True)
    t0 = time.time()
    cmds.arnoldRenderToTexture(folder=OUT, resolution=128, shader="probe_ao",
                               extend_edges=True)
    probe("extend_edges_ran_seconds", round(time.time() - t0, 1))
    probe("extend_edges_wrote", listdir(OUT))
except Exception:
    traceback.print_exc()

# ============================================================================
section("Q7: converter binaries on disk")
# ============================================================================
for candidate in (
    r"C:\Program Files\Autodesk\Arnold\Maya2027\bin\maketx.exe",
    r"C:\Program Files\Autodesk\Arnold\Maya2027\bin\oiiotool.exe",
    r"E:\Autodesk\Maya2027\bin\imgcvt.exe",
):
    probe("exists_%s" % os.path.basename(candidate), os.path.isfile(candidate))

print("DONE", flush=True)
