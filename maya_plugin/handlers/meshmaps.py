"""maya_bake_mesh_maps: bake AO / curvature / world-normal from geometry.

#770. The golem delivery measured the weakness this cures: its joins fail
under SSAO - gasket collars show no contact darkening - because nothing in
the shipped texture knows where geometry meets geometry. This tool bakes
maps that COME FROM the geometry (Arnold render-to-texture through the
mesh's UVs) and, on request, composites the AO into the material's colour
map so the contact shadow ships in the texture itself.

How it differs from texbake (#714): texbake flattens procedural SHADER
networks via convertSolidTx; this bakes GEOMETRY-derived signals, which
needs a renderer. The two compose - the AO composite writes a plain
file->slot wiring (texbake's measured shapes), so exports stay honest.

Probe-measured facts this module is built on (evals/meshmaps_probe_770*):
- arnoldRenderToTexture's `-shader` flag bakes through a NEVER-ASSIGNED
  shader, so the bake phase mutates nothing (Q2).
- A UV-less mesh does not fail at bake time: the command returns normally
  and writes a CORRUPT EXR that only fails at read (Q5). Refuse upfront.
- Output is EXR only; `extension="png"` is silently ignored - unknown
  kwargs do not raise (S2). Convert via MImage, whose EXR->PNG path is
  LINEAR (0.5 lands on 127/128, T1).
- Arnold names the output file itself and renames on short-name collisions
  (Q4) - so each bake runs one mesh into a private empty folder and takes
  the single EXR that appears, and requested-mesh short-name collisions
  refuse rather than guess the rule.
- A flat map can be HONEST (concave curvature on convex-only geometry is
  all-zero, Q3; a lone convex mesh's AO is all-white) - flat warns here,
  never refuses.
- extend_edges pads shells but floods alpha to 1.0 over the whole image
  (T3) - so masked composites (a shared atlas worn by several requested
  meshes) bake UNPADDED to keep alpha usable as a "was baked" mask.
"""

from __future__ import annotations

import glob as _glob
import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..dispatcher import HandlerError, require_known_keys
from . import material as material_mod
from . import naming, pbr, pngprobe, pngwrite, session, texbake, texclaim

MAPS = ("ao", "curvature", "world_normal")
CURVATURE_OUTPUTS = ("convex", "concave", "both")
RESOLUTIONS = texbake.RESOLUTIONS
DEFAULT_RESOLUTION = texbake.DEFAULT_RESOLUTION
DEFAULT_CURVATURE_RADIUS = 0.1

BAKE_MESH_MAPS_KEYS = ("meshes", "out_dir", "maps", "resolution", "apply_ao",
                       "curvature_radius", "curvature_output")
# The #764 lesson: an unread param must refuse, and the synonyms an agent
# actually reaches for share no letters with the real key often enough that
# similarity matching cannot find them.
BAKE_MESH_MAPS_SYNONYMS = {
    "mesh": "meshes", "map": "maps", "kinds": "maps", "channels": "maps",
    "size": "resolution", "apply": "apply_ao", "bake_ao": "apply_ao",
    "output_dir": "out_dir", "folder": "out_dir", "directory": "out_dir",
}


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _ensure_mtoa(cmds) -> None:
    """Arnold is the bake engine; without mtoa there is no honest fallback."""
    try:
        if cmds.pluginInfo("mtoa", query=True, loaded=True):
            return
    except Exception:  # noqa: BLE001 - an unanswerable query falls to load
        pass
    try:
        cmds.loadPlugin("mtoa", quiet=True)
    except Exception as exc:  # noqa: BLE001 - reported, never guessed around
        raise HandlerError(
            "the Arnold plugin (mtoa) could not be loaded: %s" % exc,
            hint="bake_mesh_maps renders its maps with arnoldRenderToTexture; "
                 "without Arnold there is nothing honest to fall back to")


def validate(params: Dict[str, Any], cmds) -> Dict[str, Any]:
    """Everything checkable before a single node is touched."""
    require_known_keys(params, BAKE_MESH_MAPS_KEYS, "bake_mesh_maps",
                       BAKE_MESH_MAPS_SYNONYMS)

    raw = params.get("meshes")
    _hint = ("pass the mesh(es) to bake maps for; maya_get_scene_graph "
             "lists what the scene contains")
    if isinstance(raw, str):
        names = [raw]
    elif isinstance(raw, (list, tuple)):
        names = list(raw)
    elif raw is None:
        names = []
    else:
        raise HandlerError("missing required param 'meshes'", hint=_hint)
    if not names or not all(isinstance(n, str) and n.strip() for n in names):
        raise HandlerError("missing required param 'meshes'", hint=_hint)

    meshes: List[Tuple[str, str]] = []
    for name in names:
        transform, shape = naming.require_mesh(cmds, name)
        if (transform, shape) not in meshes:
            meshes.append((transform, shape))

    for transform, shape in meshes:
        if _uv_count(cmds, shape) == 0:
            raise HandlerError(
                "%s has no UVs - a bake renders through UV space, and Maya "
                "does NOT refuse this: arnoldRenderToTexture returns "
                "normally and writes a CORRUPT file that only fails later, "
                "at read (MEASURED, #770 probe Q5)" % shape,
                hint="maya_uv_atlas creates UVs; bake after that")

    shorts: Dict[str, str] = {}
    for transform, _shape in meshes:
        short = transform.split("|")[-1]
        if short in shorts:
            raise HandlerError(
                "%s and %s share the short name %r - baked files are named "
                "by it, and Arnold renames colliding outputs by a rule this "
                "tool refuses to guess (MEASURED, #770 probe Q4)"
                % (shorts[short], transform, short),
                hint="maya_rename one of them, then bake")
        shorts[short] = transform

    out_dir = params.get("out_dir")
    if not isinstance(out_dir, str) or not out_dir.strip():
        raise HandlerError(
            "missing required param 'out_dir'",
            hint="an absolute directory the baked maps are written to - "
                 "there is no default, because a guessed location is how "
                 "bake files get lost from a delivery")
    if not os.path.isabs(out_dir):
        raise HandlerError(
            "out_dir %r must be absolute" % out_dir,
            hint="a relative path resolves against Maya's working directory, "
                 "which is not where you think it is")
    if not os.path.isdir(out_dir):
        raise HandlerError(
            "out_dir %r does not exist" % out_dir,
            hint="this tool does not make directories it was not asked to "
                 "make (the export_fbx rule)")

    maps = params.get("maps")
    if maps is None:
        maps = list(MAPS)
    if (not isinstance(maps, list) or not maps
            or not all(isinstance(m, str) for m in maps)):
        raise HandlerError("maps must be a non-empty list of map names",
                           hint="valid maps: %s" % ", ".join(MAPS))
    unknown = [m for m in maps if m not in MAPS]
    if unknown:
        raise HandlerError(
            "unknown map(s): %s" % ", ".join(unknown),
            hint="valid maps: %s. A tangent-space high-to-low normal bake "
                 "is a different capability this tool does not have"
                 % ", ".join(MAPS))
    maps = list(dict.fromkeys(maps))

    resolution = params.get("resolution", DEFAULT_RESOLUTION)
    if (isinstance(resolution, bool) or not isinstance(resolution, int)
            or resolution not in RESOLUTIONS):
        raise HandlerError(
            "resolution must be one of %s"
            % ", ".join(str(r) for r in RESOLUTIONS),
            hint="a bake is square; these are the sizes this tool writes")

    apply_ao = params.get("apply_ao", False)
    if not isinstance(apply_ao, bool):
        raise HandlerError("apply_ao must be true or false",
                           hint="true composites the baked AO into each "
                                "material's colour map (a persistent scene "
                                "edit); false only writes the map files")
    if apply_ao and "ao" not in maps:
        raise HandlerError(
            "apply_ao=true but 'ao' is not in maps %r" % (maps,),
            hint="the composite needs the AO bake; add 'ao' to maps or "
                 "drop apply_ao")

    radius = params.get("curvature_radius", DEFAULT_CURVATURE_RADIUS)
    if (isinstance(radius, bool) or not isinstance(radius, (int, float))
            or radius <= 0):
        raise HandlerError("curvature_radius must be a positive number "
                           "(scene units)",
                           hint="the sampling radius around each point; "
                                "0.1 suits metre-scale assets")

    curvature_output = params.get("curvature_output", "convex")
    if curvature_output not in CURVATURE_OUTPUTS:
        raise HandlerError(
            "curvature_output must be one of %s"
            % ", ".join(CURVATURE_OUTPUTS),
            hint="convex is the edge-wear mask; concave marks crevices and "
                 "is HONESTLY all-black on convex-only geometry (measured)")

    return {"meshes": meshes, "out_dir": out_dir, "maps": maps,
            "resolution": resolution, "apply_ao": apply_ao,
            "curvature_radius": float(radius),
            "curvature_output": curvature_output}


def _uv_count(cmds, shape: str) -> int:
    """texbake's honest UV count: 0 means 'no UVs', an exception means a
    different problem and must not be laundered into that diagnosis."""
    try:
        return int(cmds.polyEvaluate(shape, uvcoord=True) or 0)
    except Exception as exc:  # noqa: BLE001 - re-raised with its own message
        raise HandlerError(
            "could not determine the UV count for %s: %s" % (shape, exc),
            hint="this is not the no-UVs refusal - polyEvaluate itself "
                 "failed; inspect %s in Maya directly" % shape)


# --------------------------------------------------------------------------
# apply_ao planning - every refusal fires BEFORE any bake runs
# --------------------------------------------------------------------------


def plan_apply(cmds, meshes: List[Tuple[str, str]]) -> Tuple[
        List[Dict[str, Any]], List[str]]:
    """One composite job per material worn by the requested meshes.

    Pre-mutation and pre-bake: a refusal here costs nothing. The colour
    slot must be something this tool can composite honestly - a plain
    value, or a single readable PNG file. Anything procedural refuses
    (texbake flattens those first), and a material worn by a mesh OUTSIDE
    the request refuses because the rewire would change that mesh's look
    with an AO it never contributed to.
    """
    warnings: List[str] = []
    shapes = [shape for _t, shape in meshes]
    by_material: Dict[str, Dict[str, Any]] = {}
    for transform, shape in meshes:
        sgs = cmds.listSets(object=shape, type=1) or []
        if len(sgs) != 1:
            raise HandlerError(
                "%s wears %d shading groups - per-face material assignment "
                "has no single colour slot to composite into"
                % (shape, len(sgs)),
                hint="apply_ao composites one AO into one material per mesh; "
                     "bake without apply_ao and composite by hand, or "
                     "consolidate the assignment first")
        sg = sgs[0]
        shaders = cmds.listConnections(sg + ".surfaceShader",
                                       source=True) or []
        if not shaders:
            raise HandlerError(
                "%s's shading group %s has no surface shader" % (shape, sg),
                hint="assign a material (maya_assign_material or "
                     "maya_assign_pbr) before compositing AO into it")
        shader = shaders[0]
        entry = by_material.setdefault(shader, {"sg": sg, "wearers": []})
        entry["wearers"].append((transform, shape))

    claims = texclaim.material_claims(cmds, shapes)
    jobs: List[Dict[str, Any]] = []
    for shader, entry in by_material.items():
        shader_type = cmds.nodeType(shader)
        slots = material_mod.SHADER_SLOTS.get(shader_type)
        attr = (slots or {}).get("color")
        if attr is None:
            raise HandlerError(
                "%s is a %s, which this tool has no colour-slot mapping for"
                % (shader, shader_type),
                hint="supported shader types: %s"
                     % ", ".join(sorted(material_mod.SHADER_SLOTS)))

        outside = texbake._outside_wearers(cmds, entry["sg"], shapes)
        if outside:
            raise HandlerError(
                "%s is also worn by %s, which this call did not name - "
                "compositing AO into it would change that mesh's look with "
                "an occlusion it never contributed to"
                % (shader, ", ".join(sorted(outside))),
                hint="name every wearer in meshes, or give %s its own "
                     "material first" % ", ".join(sorted(outside)))

        claim = next((c for c in claims
                      if c["material"] == shader and c["attr"] == attr), None)
        if claim is None:
            value = cmds.getAttr("%s.%s" % (shader, attr))
            rgb = tuple(value[0]) if value else (1.0, 1.0, 1.0)
            base: Dict[str, Any] = {"kind": "value", "rgb": rgb}
        elif claim["classification"] == "file":
            if len(claim["terminals"]) != 1:
                raise HandlerError(
                    "%s.%s is driven by %d file terminals - this tool "
                    "composites into one image and will not guess which"
                    % (shader, attr, len(claim["terminals"])),
                    hint="simplify the network to a single file node first")
            terminal = claim["terminals"][0]
            path = terminal["file_path"]
            readable = None
            if path:
                probe = pngprobe.uniformity(path)
                readable = probe["non_uniform"] is not None
            if not readable:
                raise HandlerError(
                    "%s.%s reads %r, which cannot be read as a PNG this "
                    "tool understands - compositing into pixels it cannot "
                    "read would be a guess" % (shader, attr, path),
                    hint="the composite supports 8-bit PNG bases; convert "
                         "the map, or bake without apply_ao")
            base = {"kind": "file", "path": path,
                    "colorspace": terminal.get("colorspace") or "sRGB",
                    "file_node": terminal["node"]}
        else:
            raise HandlerError(
                "%s.%s is driven procedurally - compositing AO into a "
                "network this tool cannot read would be a guess"
                % (shader, attr),
                hint="maya_bake_textures flattens the network to a file "
                     "first; then apply_ao composites into that file")

        jobs.append({
            "material": shader, "sg": entry["sg"], "attr": attr,
            "wearers": list(entry["wearers"]),
            "masked": len(entry["wearers"]) > 1,
            "base": base,
            "basename": "%s_color_ao.png" % shader,
        })
    return jobs, warnings


# --------------------------------------------------------------------------
# the bake itself - isolated so tests drive the machinery without Maya
# --------------------------------------------------------------------------


def _arnold_bake(cmds, shape: str, folder: str, resolution: int,
                 shader: str, extend_edges: bool) -> None:
    """One mesh, one map, one private folder. Selection is the command's
    input channel (the positional form is unmeasured); the caller saves and
    restores it."""
    cmds.select(shape, replace=True)
    cmds.arnoldRenderToTexture(folder=folder, resolution=resolution,
                               shader=shader, extend_edges=extend_edges,
                               aa_samples=3)


def _find_oiiotool(cmds) -> str:
    """Arnold's own oiiotool, located from the loaded mtoa plugin.

    Why not MImage: MEASURED on the live gate's first run - in a GUI Maya
    session, MImage.writeToFile('png') zeroes the ALPHA CHANNEL of the
    converted EXR while the very same call on the very same file is
    correct under maya.standalone. Every headless test was green while
    the live bake read as "drew nothing". oiiotool is a subprocess with
    no session to inherit, and its output was measured BYTE-IDENTICAL to
    the correct standalone conversion (same pixel census, same linear
    transfer). No MImage fallback on purpose: falling back would
    resurrect the exact defect the gate caught.
    """
    try:
        plugin_path = cmds.pluginInfo("mtoa", query=True, path=True) or ""
    except Exception:  # noqa: BLE001 - reported below with the same hint
        plugin_path = ""
    if plugin_path:
        root = os.path.dirname(os.path.dirname(plugin_path))
        exe = os.path.join(root, "bin",
                           "oiiotool.exe" if os.name == "nt" else "oiiotool")
        if os.path.isfile(exe):
            return exe
    raise HandlerError(
        "oiiotool was not found next to the mtoa plugin (looked from %r)"
        % plugin_path,
        hint="the EXR->PNG conversion runs through Arnold's bundled "
             "oiiotool because Maya's MImage was measured to corrupt the "
             "alpha channel in GUI sessions; check the MtoA install's bin "
             "directory")


def _exr_to_png(cmds, src: str, dst: str) -> None:
    """Convert one baked EXR to PNG via oiiotool (see _find_oiiotool for
    why not MImage). The conversion is a LINEAR passthrough (measured:
    AO 0.5 lands on 127/128, and oiiotool's census matches it exactly).
    A corrupt EXR - what a UV-less bake writes - fails here; the caller
    turns that into the honest refusal."""
    import subprocess  # noqa: PLC0415 - only this path spawns a process

    exe = _find_oiiotool(cmds)
    creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    proc = subprocess.run([exe, src, "-o", dst], capture_output=True,
                          timeout=120, creationflags=creationflags)
    if proc.returncode != 0 or not os.path.isfile(dst):
        tail = (proc.stderr or proc.stdout or b"").decode(
            "utf-8", "replace").strip()[-400:]
        raise RuntimeError(
            "oiiotool exited %d converting %s: %s"
            % (proc.returncode, src, tail or "(no output)"))


def _make_bake_shader(cmds, map_name: str,
                      settings: Dict[str, Any]) -> str:
    base = "mcpBake_%s" % map_name
    if map_name == "ao":
        node = cmds.shadingNode("aiAmbientOcclusion", asShader=True,
                                name=naming.unique_name(cmds, base))
    elif map_name == "curvature":
        node = cmds.shadingNode("aiCurvature", asShader=True,
                                name=naming.unique_name(cmds, base))
        cmds.setAttr(node + ".output",
                     CURVATURE_OUTPUTS.index(settings["curvature_output"]))
        cmds.setAttr(node + ".radius", settings["curvature_radius"])
    else:  # world_normal
        node = cmds.shadingNode("aiUtility", asShader=True,
                                name=naming.unique_name(cmds, base))
        cmds.setAttr(node + ".shadeMode", 2)  # flat
        cmds.setAttr(node + ".colorMode", 3)  # 'n' - world-space normal
    return node


def _bake_one(cmds, shape: str, shader: str, resolution: int,
              extend_edges: bool, part_path: str) -> None:
    """Bake one (mesh, map) into `part_path` via a private empty temp dir.

    Arnold names its own output (and renames on collisions, Q4); with the
    dir private and empty, "the single EXR that appears" is unambiguous
    without ever modelling that rule.
    """
    tmpdir = tempfile.mkdtemp(prefix="mcp_meshmaps_")
    try:
        _arnold_bake(cmds, shape, tmpdir, resolution, shader, extend_edges)
        exrs = sorted(_glob.glob(os.path.join(tmpdir, "*.exr")))
        if len(exrs) != 1:
            raise HandlerError(
                "the bake of %s wrote no EXR (found %d files) - "
                "arnoldRenderToTexture returned without producing its "
                "output" % (shape, len(exrs)),
                hint="nothing was changed; check that the mesh renders at "
                     "all (maya_render_scene) and that mtoa is healthy")
        try:
            _exr_to_png(cmds, exrs[0], part_path)
        except HandlerError:
            raise
        except Exception as exc:  # noqa: BLE001 - relabelled, never laundered
            raise HandlerError(
                "the bake of %s could not be read back (%s: %s) - this is "
                "what a corrupt bake looks like (a UV-less mesh writes "
                "exactly this, MEASURED Q5)" % (shape, type(exc).__name__,
                                                exc),
                hint="nothing was changed; if the mesh has UVs, inspect "
                     "the raw output that was left at %s" % exrs[0])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _map_stats(path: str, mesh: str, map_name: str,
               warnings: List[str]) -> Dict[str, Any]:
    """Verify a bake and describe it. Missing/unreadable refuses; FLAT only
    warns - a flat map can be the honest answer here (Q3), unlike texbake's
    always-varied procedural networks."""
    uni = pngprobe.uniformity(path)
    if uni["non_uniform"] is None:
        err = HandlerError(
            "the %s bake of %s could not be measured (%s)"
            % (map_name, mesh, uni["unavailable_reason"]),
            hint="nothing was changed; the file is at %s" % path)
        # The hint promises the file for inspection, so the phase-A sweep
        # must actually leave it (the texbake keep_evidence idiom - and a
        # promise the live gate's first run caught being broken).
        err.keep_evidence = True
        raise err
    opa = pngprobe.opacity(path)
    if opa["blank"] is not False:
        # blank=True is the #765 class - a bake that drew NOTHING (every
        # pixel transparent); blank=None means it could not be measured.
        # Either way this map cannot be trusted, and unlike flatness there
        # is no honest geometry that produces it through real UVs.
        err = HandlerError(
            "the %s bake of %s drew nothing (%s)"
            % (map_name, mesh,
               opa["unavailable_reason"] or "every pixel is transparent"),
            hint="nothing was changed; the file is at %s - the usual cause "
                 "is a UV layout whose shells cover no texels" % path)
        err.keep_evidence = True
        raise err
    if not uni["non_uniform"]:
        warnings.append(
            "the %s bake of %s is flat (every pixel identical) - for ao "
            "that means nothing occludes this mesh; for concave curvature "
            "it means the geometry has no crevices at this radius. It CAN "
            "be honest, which is why this is a warning and not a refusal - "
            "but check it if you expected detail" % (map_name, mesh))
    return {"distinct_values": uni["distinct_values"],
            "pixel_count": uni["pixel_count"],
            "non_uniform": uni["non_uniform"],
            "blank": opa["blank"]}


# --------------------------------------------------------------------------
# the AO composite - pure pixel math, testable headless
# --------------------------------------------------------------------------

_SRGB_DECODE = [0.0] * 256
for _i in range(256):
    _c = _i / 255.0
    _SRGB_DECODE[_i] = (_c / 12.92 if _c <= 0.04045
                        else ((_c + 0.055) / 1.055) ** 2.4)


def _srgb_encode(linear: float) -> int:
    if linear <= 0.0:
        return 0
    if linear >= 1.0:
        return 255
    if linear <= 0.0031308:
        v = linear * 12.92
    else:
        v = 1.055 * (linear ** (1.0 / 2.4)) - 0.055
    return max(0, min(255, int(round(v * 255.0))))


def load_base_pixels(base: Dict[str, Any]) -> Dict[str, Any]:
    """Read a file base into linear-float pixels; a value base passes
    through. Kept separate from composite_ao so the math stays pure."""
    if base["kind"] == "value":
        return base
    png = pngprobe.read_png(base["path"])
    decode = ((lambda v: v / 255.0) if base.get("colorspace") == "Raw"
              else (lambda v: _SRGB_DECODE[v]))
    pixels = [(decode(p[0]), decode(p[1]), decode(p[2]))
              for p in png["pixels"]]
    return {"kind": "file_pixels", "pixels": pixels,
            "width": png["width"], "height": png["height"]}


def composite_ao(base: Dict[str, Any], ao_layers: List[Dict[str, Any]],
                 resolution: int) -> Dict[str, Any]:
    """out = srgb_encode(linear_base * ao_linear), per texel.

    The AO layers hold LINEAR values (MEASURED T1: MImage's EXR->PNG is a
    linear passthrough - 0.5 lands on 127/128), so the base is decoded to
    linear before the multiply and re-encoded after. Multiplying display
    bytes directly would double-darken every contact shadow.

    A `masked` layer applies only where its alpha is opaque - that is the
    shared-atlas case, where each wearer's unpadded bake marks its own
    shells. Texels claimed by 2+ masked layers are counted into
    `overlap_fraction` (0..1 of the claimed area): overlapping shells
    multiply twice, which is wrong exactly there, and the caller turns a
    non-zero fraction into a warning the reviewer can weigh.
    """
    n = resolution * resolution
    if base["kind"] == "value":
        rgb = base["rgb"]
        linear = [(float(rgb[0]), float(rgb[1]), float(rgb[2]))] * n
    else:
        bw, bh = base["width"], base["height"]
        src = base["pixels"]
        linear = []
        for i in range(n):
            x, y = i % resolution, i // resolution
            sx = min(bw - 1, x * bw // resolution)
            sy = min(bh - 1, y * bh // resolution)
            linear.append(src[sy * bw + sx])

    factor = [1.0] * n
    claimed = [0] * n
    for layer in ao_layers:
        lw, lh = layer["width"], layer["height"]
        px = layer["pixels"]
        masked = layer["masked"]
        for i in range(n):
            x, y = i % resolution, i // resolution
            sx = min(lw - 1, x * lw // resolution)
            sy = min(lh - 1, y * lh // resolution)
            p = px[sy * lw + sx]
            if masked:
                alpha = p[3] if len(p) > 3 else 255
                if alpha == 0:
                    continue
                claimed[i] += 1
            factor[i] *= p[0] / 255.0

    out = [(_srgb_encode(l[0] * f), _srgb_encode(l[1] * f),
            _srgb_encode(l[2] * f))
           for l, f in zip(linear, factor)]
    claimed_any = sum(1 for c in claimed if c >= 1)
    overlapped = sum(1 for c in claimed if c >= 2)
    return {"pixels": out,
            "overlap_fraction": (overlapped / claimed_any
                                 if claimed_any else 0.0)}


# --------------------------------------------------------------------------
# the rewire - texbake's measured colour-slot shape
# --------------------------------------------------------------------------


def _rewire_color(cmds, job: Dict[str, Any], final_path: str) -> str:
    """file.outColor -> material.<colorAttr>, the #714-measured shape that
    survives an FBX export. Returns the new file node."""
    base = "%s_color_ao" % job["material"]
    node = cmds.shadingNode("file", asTexture=True,
                            name=naming.unique_name(cmds, base))
    cmds.setAttr(node + ".fileTextureName", final_path, type="string")
    place = cmds.shadingNode("place2dTexture", asUtility=True,
                             name=naming.unique_name(cmds, base + "_p2d"))
    for src, dst in pbr._PLACE2D_LINKS:
        try:
            cmds.connectAttr("%s.%s" % (place, src), "%s.%s" % (node, dst),
                             force=True)
        except Exception:  # noqa: BLE001 - attribute sets differ by version
            pass
    cmds.connectAttr(node + ".outColor",
                     "%s.%s" % (job["material"], job["attr"]), force=True)
    return node


# --------------------------------------------------------------------------
# the tool
# --------------------------------------------------------------------------


def bake_mesh_maps(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    settings = validate(params, cmds)
    apply_jobs: List[Dict[str, Any]] = []
    warnings: List[str] = []
    if settings["apply_ao"]:
        apply_jobs, warnings = plan_apply(cmds, settings["meshes"])
    _ensure_mtoa(cmds)

    # Which meshes need an UNPADDED AO bake: wearers of a masked (shared)
    # composite, where alpha must keep marking the real shells (T3).
    unpadded_ao = set()
    for job in apply_jobs:
        if job["masked"]:
            for _t, shape in job["wearers"]:
                unpadded_ao.add(shape)

    # --- phase A: bake and verify, mutating NOTHING -------------------
    saved_selection = cmds.ls(selection=True) or []
    staged: List[Dict[str, Any]] = []
    attempted: List[str] = []
    try:
        for transform, shape in settings["meshes"]:
            short = transform.split("|")[-1]
            for map_name in settings["maps"]:
                shader = _make_bake_shader(cmds, map_name, settings)
                try:
                    basename = "%s_%s.png" % (short, map_name)
                    part = os.path.join(settings["out_dir"],
                                        basename + ".part.png")
                    attempted.append(part)
                    padded = not (map_name == "ao" and shape in unpadded_ao)
                    _bake_one(cmds, shape, shader, settings["resolution"],
                              padded, part)
                    stats = _map_stats(part, transform, map_name, warnings)
                    staged.append({"mesh": transform, "shape": shape,
                                   "map": map_name, "part": part,
                                   "basename": basename, "padded": padded,
                                   "stats": stats})
                finally:
                    try:
                        cmds.delete(shader)
                    except Exception:  # noqa: BLE001 - already gone is fine
                        pass
    except Exception as exc:
        # A refusal that names its part file as evidence keeps exactly
        # that file - always attempted[-1]: it was appended right before
        # the call that raised (the texbake phase-A discipline).
        keep = getattr(exc, "keep_evidence", False)
        for part in attempted:
            if keep and part == attempted[-1]:
                continue
            try:
                os.unlink(part)
            except OSError:
                pass
        raise
    finally:
        try:
            if saved_selection:
                cmds.select(saved_selection, replace=True)
            else:
                cmds.select(clear=True)
        except Exception:  # noqa: BLE001 - selection is a courtesy, not state
            pass

    # --- commit the files (still no scene mutation) -------------------
    baked: List[Dict[str, Any]] = []
    for entry in staged:
        final_path = os.path.join(settings["out_dir"], entry["basename"])
        os.replace(entry["part"], final_path)
        baked.append({"mesh": entry["mesh"], "map": entry["map"],
                      "file": final_path, "basename": entry["basename"],
                      "resolution": settings["resolution"],
                      "padded": entry["padded"], "stats": entry["stats"]})

    # --- phase B: the apply_ao composite (the only mutation) ----------
    applied: List[Dict[str, Any]] = []
    checkpoint = None
    if apply_jobs:
        ao_by_shape = {e["shape"]: e for e in staged if e["map"] == "ao"}
        checkpoint = session.auto_checkpoint("bake_mesh_maps")
        try:
            for job in apply_jobs:
                layers = []
                for _t, shape in job["wearers"]:
                    entry = ao_by_shape[shape]
                    png = pngprobe.read_png(
                        os.path.join(settings["out_dir"], entry["basename"]))
                    layers.append({"pixels": png["pixels"],
                                   "width": png["width"],
                                   "height": png["height"],
                                   "masked": job["masked"]})
                base = load_base_pixels(job["base"])
                comp = composite_ao(base, layers, settings["resolution"])
                if comp["overlap_fraction"] > 0.01:
                    warnings.append(
                        "%.1f%% of %s's composited texels are claimed by "
                        "more than one wearer's UV shells - the AO "
                        "multiplies twice there, which is wrong exactly "
                        "there; re-check the shared atlas layout"
                        % (100 * comp["overlap_fraction"], job["material"]))
                final_path = os.path.join(settings["out_dir"],
                                          job["basename"])
                pngwrite.write_png(final_path, settings["resolution"],
                                   settings["resolution"], comp["pixels"])
                node = _rewire_color(cmds, job,
                                     final_path.replace("\\", "/"))
                deleted: List[str] = []
                old = job["base"].get("file_node")
                if old:
                    doomed, kept = texbake._sweep_orphans(
                        cmds, [old], {"material": job["material"],
                                      "attr": job["attr"]})
                    deleted = doomed
                    warnings.extend(kept)
                applied.append({
                    "material": job["material"], "attr": job["attr"],
                    "file": final_path, "basename": job["basename"],
                    "file_node": node,
                    "wearers": [t for t, _s in job["wearers"]],
                    "replaced_file": job["base"].get("path"),
                    "overlap_fraction": comp["overlap_fraction"],
                    "deleted_nodes": deleted,
                })
        except Exception as exc:
            raise HandlerError(
                "the scene has been modified while compositing AO and then "
                "this happened: %s: %s - checkpoint %s has the pre-apply "
                "scene" % (type(exc).__name__, exc,
                           checkpoint["checkpoint_id"]),
                hint="call maya_restore_checkpoint(checkpoint_id=%r) to "
                     "recover" % checkpoint["checkpoint_id"]) from exc

        # Postcondition: every applied slot must now read as file-backed
        # at the composite path. A "success" that left the slot elsewhere
        # is a bug in this tool, so it raises rather than warning.
        try:
            claims = texclaim.material_claims(
                cmds, [s for _t, s in settings["meshes"]])
        except Exception as exc:  # noqa: BLE001 - labelled, scene is changed
            raise HandlerError(
                "the composite completed and the scene was modified, but "
                "the postcondition check itself could not run: %s: %s - "
                "checkpoint %s has the pre-apply scene"
                % (type(exc).__name__, exc, checkpoint["checkpoint_id"]),
                hint="call maya_restore_checkpoint(checkpoint_id=%r) to "
                     "recover" % checkpoint["checkpoint_id"]) from exc
        for done in applied:
            claim = next((c for c in claims
                          if c["material"] == done["material"]
                          and c["attr"] == done["attr"]), None)
            if claim is None or claim["classification"] != "file":
                raise HandlerError(
                    "POSTCONDITION FAILED: %s.%s does not read as "
                    "file-backed after the composite - the scene has been "
                    "modified and checkpoint %s has the pre-apply state"
                    % (done["material"], done["attr"],
                       checkpoint["checkpoint_id"]),
                    hint="maya_restore_checkpoint returns the scene; this "
                         "is a bug in maya_bake_mesh_maps, please report "
                         "the network shape")

    return {
        "meshes": [t for t, _s in settings["meshes"]],
        "out_dir": settings["out_dir"],
        "resolution": settings["resolution"],
        "maps": settings["maps"],
        "baked": baked,
        "applied": applied,
        "checkpoint_id": (checkpoint["checkpoint_id"] if checkpoint
                          else None),
        "warnings": warnings,
    }
