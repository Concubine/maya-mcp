"""maya-mcp #714 phase 1 Task 8: the five bake probes and the phase-2
GO/NO-GO.

Phase 1 (detect + report + gate texture loss on export) is built and proven.
Phase 2 would be a `maya_bake_textures` tool that converts procedural
shading networks into file textures so the look actually ships. Nothing in
phase 1 depends on the outcomes measured here - a disappointing result
shapes phase 2's design, it cannot sink phase 1. `convertSolidTx` appears
NOWHERE else in this repo's production code; this script is the first
measurement of it.

Per the spec (docs/superpowers/specs/2026-08-25-714-export-texture-honesty-
design.md): phase 2 proceeds iff P2 yields a usable bake on box-projection
UVs (case b below - the golem-class case, primitive polyCube UVs). P2 also
answers which phase-2 design arm applies: if the bake is proven
mesh-INDEPENDENT (pure 2D/UV-space sampling), a material shared across
meshes can bake ONCE; if it is mesh-DEPENDENT (reads the actual 3D surface),
phase 2 must refuse shared materials and bake per mesh.

- P1: does convertSolidTx run under maya.standalone at all.
- P2: THE GO/NO-GO. Bakes a `noise` recipe through (a) clean 0..1 UVs,
  (b) primitive/box-projection UVs, (c) a UV-less mesh (records the exact
  failure mode - it becomes phase 2's refusal message), and (d) the same
  UVs on two meshes at different world positions/scale, to decide the
  design arm.
- P3: the written PNG's IHDR (bit depth, colour type), plus whether the
  pre-bump scalar (noise.outColorR) bakes into something usable - bump-as-
  height viability.
- P4: does a `file -> bump2d(bumpInterp=0) -> normalCamera` height path
  survive export (image basename present in the FBX bytes, read via
  fbxbytes.texture_facts).
- P5: what the bytes carry for a `file` node whose image is missing from
  disk.

Every probe is independently runnable and FAILURE-TOLERANT: each catches
its own exceptions, prints the full traceback, and continues - a probe that
cannot run is a measured answer, not a crash. No probe fabricates a number;
where a pixel check is not possible (an unsupported PNG shape, an unreadable
file) the probe says so and reports what it CAN measure (file size) instead.

This script is standalone: not part of any test suite, not imported by
anything, run directly under mayapy.

Run:
    E:\\Autodesk\\Maya2027\\bin\\mayapy.exe evals\\bake_probe_714.py

Exit: 0 if the script ran to completion (regardless of individual probe
verdicts - a measured NO-GO is still a successful run), 2 if maya.standalone
is not importable (this is not a live-Maya-port eval).
"""

from __future__ import annotations

import os
import struct
import sys
import traceback
import zlib

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

try:
    import maya.standalone
except ImportError:
    print("mayapy / Maya's embedded Python is required - this cannot run "
          "against a live Maya port. See the module docstring for the "
          "mayapy invocation.")
    sys.exit(2)

OUT_DIR = os.path.join(_HERE, "bake_probe_714_out")

_COLOR_TYPE_NAMES = {0: "greyscale", 2: "RGB", 3: "palette",
                     4: "greyscale+alpha", 6: "RGBA"}


# --------------------------------------------------------------------------
# A minimal, dependency-free PNG reader (struct + zlib only - the repo has
# no Pillow and hand-rolls its PNG writers the same way, see
# evals/tool_gaps_live.py:write_png and evals/drifter_live.py). This is a
# READER: IHDR fields plus defiltered pixel rows, for the uniformity check
# P2/P3 need. Only what this probe requires is supported - 8/16-bit depth,
# colour type 0/2/4/6, no interlacing. Anything else raises
# NotImplementedError describing exactly what WAS found, so the caller can
# fall back to a file-size-only report instead of guessing pixel values.
# --------------------------------------------------------------------------
def _read_png(path):
    with open(path, "rb") as fh:
        data = fh.read()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("%s does not start with a PNG signature" % path)
    pos = 8
    ihdr = None
    idat = bytearray()
    while pos < len(data):
        length = struct.unpack_from(">I", data, pos)[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
        pos += 8 + length + 4  # length field + tag + data + crc32
    if ihdr is None:
        raise ValueError("%s carries no IHDR chunk" % path)
    width, height, bit_depth, color_type, _compression, _filt, interlace = ihdr
    if interlace != 0:
        raise NotImplementedError(
            "interlaced (Adam7) PNG - pixel decode not implemented, IHDR "
            "only: width=%d height=%d bit_depth=%d color_type=%d"
            % (width, height, bit_depth, color_type))
    if bit_depth not in (8, 16):
        raise NotImplementedError(
            "bit depth %d - pixel decode not implemented, IHDR only: "
            "width=%d height=%d color_type=%d"
            % (bit_depth, width, height, color_type))
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise NotImplementedError(
            "colour type %d (palette or unrecognised) - pixel decode not "
            "implemented, IHDR only: width=%d height=%d bit_depth=%d"
            % (color_type, width, height, bit_depth))
    raw = zlib.decompress(bytes(idat))
    bpp = channels * (bit_depth // 8)
    row_bytes = width * bpp
    stride = row_bytes + 1
    rows = []
    prev = bytes(row_bytes)
    for r in range(height):
        start = r * stride
        ftype = raw[start]
        line = bytearray(raw[start + 1:start + 1 + row_bytes])
        for i in range(row_bytes):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if ftype == 1:
                line[i] = (line[i] + a) & 0xFF
            elif ftype == 2:
                line[i] = (line[i] + b) & 0xFF
            elif ftype == 3:
                line[i] = (line[i] + (a + b) // 2) & 0xFF
            elif ftype == 4:
                pa = abs(b - c)
                pb = abs(a - c)
                pc = abs(a + b - 2 * c)
                if pa <= pb and pa <= pc:
                    pr = a
                elif pb <= pc:
                    pr = b
                else:
                    pr = c
                line[i] = (line[i] + pr) & 0xFF
            # ftype == 0 (None): nothing to add.
        prev = bytes(line)
        rows.append(prev)
    return {"width": width, "height": height, "bit_depth": bit_depth,
            "color_type": color_type, "channels": channels, "bpp": bpp,
            "rows": rows}


def _pixels(png):
    channels, bit_depth = png["channels"], png["bit_depth"]
    out = []
    for row in png["rows"]:
        if bit_depth == 8:
            for i in range(0, len(row), channels):
                out.append(tuple(row[i:i + channels]))
        else:
            vals = struct.unpack(">%dH" % (len(row) // 2), row)
            for i in range(0, len(vals), channels):
                out.append(tuple(vals[i:i + channels]))
    return out


def _uniformity(png):
    px = _pixels(png)
    distinct = set(px)
    return {"pixel_count": len(px), "distinct_values": len(distinct),
            "non_uniform": len(distinct) > 1}


def _write_tiny_png(path, size=8):
    """A small real gradient PNG, written without Pillow (same technique as
    evals/tool_gaps_live.py:write_png). Used as P4/P5's `file` node source
    image - a real file on disk, independent of whether P1/P2's own bakes
    succeeded.
    """
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filter type: None
        for x in range(size):
            v = (x * 255) // max(size - 1, 1)
            raw += bytes((v, v, v))

    def chunk(tag, body):
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)


# --------------------------------------------------------------------------
# Scene-building helpers
# --------------------------------------------------------------------------
def _fresh_scene(cmds):
    cmds.file(new=True, force=True)


def _plane_with_uvs(cmds, name):
    plane, _node = cmds.polyPlane(name=name, w=2, h=2, sx=4, sy=4)
    return plane


def _cube_with_default_uvs(cmds, name):
    cube, _node = cmds.polyCube(name=name, w=2, h=2, d=2)
    return cube


def _shape_of(cmds, transform):
    shapes = cmds.listRelatives(transform, shapes=True, fullPath=True) or []
    if not shapes:
        raise RuntimeError("%s has no shape" % transform)
    return shapes[0]


def _noise_material(cmds, transform, name_prefix):
    """standardSurface with a `noise` texture wired into baseColor - the
    same node type maya_plugin's noise_bump recipe uses, connected to the
    slot P2 needs to test."""
    shape = _shape_of(cmds, transform)
    shader = cmds.shadingNode("standardSurface", asShader=True,
                              name=name_prefix + "_shd")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                   name=name_prefix + "SG")
    cmds.connectAttr(shader + ".outColor", sg + ".surfaceShader", force=True)
    cmds.sets(shape, edit=True, forceElement=sg)
    noise = cmds.shadingNode("noise", asTexture=True,
                             name=name_prefix + "_noise")
    cmds.setAttr(noise + ".frequency", 4.0)
    cmds.connectAttr(noise + ".outColor", shader + ".baseColor", force=True)
    return shader, noise, shape


def _last_line(exc_text):
    return (exc_text or "").strip().splitlines()[-1] if exc_text else "unknown error"


# --------------------------------------------------------------------------
# P1
# --------------------------------------------------------------------------
def probe_p1(cmds):
    """P1: does convertSolidTx run under maya.standalone at all."""
    _fresh_scene(cmds)
    plane = _plane_with_uvs(cmds, "p1_plane")
    _shader, noise, _shape = _noise_material(cmds, plane, "p1")
    path = os.path.join(OUT_DIR, "p1_bake.png").replace("\\", "/")
    result = {"path": path, "ran": False, "returned": None,
              "error": None, "size": None}
    try:
        result["returned"] = cmds.convertSolidTx(
            noise + ".outColor", plane, resolutionX=32, resolutionY=32,
            fileImageName=path, fileFormat="png", alpha=False)
        result["ran"] = True
    except Exception:
        result["error"] = traceback.format_exc()
    if os.path.isfile(path):
        result["size"] = os.path.getsize(path)
    if result["ran"] and result["size"]:
        verdict = "RAN - wrote %d bytes to %s" % (result["size"], path)
    elif result["ran"]:
        verdict = "RAN (returned %r) but no file appeared at %s" % (
            result["returned"], path)
    else:
        verdict = "FAILED: %s" % _last_line(result["error"])
    result["verdict"] = verdict
    print("P1 convertSolidTx headless: %s" % verdict)
    if result["error"]:
        print(result["error"])
    return result


# --------------------------------------------------------------------------
# P2 - the GO/NO-GO
# --------------------------------------------------------------------------
def _bake_case(cmds, label, build_fn, delete_uvs=False):
    _fresh_scene(cmds)
    transform = build_fn(cmds, label)
    if delete_uvs:
        shape = _shape_of(cmds, transform)
        cmds.polyMapDel(shape + ".f[*]")
        # only worth anything if the mesh really has no UVs left
        remaining = cmds.polyEditUV(shape + ".map[*]", query=True) or []
        if remaining:
            raise RuntimeError(
                "polyMapDel left %d UV coordinate(s) - the no-UV setup "
                "itself failed" % len(remaining))
    _shader, noise, _shape = _noise_material(cmds, transform, label)
    path = os.path.join(OUT_DIR, "p2_%s.png" % label).replace("\\", "/")
    entry = {"path": path, "error": None, "png": None, "png_error": None,
              "size": None}
    try:
        cmds.convertSolidTx(noise + ".outColor", transform,
                            resolutionX=32, resolutionY=32,
                            fileImageName=path, fileFormat="png",
                            alpha=False)
    except Exception:
        entry["error"] = traceback.format_exc()
    if os.path.isfile(path):
        entry["size"] = os.path.getsize(path)
        try:
            png = _read_png(path)
            uni = _uniformity(png)
            entry["png"] = {"width": png["width"], "height": png["height"],
                            "bit_depth": png["bit_depth"],
                            "color_type": png["color_type"]}
            entry["png"].update(uni)
        except Exception:
            entry["png_error"] = traceback.format_exc()
    return entry, transform, noise


def _fidelity_verdict(entry):
    if entry.get("png"):
        if entry["png"]["non_uniform"]:
            return "USABLE - non-uniform bake (%d distinct value(s) of %d px)" % (
                entry["png"]["distinct_values"], entry["png"]["pixel_count"])
        return "BAKED BUT UNIFORM (flat, %d px) - not usable" % (
            entry["png"]["pixel_count"])
    if entry.get("size") is not None:
        return ("baked to %d bytes but the pixel check was not possible "
                "(%s) - report file size only" % (
                    entry["size"], _last_line(entry.get("png_error"))))
    if entry.get("error"):
        return "FAILED: %s" % _last_line(entry["error"])
    return "no file written, no exception raised - silent no-op"


def probe_p2(cmds):
    """P2: THE GO/NO-GO. Bakes across three UV conditions, plus a
    mesh-independence check that picks the phase-2 design arm."""
    cases = {}

    entry_a, _t, _n = _bake_case(cmds, "a_clean_uv_plane", _plane_with_uvs)
    entry_a["verdict"] = _fidelity_verdict(entry_a)
    cases["a_clean_uv_plane"] = entry_a
    print("P2a (clean 0..1 UVs, plane): %s" % entry_a["verdict"])

    entry_b, _t, _n = _bake_case(cmds, "b_box_projection_cube",
                                  _cube_with_default_uvs)
    entry_b["verdict"] = _fidelity_verdict(entry_b)
    cases["b_box_projection_cube"] = entry_b
    print("P2b (box-projection UVs, cube - decides the GO/NO-GO): %s"
          % entry_b["verdict"])

    try:
        entry_c, _t, _n = _bake_case(cmds, "c_no_uvs",
                                      _cube_with_default_uvs,
                                      delete_uvs=True)
        if entry_c.get("error"):
            entry_c["verdict"] = "REFUSED (exception) - %s" % _last_line(
                entry_c["error"])
        elif entry_c.get("png"):
            entry_c["verdict"] = (
                "silently produced a %s image (%d px) rather than raising"
                % ("non-uniform" if entry_c["png"]["non_uniform"]
                   else "uniform/flat", entry_c["png"]["pixel_count"]))
        elif entry_c.get("size") is not None:
            entry_c["verdict"] = (
                "silently wrote %d bytes rather than raising (pixel check "
                "not possible: %s)" % (entry_c["size"],
                                       _last_line(entry_c.get("png_error"))))
        else:
            entry_c["verdict"] = ("no file written, no exception raised - "
                                  "silent no-op")
    except Exception:
        entry_c = {"error": traceback.format_exc()}
        entry_c["verdict"] = "the no-UV setup itself failed: %s" % _last_line(
            entry_c["error"])
    cases["c_no_uvs"] = entry_c
    print("P2c (UVs deleted - exact failure mode for phase 2's refusal "
          "message): %s" % entry_c["verdict"])

    # (d) TRANSFORM independence: same clean UVs, same noise INSTANCE, same
    # local vertex geometry, two meshes differing only in the TRANSFORM
    # NODE (world position/scale). Identical bytes here would only prove
    # the bake ignores the transform node - it says nothing yet about
    # whether it reads the mesh's actual (local) 3D surface, since a
    # duplicate's local vertex coordinates are identical to the source's.
    d_entry = {"error": None, "identical_bytes": None}
    try:
        _fresh_scene(cmds)
        plane1 = _plane_with_uvs(cmds, "p2d_plane1")
        _shader, noise, _shape1 = _noise_material(cmds, plane1, "p2d")
        plane2 = cmds.duplicate(plane1, name="p2d_plane2")[0]
        cmds.move(37.0, 12.0, -8.0, plane2, relative=True)
        cmds.setAttr(plane2 + ".scaleX", 3.0)
        cmds.setAttr(plane2 + ".scaleZ", 3.0)
        path1 = os.path.join(OUT_DIR, "p2d_plane1.png").replace("\\", "/")
        path2 = os.path.join(OUT_DIR, "p2d_plane2.png").replace("\\", "/")
        cmds.convertSolidTx(noise + ".outColor", plane1, resolutionX=32,
                            resolutionY=32, fileImageName=path1,
                            fileFormat="png", alpha=False)
        cmds.convertSolidTx(noise + ".outColor", plane2, resolutionX=32,
                            resolutionY=32, fileImageName=path2,
                            fileFormat="png", alpha=False)
        png1, png2 = _read_png(path1), _read_png(path2)
        identical = png1["rows"] == png2["rows"]
        d_entry["identical_bytes"] = identical
        if identical:
            d_entry["verdict"] = (
                "TRANSFORM-INDEPENDENT - identical bytes despite a "
                "different world position/scale on the transform node "
                "(inconclusive alone about LOCAL geometry - see P2e)")
        else:
            d_entry["verdict"] = (
                "TRANSFORM-DEPENDENT - same UVs and local geometry, "
                "different world position/scale produced different bytes")
    except Exception:
        d_entry["error"] = traceback.format_exc()
        d_entry["verdict"] = "could not run: %s" % _last_line(d_entry["error"])
    cases["d_transform_independence"] = d_entry
    print("P2d (transform independence): %s" % d_entry["verdict"])

    # (e) LOCAL-GEOMETRY dependence: same UVs, same noise INSTANCE, same
    # transform, but the duplicate's actual VERTEX POSITIONS are pushed out
    # of plane. This is what (d) could not isolate: does the bake read the
    # mesh's real local 3D surface at all, or purely its UV parameter
    # space? Identical bytes -> confirms pure 2D/UV-space sampling, so a
    # material shared across DIFFERENTLY-SHAPED meshes with matching UVs
    # bakes identically and could be reused. Different bytes -> the bake
    # reads local 3D geometry, so even same-UV meshes of different actual
    # shape need their own bake - this is the one that actually decides
    # the design arm, not (d).
    e_entry = {"error": None, "identical_bytes": None}
    try:
        _fresh_scene(cmds)
        plane1 = _plane_with_uvs(cmds, "p2e_plane1")
        _shader, noise, _shape1 = _noise_material(cmds, plane1, "p2e")
        plane2 = cmds.duplicate(plane1, name="p2e_plane2")[0]
        shape2 = _shape_of(cmds, plane2)
        num_verts = cmds.polyEvaluate(shape2, vertex=True)
        for i in range(num_verts):
            cmds.move(0, 0, 1.5 * (1 if i % 2 == 0 else -1),
                     "%s.vtx[%d]" % (shape2, i), relative=True,
                     objectSpace=True)
        path1 = os.path.join(OUT_DIR, "p2e_plane1.png").replace("\\", "/")
        path2 = os.path.join(OUT_DIR, "p2e_plane2.png").replace("\\", "/")
        cmds.convertSolidTx(noise + ".outColor", plane1, resolutionX=32,
                            resolutionY=32, fileImageName=path1,
                            fileFormat="png", alpha=False)
        cmds.convertSolidTx(noise + ".outColor", plane2, resolutionX=32,
                            resolutionY=32, fileImageName=path2,
                            fileFormat="png", alpha=False)
        png1, png2 = _read_png(path1), _read_png(path2)
        identical = png1["rows"] == png2["rows"]
        e_entry["identical_bytes"] = identical
        if identical:
            e_entry["verdict"] = (
                "MESH-INDEPENDENT (pure 2D/UV-space sampling) - identical "
                "bytes even after deforming the duplicate's vertices out "
                "of plane -> a material shared across differently-shaped "
                "meshes with matching UVs can bake ONCE")
        else:
            e_entry["verdict"] = (
                "MESH-DEPENDENT (reads local 3D surface geometry) - "
                "deforming the duplicate's vertices changed the bake even "
                "though the UVs and transform were unchanged -> phase 2 "
                "must refuse shared materials, one bake per mesh")
    except Exception:
        e_entry["error"] = traceback.format_exc()
        e_entry["verdict"] = "could not run: %s" % _last_line(e_entry["error"])
    cases["e_local_geometry_dependence"] = e_entry
    print("P2e (local-geometry dependence - selects the phase-2 design "
          "arm): %s" % e_entry["verdict"])

    go = bool(entry_b.get("png") and entry_b["png"]["non_uniform"])
    cases["go_no_go"] = "GO" if go else "NO-GO"
    print("P2 GO/NO-GO for phase 2: %s (decided by case b, box-projection "
          "UVs)" % cases["go_no_go"])
    return cases


# --------------------------------------------------------------------------
# P3
# --------------------------------------------------------------------------
def probe_p3(cmds, p2_cases):
    """P3: the written PNG's IHDR, plus bump-as-height viability (the
    pre-bump scalar noise.outColorR)."""
    result = {}
    source = None
    for key in ("b_box_projection_cube", "a_clean_uv_plane"):
        entry = (p2_cases or {}).get(key) or {}
        if entry.get("png"):
            source = (key, entry["png"])
            break
    if source:
        key, png = source
        color_name = _COLOR_TYPE_NAMES.get(png["color_type"], "unknown")
        result["ihdr_source"] = key
        result["bit_depth"] = png["bit_depth"]
        result["color_type"] = png["color_type"]
        result["ihdr_verdict"] = (
            "bit depth %d, colour type %d (%s) - measured from P2's %r bake"
            % (png["bit_depth"], png["color_type"], color_name, key))
    else:
        result["ihdr_verdict"] = ("no readable P2 PNG available to inspect "
                                  "- IHDR could not be measured")
    print("P3 PNG format: %s" % result["ihdr_verdict"])

    _fresh_scene(cmds)
    plane = _plane_with_uvs(cmds, "p3_plane")
    _shader, noise, _shape = _noise_material(cmds, plane, "p3")
    scalar_path = os.path.join(OUT_DIR, "p3_scalar.png").replace("\\", "/")
    scalar = {"method": "direct noise.outColorR", "error": None,
              "fallback_error": None, "png": None, "png_error": None}
    try:
        cmds.convertSolidTx(noise + ".outColorR", plane, resolutionX=32,
                            resolutionY=32, fileImageName=scalar_path,
                            fileFormat="png", alpha=False)
    except Exception:
        scalar["error"] = traceback.format_exc()
        scalar["method"] = ("direct outColorR FAILED (%s); tried routing "
                            "the scalar through a connected attribute "
                            "instead" % _last_line(scalar["error"]))
        try:
            fallback_shader = cmds.shadingNode(
                "lambert", asShader=True, name="p3_fallback_shd")
            cmds.connectAttr(noise + ".outColorR",
                             fallback_shader + ".translucence", force=True)
            cmds.convertSolidTx(fallback_shader + ".translucence", plane,
                                resolutionX=32, resolutionY=32,
                                fileImageName=scalar_path, fileFormat="png",
                                alpha=False)
        except Exception:
            scalar["fallback_error"] = traceback.format_exc()
    if os.path.isfile(scalar_path):
        try:
            png = _read_png(scalar_path)
            scalar["png"] = _uniformity(png)
        except Exception:
            scalar["png_error"] = traceback.format_exc()
    result["scalar_bake"] = scalar
    if scalar.get("png") and scalar["png"]["non_uniform"]:
        verdict = "USABLE (%s) - non-uniform scalar bake" % scalar["method"]
    elif scalar.get("png"):
        verdict = ("bakes but flat/uniform (%s) - not usable as a height "
                   "map" % scalar["method"])
    elif os.path.isfile(scalar_path):
        verdict = ("baked but the pixel check was not possible (%s)"
                  % _last_line(scalar.get("png_error")))
    else:
        verdict = "FAILED entirely: %s" % _last_line(
            scalar.get("fallback_error") or scalar.get("error"))
    result["verdict"] = verdict
    print("P3 scalar/bump-as-height (noise.outColorR): %s" % verdict)
    return result


# --------------------------------------------------------------------------
# P4
# --------------------------------------------------------------------------
def probe_p4(cmds, export_mod, fbxbytes_mod):
    """P4: does file -> bump2d(bumpInterp=0) -> normalCamera survive
    export.export_fbx (image basename present in the FBX bytes)?"""
    _fresh_scene(cmds)
    plane = _plane_with_uvs(cmds, "p4_plane")
    shape = _shape_of(cmds, plane)
    shader = cmds.shadingNode("standardSurface", asShader=True, name="p4_shd")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                   name="p4SG")
    cmds.connectAttr(shader + ".outColor", sg + ".surfaceShader", force=True)
    cmds.sets(shape, edit=True, forceElement=sg)

    image_path = os.path.join(OUT_DIR, "p4_height.png").replace("\\", "/")
    _write_tiny_png(image_path)

    file_node = cmds.shadingNode("file", asTexture=True, name="p4_file")
    cmds.setAttr(file_node + ".fileTextureName", image_path, type="string")
    bump = cmds.shadingNode("bump2d", asUtility=True, name="p4_bump")
    cmds.setAttr(bump + ".bumpInterp", 0)
    cmds.connectAttr(file_node + ".outAlpha", bump + ".bumpValue", force=True)
    cmds.connectAttr(bump + ".outNormal", shader + ".normalCamera",
                     force=True)

    fbx_path = os.path.join(OUT_DIR, "p4_export.fbx").replace("\\", "/")
    result = {"image_path": image_path, "fbx_path": fbx_path, "error": None}
    try:
        export_mod.export_fbx({"path": fbx_path, "metres_per_unit": 1.0,
                              "nodes": [plane]})
        facts = fbxbytes_mod.read_fbx(fbx_path)
        tf = fbxbytes_mod.texture_facts(facts)
        basename = os.path.basename(image_path)
        found = any(row["basename"] == basename
                    for row in tf["textures"] + tf["videos"])
        result["texture_facts"] = tf
        result["basename"] = basename
        result["found"] = found
        if found:
            result["verdict"] = ("SURVIVES - basename %r present in the "
                                 "exported bytes (texture_records=%d, "
                                 "video_records=%d)" % (
                                     basename, tf["texture_records"],
                                     tf["video_records"]))
        else:
            result["verdict"] = ("LOST - basename %r NOT found in the "
                                 "exported bytes (texture_records=%d, "
                                 "video_records=%d)" % (
                                     basename, tf["texture_records"],
                                     tf["video_records"]))
    except Exception:
        result["error"] = traceback.format_exc()
        result["verdict"] = "FAILED: %s" % _last_line(result["error"])
    print("P4 height-path survival: %s" % result["verdict"])
    if result["error"]:
        print(result["error"])
    return result


# --------------------------------------------------------------------------
# P5
# --------------------------------------------------------------------------
def probe_p5(cmds, export_mod, fbxbytes_mod):
    """P5: what does the FBX carry for a `file` node whose image is missing
    from disk?"""
    _fresh_scene(cmds)
    plane = _plane_with_uvs(cmds, "p5_plane")
    shape = _shape_of(cmds, plane)
    shader = cmds.shadingNode("standardSurface", asShader=True, name="p5_shd")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                   name="p5SG")
    cmds.connectAttr(shader + ".outColor", sg + ".surfaceShader", force=True)
    cmds.sets(shape, edit=True, forceElement=sg)

    missing_path = os.path.join(
        OUT_DIR, "does_not_exist_714", "missing_texture.png").replace(
        "\\", "/")
    file_node = cmds.shadingNode("file", asTexture=True, name="p5_file")
    cmds.setAttr(file_node + ".fileTextureName", missing_path, type="string")
    cmds.connectAttr(file_node + ".outColor", shader + ".baseColor",
                     force=True)

    fbx_path = os.path.join(OUT_DIR, "p5_export.fbx").replace("\\", "/")
    result = {"missing_path": missing_path, "fbx_path": fbx_path,
              "error": None}
    try:
        export_mod.export_fbx({"path": fbx_path, "metres_per_unit": 1.0,
                              "nodes": [plane]})
        facts = fbxbytes_mod.read_fbx(fbx_path)
        tf = fbxbytes_mod.texture_facts(facts)
        result["texture_facts"] = tf
        basename = os.path.basename(missing_path)
        rows = [r for r in (tf["textures"] + tf["videos"])
                if r["basename"] == basename]
        result["rows"] = rows
        if rows:
            result["verdict"] = (
                "Texture/Video record PRESENT (basename %r, %d record(s)) "
                "even though the file is missing from disk - export does "
                "not validate image existence" % (basename, len(rows)))
        else:
            result["verdict"] = (
                "NO record for %r (texture_records=%d, video_records=%d) - "
                "at the byte level a missing image is indistinguishable "
                "from a dropped procedural map" % (
                    basename, tf["texture_records"], tf["video_records"]))
    except Exception:
        result["error"] = traceback.format_exc()
        result["verdict"] = "FAILED: %s" % _last_line(result["error"])
    print("P5 missing image: %s" % result["verdict"])
    if result["error"]:
        print(result["error"])
    return result


def _safe(fn, label):
    """Second layer of failure-tolerance: a probe is expected to catch its
    own exceptions, but if one still escapes (a bug in the probe itself,
    not the candidate it measures), this stops it from taking the rest of
    the script down."""
    try:
        return fn()
    except Exception:
        print("%s: UNCAUGHT ERROR - the probe itself crashed" % label)
        traceback.print_exc()
        return None


def main():
    maya.standalone.initialize(name="python")
    import maya.cmds as cmds  # noqa: PLC0415 - only importable after init

    from maya_plugin.handlers import export, fbxbytes

    os.makedirs(OUT_DIR, exist_ok=True)

    print("=" * 78)
    print("#714 phase 1 Task 8 - the five bake probes")
    print("=" * 78)

    p1 = _safe(lambda: probe_p1(cmds), "P1")
    p2 = _safe(lambda: probe_p2(cmds), "P2")
    p3 = _safe(lambda: probe_p3(cmds, p2 or {}), "P3")
    p4 = _safe(lambda: probe_p4(cmds, export, fbxbytes), "P4")
    p5 = _safe(lambda: probe_p5(cmds, export, fbxbytes), "P5")

    print("\n" + "=" * 78)
    print("FINAL TABLE")
    print("=" * 78)
    rows = [
        ("P1 convertSolidTx headless",
         (p1 or {}).get("verdict", "COULD NOT RUN - see UNCAUGHT ERROR above")),
        ("P2a clean 0..1 UVs",
         (p2 or {}).get("a_clean_uv_plane", {}).get(
             "verdict", "COULD NOT RUN")),
        ("P2b box-projection UVs (GO/NO-GO)",
         (p2 or {}).get("b_box_projection_cube", {}).get(
             "verdict", "COULD NOT RUN")),
        ("P2c UV-less mesh (failure mode)",
         (p2 or {}).get("c_no_uvs", {}).get("verdict", "COULD NOT RUN")),
        ("P2d transform independence",
         (p2 or {}).get("d_transform_independence", {}).get(
             "verdict", "COULD NOT RUN")),
        ("P2e local-geometry dependence (design arm)",
         (p2 or {}).get("e_local_geometry_dependence", {}).get(
             "verdict", "COULD NOT RUN")),
        ("P3 PNG format",
         (p3 or {}).get("ihdr_verdict", "COULD NOT RUN")),
        ("P3 scalar/bump-as-height",
         (p3 or {}).get("verdict", "COULD NOT RUN")),
        ("P4 height-path survives export",
         (p4 or {}).get("verdict", "COULD NOT RUN")),
        ("P5 missing image bytes",
         (p5 or {}).get("verdict", "COULD NOT RUN")),
    ]
    width = max(len(r[0]) for r in rows)
    for label, verdict in rows:
        print("%-*s  %s" % (width, label, verdict))

    go = bool(p2 and p2.get("go_no_go") == "GO")
    print("\nGO/NO-GO for phase 2: %s" % ("GO" if go else "NO-GO"))
    e_entry = (p2 or {}).get("e_local_geometry_dependence") or {}
    if e_entry.get("identical_bytes") is not None:
        if e_entry["identical_bytes"]:
            arm = "shared materials bake ONCE (mesh-independent sampling)"
        else:
            arm = ("phase 2 MUST REFUSE shared materials - one bake per "
                  "mesh (mesh-dependent sampling)")
        print("Design arm selected: %s" % arm)
    else:
        print("Design arm: could not be determined - see P2e's error above")

    try:
        maya.standalone.uninitialize()
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
