"""#770 probe: how THIS Maya 2027 actually bakes geometry-derived maps
(AO / curvature / normal) to textures.

Run:  E:\\Autodesk\\Maya2027\\bin\\mayapy.exe evals/meshmaps_probe_770.py
Every finding prints as 'PROBE <name>: <value>'. Facts, not assertions: a
surprising value here changes the plan's constants, not this script.

Questions this probe answers (each shapes a design decision):
  S1  Does mtoa load headless? Do aiAmbientOcclusion / aiCurvature /
      aiUtility / aiNormalMap node types exist? Does cmds.arnoldRenderToTexture
      exist, and what flags does it take?
  S2  What does a minimal bake actually write (file names, extension)? Can it
      write PNG directly, or EXR only? If EXR-only: can MImage read the EXR
      back and write a PNG that pngprobe can measure?
  S3  AO semantics: does the bake see OTHER meshes as occluders (the golem
      join case), or only self-occlusion? Measured by baking a ground plane
      with and without a box resting on it and comparing region means.
  S4  aiCurvature: does a bake distinguish edges from flats on a beveled cube?
  S5  Normal options: aiUtility color_mode='n' world-normal bake; does
      cmds.surfaceSampler exist (the high->low transfer path)?
  S6  Timing at 512 and 1024 (sets the tool's timeout budget).
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

OUT = os.path.join(tempfile.gettempdir(), "meshmaps_probe_770")
os.makedirs(OUT, exist_ok=True)


def probe(name, value):
    print("PROBE %s: %r" % (name, value), flush=True)


def section(title):
    print("=" * 10, title, "=" * 10, flush=True)


def listdir(folder):
    try:
        return sorted(os.listdir(folder))
    except OSError as exc:
        return "unlistable: %s" % exc


def clean(folder):
    for f in os.listdir(folder):
        try:
            os.unlink(os.path.join(folder, f))
        except OSError:
            pass


# ============================================================================
section("S1: Arnold availability under maya.standalone")
# ============================================================================
try:
    t0 = time.time()
    loaded = cmds.loadPlugin("mtoa", quiet=True)
    probe("mtoa_loadPlugin_returned", loaded)
    probe("mtoa_load_seconds", round(time.time() - t0, 1))
    for nt in ("aiAmbientOcclusion", "aiCurvature", "aiUtility", "aiNormalMap",
               "aiStandardSurface", "aiFlat"):
        try:
            node = cmds.shadingNode(nt, asShader=True, name="probe_" + nt)
            probe("nodetype_%s" % nt, "creatable")
            cmds.delete(node)
        except Exception as exc:  # noqa: BLE001
            probe("nodetype_%s" % nt, "NO: %s" % exc)
    probe("arnoldRenderToTexture_exists", hasattr(cmds, "arnoldRenderToTexture"))
    probe("surfaceSampler_exists", hasattr(cmds, "surfaceSampler"))
    try:
        probe("arnoldRenderToTexture_help", cmds.help("arnoldRenderToTexture"))
    except Exception as exc:  # noqa: BLE001
        probe("arnoldRenderToTexture_help", "unavailable: %s" % exc)
except Exception:
    traceback.print_exc()

# ============================================================================
section("S2: minimal bake - what lands on disk, and can we read it")
# ============================================================================


def fresh_plane_scene():
    cmds.file(new=True, force=True)
    plane = cmds.polyPlane(width=10, height=10, subdivisionsX=4,
                           subdivisionsY=4, constructionHistory=False)[0]
    return (cmds.ls(plane, long=True) or [plane])[0]


def assign_shader(mesh, shader):
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                   name=shader + "SG")
    cmds.connectAttr(shader + ".outColor", sg + ".surfaceShader", force=True)
    cmds.sets(mesh, edit=True, forceElement=sg)
    return sg


def bake(mesh, folder, resolution=256, **kw):
    cmds.select(mesh, replace=True)
    t0 = time.time()
    r = cmds.arnoldRenderToTexture(folder=folder, resolution=resolution, **kw)
    return r, round(time.time() - t0, 1)


try:
    plane = fresh_plane_scene()
    cmds.loadPlugin("mtoa", quiet=True)
    ao = cmds.shadingNode("aiAmbientOcclusion", asShader=True, name="probe_ao")
    assign_shader(plane, ao)
    clean(OUT)
    result, secs = bake(plane, OUT, resolution=256)
    probe("bake_returned", result)
    probe("bake_seconds_256_default_flags", secs)
    probe("bake_wrote", listdir(OUT))

    # can it write PNG natively?
    try:
        clean(OUT)
        result, secs = bake(plane, OUT, resolution=256, extension="png")
        probe("bake_extension_png_wrote", listdir(OUT))
    except Exception as exc:  # noqa: BLE001
        probe("bake_extension_png", "REFUSED: %s" % exc)

    # If EXR: can MImage read it and write PNG?
    clean(OUT)
    bake(plane, OUT, resolution=256)
    files = [f for f in os.listdir(OUT) if not f.endswith(".png")]
    if files:
        src = os.path.join(OUT, files[0])
        dst = os.path.join(OUT, "converted.png")
        try:
            import maya.OpenMaya as om1
            img = om1.MImage()
            img.readFromFile(src)
            img.writeToFile(dst, "png")
            probe("mimage_exr_to_png", pngprobe.uniformity(dst))
        except Exception as exc:  # noqa: BLE001
            probe("mimage_exr_to_png", "FAILED: %s" % exc)
        # float depth path (EXR is float; default readFromFile may clamp)
        try:
            img2 = om1.MImage()
            img2.readFromFileWithDepth(src, om1.MImage.kFloat)
            probe("mimage_read_float_depth", "ok")
        except Exception as exc:  # noqa: BLE001
            probe("mimage_read_float_depth", "FAILED: %s" % exc)
except Exception:
    traceback.print_exc()

# ============================================================================
section("S3: AO semantics - does the bake see other meshes as occluders?")
# ============================================================================


def region_mean(png_path, u0, u1, v0, v1):
    """Mean R value of texels whose UV-space position falls in the box.
    PNG row 0 is TOP of the image; Maya UV v=0 is BOTTOM - flip v."""
    png = pngprobe.read_png(png_path)
    w, h = png["width"], png["height"]
    px = png["pixels"]
    total, count = 0, 0
    for y in range(h):
        v = 1.0 - (y + 0.5) / h
        if not (v0 <= v <= v1):
            continue
        for x in range(w):
            u = (x + 0.5) / w
            if not (u0 <= u <= u1):
                continue
            total += px[y * w + x][0]
            count += 1
    return round(total / max(count, 1), 1)


def to_png(folder):
    """Convert whatever the bake wrote to PNG; return the png path."""
    files = [f for f in os.listdir(folder)
             if f != "converted.png" and not f.endswith(".part")]
    if not files:
        raise RuntimeError("bake wrote nothing")
    src = os.path.join(folder, files[0])
    if src.endswith(".png"):
        return src
    import maya.OpenMaya as om1
    img = om1.MImage()
    img.readFromFile(src)
    dst = os.path.join(folder, "converted.png")
    img.writeToFile(dst, "png")
    return dst


try:
    # bare plane, nothing above it
    plane = fresh_plane_scene()
    ao = cmds.shadingNode("aiAmbientOcclusion", asShader=True, name="probe_ao")
    assign_shader(plane, ao)
    clean(OUT)
    bake(plane, OUT, resolution=256)
    png = to_png(OUT)
    bare_center = region_mean(png, 0.4, 0.6, 0.4, 0.6)
    bare_corner = region_mean(png, 0.0, 0.15, 0.0, 0.15)
    probe("ao_bare_plane_center_mean", bare_center)
    probe("ao_bare_plane_corner_mean", bare_corner)
    probe("ao_bare_plane_uniformity", pngprobe.uniformity(png))

    # same plane with a box RESTING on its center (the golem-join shape)
    box = cmds.polyCube(width=2, height=2, depth=2,
                        constructionHistory=False)[0]
    cmds.setAttr(box + ".translateY", 1.0)  # resting on y=0 plane
    clean(OUT)
    bake(plane, OUT, resolution=256)
    png = to_png(OUT)
    contact_center = region_mean(png, 0.4, 0.6, 0.4, 0.6)
    contact_corner = region_mean(png, 0.0, 0.15, 0.0, 0.15)
    probe("ao_with_box_center_mean_UNDER_BOX", contact_center)
    probe("ao_with_box_corner_mean_AWAY", contact_corner)
    probe("ao_sees_other_meshes", contact_center < bare_center - 10)

    # does the OCCLUDER's own bake still work (box occluded by plane below)?
    ao2 = cmds.shadingNode("aiAmbientOcclusion", asShader=True, name="probe_ao2")
    assign_shader(box, ao2)
    clean(OUT)
    bake(box, OUT, resolution=256)
    probe("ao_box_bake_wrote", listdir(OUT))
    try:
        probe("ao_box_uniformity", pngprobe.uniformity(to_png(OUT)))
    except Exception as exc:  # noqa: BLE001
        probe("ao_box_uniformity", "FAILED: %s" % exc)

    # falloff / spread knobs exist?
    for attr in ("falloff", "spread", "nearClip", "farClip", "samples"):
        try:
            probe("aiAO_attr_%s" % attr, cmds.getAttr("%s.%s" % (ao, attr)))
        except Exception as exc:  # noqa: BLE001
            probe("aiAO_attr_%s" % attr, "NO: %s" % exc)
except Exception:
    traceback.print_exc()

# ============================================================================
section("S4: aiCurvature - edges vs flats on a beveled cube")
# ============================================================================
try:
    cmds.file(new=True, force=True)
    cube = cmds.polyCube(width=2, height=2, depth=2,
                         constructionHistory=False)[0]
    cube = (cmds.ls(cube, long=True) or [cube])[0]
    cmds.polyBevel3(cube, offset=0.15, segments=2, constructionHistory=False)
    # box-project UVs so every face samples somewhere sane
    cmds.polyAutoProjection(cube, layoutMethod=0, insertBeforeDeformers=True,
                            scaleMode=1, constructionHistory=False)
    curv = cmds.shadingNode("aiCurvature", asShader=True, name="probe_curv")
    assign_shader(cube, curv)
    for attr in ("output", "samples", "radius", "spread", "threshold", "bias"):
        try:
            probe("aiCurvature_attr_%s" % attr,
                  cmds.getAttr("%s.%s" % (curv, attr)))
        except Exception as exc:  # noqa: BLE001
            probe("aiCurvature_attr_%s" % attr, "NO: %s" % exc)
    clean(OUT)
    bake(cube, OUT, resolution=256)
    png = to_png(OUT)
    u = pngprobe.uniformity(png)
    probe("curvature_bake_uniformity", u)
    # distribution: how many texels are bright (edge-ish) vs dark
    full = pngprobe.read_png(png)
    rs = [p[0] for p in full["pixels"]]
    probe("curvature_r_min_mean_max",
          (min(rs), round(sum(rs) / len(rs), 1), max(rs)))
    bright = sum(1 for r in rs if r > 128)
    probe("curvature_bright_texel_fraction", round(bright / len(rs), 3))
except Exception:
    traceback.print_exc()

# ============================================================================
section("S5: normal bake options")
# ============================================================================
try:
    cmds.file(new=True, force=True)
    sphere = cmds.polySphere(radius=2, constructionHistory=False)[0]
    sphere = (cmds.ls(sphere, long=True) or [sphere])[0]
    util = cmds.shadingNode("aiUtility", asShader=True, name="probe_util")
    try:
        cmds.setAttr(util + ".shadeMode", 2)   # flat
        cmds.setAttr(util + ".colorMode", 2)   # n (world normal)? measure
        probe("aiUtility_shadeMode_colorMode_settable", True)
    except Exception as exc:  # noqa: BLE001
        probe("aiUtility_shadeMode_colorMode_settable", "NO: %s" % exc)
    # what do the enum values actually mean here?
    try:
        probe("aiUtility_colorMode_enums",
              cmds.attributeQuery("colorMode", node=util, listEnum=True))
        probe("aiUtility_shadeMode_enums",
              cmds.attributeQuery("shadeMode", node=util, listEnum=True))
    except Exception as exc:  # noqa: BLE001
        probe("aiUtility_enums", "NO: %s" % exc)
    assign_shader(sphere, util)
    clean(OUT)
    bake(sphere, OUT, resolution=256)
    try:
        u = pngprobe.uniformity(to_png(OUT))
        probe("world_normal_bake_uniformity", u)
    except Exception as exc:  # noqa: BLE001
        probe("world_normal_bake", "FAILED: %s" % exc)
    # arnoldRenderToTexture's own normal_offset / enable_aovs flags?
    for flag in ("normal_offset", "enable_aovs", "aa_samples", "filter",
                 "all_udims", "uv_set", "extend_edges"):
        probe("flag_probe_%s" % flag, "see S1 help output")
except Exception:
    traceback.print_exc()

# ============================================================================
section("S6: timing at 512 and 1024 (AO, default samples)")
# ============================================================================
try:
    plane = fresh_plane_scene()
    box = cmds.polyCube(width=2, height=2, depth=2,
                        constructionHistory=False)[0]
    cmds.setAttr(box + ".translateY", 1.0)
    ao = cmds.shadingNode("aiAmbientOcclusion", asShader=True, name="probe_ao")
    assign_shader(plane, ao)
    for res in (512, 1024):
        clean(OUT)
        _r, secs = bake(plane, OUT, resolution=res)
        probe("bake_seconds_%d" % res, secs)
except Exception:
    traceback.print_exc()

print("DONE", flush=True)
