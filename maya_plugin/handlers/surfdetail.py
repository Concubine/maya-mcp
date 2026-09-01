"""apply_surface_detail: directed wear/grime/grain on top of a baked mesh.

#775 task 3. This is the consumer of #770's geometry-derived masks
(curvature, ao) and #775 task 2's pure pattern math (surfdetail_math):
wear and grime are colour effects composited into the material's colour
map the same way #770's AO composite is (`meshmaps._rewire_color`, same
`.part.png` -> `os.replace` commit discipline); grain is a height map
wired as a Maya bump network.

Measured facts this module is built on (#775 task 1 probe):
- file -> bump2d(bumpInterp=0) -> standardSurface.normalCamera exports
  correctly (dropped_maps empty, the PNG lands in the FBX bytes) - this
  is the HEIGHT wiring (bumpInterp=1 is the *tangent-space normal map*
  wiring `pbr.py` uses for an authored normal map; grain is not that).
  bump2d.bumpValue is a single float and refuses RGB directly, so the
  file's outAlpha drives it either way (pbr.py's measured trap).
- Colours here are LINEAR floats, the same convention `assign_material`
  and `surfdetail_math` use - never re-derive an sRGB one.
- Directional signal comes from geometry, not guesswork: wear rides the
  baked curvature map (edges wear first), grime and grain's pocket term
  ride the baked AO map INVERTED (occluded = dirty/detailed), and grain
  additionally rides curvature un-inverted (both raised edges and
  recessed pockets pick up surface grain; the flats between them do not).
- Every refusal here - unknown params, out-of-range strength/scale, a
  missing/flat/unmeasurable mask, a procedural or multi-terminal colour
  base, a shader that already carries a bump/normal network - fires
  before a single byte is written or a single node is created. The only
  mutations are inside the one `session.auto_checkpoint("apply_surface_
  detail")` block, and a failure there deletes whatever nodes this call
  itself created and names the checkpoint to restore (the meshmaps
  phase-B discipline, #770).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError, require_known_keys
from . import (meshmaps, naming, pbr, pngprobe, pngwrite, session,
              surfdetail_math, texbake, texclaim, texture_recipes)

EFFECT_KINDS = ("wear", "grime", "grain")

APPLY_SURFACE_DETAIL_KEYS = ("mesh", "maps_dir", "out_dir", "effects",
                             "resolution", "seed")
# The #764 lesson, same as meshmaps' BAKE_MESH_MAPS_SYNONYMS: the wrong
# word an agent reaches for is a plausible synonym, not a typo, and no
# string-similarity test finds "masks_dir" from "maps_dir" or "effect"
# from "effects" on its own.
APPLY_SURFACE_DETAIL_SYNONYMS = {
    "meshes": "mesh", "masks_dir": "maps_dir", "dir": "maps_dir",
    "effect": "effects"}

EFFECT_KEYS = ("kind", "strength", "scale", "color")
EFFECT_SYNONYMS = {"type": "kind", "intensity": "strength",
                   "amount": "strength", "size": "scale", "colour": "color"}

# Measured, not taste (#775 task 6 look probe). The original 0.5/0.5/0.3
# were sub-visible: on the gate's geometry the whole limb colour composite
# spanned six 8-bit levels and the render moved 1573 pixels against a
# 1173-pixel render-to-render noise floor - nothing an eye could find. A
# blind consumer asking for "wear" with no strength must get detail that
# reads, so the defaults are the smallest values the look probe found
# legible; they are ordinary art-direction settings well inside
# STRENGTH_MAX and a caller who wants subtlety can still ask for it.
DEFAULT_STRENGTH = {"wear": 2.0, "grime": 1.5, "grain": 2.0}
DEFAULT_SCALE = 1.0
DEFAULT_SEED = 0
STRENGTH_MAX = 4.0
SCALE_MAX = 16.0

# Below this fraction of texels actually touched, an effect might as well
# not have been asked for - the caller should know rather than ship a
# file that quietly does nothing.
CHANGED_FRACTION_FLOOR = 0.005

_MASK_FOR_KIND = {"wear": "curvature", "grime": "ao"}


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


# --------------------------------------------------------------------------
# validation - nothing here touches Maya beyond resolving the mesh name
# --------------------------------------------------------------------------


def _require_dir(params: Dict[str, Any], key: str, required: bool) -> Optional[str]:
    value = params.get(key)
    if value is None:
        if required:
            raise HandlerError(
                "missing required param %r" % key,
                hint="an absolute directory this tool reads/writes - there "
                     "is no default, because a guessed location is how "
                     "files get lost from a delivery")
        return None
    if not isinstance(value, str) or not value.strip():
        raise HandlerError("%s must be a non-empty string" % key,
                           hint="pass an absolute directory path")
    if not os.path.isabs(value):
        raise HandlerError(
            "%s %r must be absolute" % (key, value),
            hint="a relative path resolves against Maya's working "
                 "directory, which is not where you think it is")
    if not os.path.isdir(value):
        raise HandlerError(
            "%s %r does not exist" % (key, value),
            hint="this tool does not make directories it was not asked to "
                 "make (the export_fbx rule)")
    return value


def _validate_color(kind: str, i: int, raw: Any) -> Optional[List[float]]:
    if raw is None:
        if kind == "wear":
            return list(surfdetail_math.DEFAULT_WEAR_COLOR)
        if kind == "grime":
            return list(surfdetail_math.DEFAULT_GRIME_COLOR)
        return None  # grain has no colour slot
    if kind == "grain":
        raise HandlerError(
            "effects[%d].color is not valid for kind='grain'" % i,
            hint="grain writes a HEIGHT map, not a colour composite - "
                 "there is no colour to tint; color belongs on the "
                 "wear/grime effects instead")
    ok = (isinstance(raw, (list, tuple)) and len(raw) == 3
          and all(isinstance(c, (int, float)) and not isinstance(c, bool)
                 for c in raw)
          and all(0.0 <= c <= 1.0 for c in raw))
    if not ok:
        raise HandlerError(
            "effects[%d].color must be a 3-list of numbers in [0, 1]"
            % i, hint="stored LINEAR - the same convention "
                     "assign_material's colour params use; got %r"
                     % (raw,))
    return [float(c) for c in raw]


def _validate_effect(i: int, raw: Any, seen_kinds: set) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise HandlerError(
            "effects[%d] must be an object" % i,
            hint="each effect is {kind, strength, scale, color}")
    require_known_keys(raw, EFFECT_KEYS, "apply_surface_detail effect",
                       EFFECT_SYNONYMS)
    kind = raw.get("kind")
    if kind not in EFFECT_KINDS:
        raise HandlerError(
            "effects[%d].kind must be one of %s" % (i, ", ".join(EFFECT_KINDS)),
            hint="got %r" % (kind,))
    if kind in seen_kinds:
        raise HandlerError(
            "effects repeats kind %r" % kind,
            hint="pass at most one effect per kind")
    seen_kinds.add(kind)

    strength = raw.get("strength", DEFAULT_STRENGTH[kind])
    if (isinstance(strength, bool) or not isinstance(strength, (int, float))
            or not (0 < strength <= STRENGTH_MAX)):
        raise HandlerError(
            "effects[%d].strength must be a number in (0, %g]"
            % (i, STRENGTH_MAX),
            hint="got %r; default is wear %g, grime %g, grain %g"
                 % (strength, DEFAULT_STRENGTH["wear"], DEFAULT_STRENGTH["grime"],
                    DEFAULT_STRENGTH["grain"]))

    scale = raw.get("scale", DEFAULT_SCALE)
    if (isinstance(scale, bool) or not isinstance(scale, (int, float))
            or not (0 < scale <= SCALE_MAX)):
        raise HandlerError(
            "effects[%d].scale must be a number in (0, %g]" % (i, SCALE_MAX),
            hint="got %r; default is %g" % (scale, DEFAULT_SCALE))

    color = _validate_color(kind, i, raw.get("color"))

    return {"kind": kind, "strength": float(strength), "scale": float(scale),
            "color": color}


def validate(params: Dict[str, Any], cmds) -> Dict[str, Any]:
    """Everything checkable before a mask file is opened or a node touched."""
    require_known_keys(params, APPLY_SURFACE_DETAIL_KEYS,
                       "apply_surface_detail",
                       APPLY_SURFACE_DETAIL_SYNONYMS)

    mesh_name = params.get("mesh")
    if not isinstance(mesh_name, str) or not mesh_name.strip():
        raise HandlerError(
            "missing required param 'mesh'",
            hint="pass the single mesh to add directed detail to; "
                 "maya_get_scene_graph lists what the scene contains")
    mesh = naming.require_mesh(cmds, mesh_name)

    raw_effects = params.get("effects")
    if not isinstance(raw_effects, list) or not raw_effects:
        raise HandlerError(
            "missing required param 'effects'",
            hint="pass a non-empty list of {kind, strength, scale, color} "
                 "- valid kinds: %s" % ", ".join(EFFECT_KINDS))

    seen_kinds: set = set()
    effects = [_validate_effect(i, raw, seen_kinds)
              for i, raw in enumerate(raw_effects)]

    maps_dir = _require_dir(params, "maps_dir", required=True)
    out_dir_raw = params.get("out_dir")
    out_dir = (_require_dir(params, "out_dir", required=False)
              if out_dir_raw is not None else maps_dir)

    resolution = params.get("resolution")
    if resolution is not None:
        if (isinstance(resolution, bool) or not isinstance(resolution, int)
                or resolution not in texbake.RESOLUTIONS):
            raise HandlerError(
                "resolution must be one of %s"
                % ", ".join(str(r) for r in texbake.RESOLUTIONS),
                hint="a detail map is square; these are the sizes this "
                     "tool writes")

    seed = params.get("seed", DEFAULT_SEED)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise HandlerError("seed must be an integer", hint="got %r" % (seed,))

    return {"mesh": mesh, "effects": effects, "maps_dir": maps_dir,
            "out_dir": out_dir, "resolution": resolution, "seed": seed}


# --------------------------------------------------------------------------
# mask resolution - file I/O only, no Maya; pure enough to unit-test alone
# --------------------------------------------------------------------------


def _load_mask(maps_dir: str, short: str, kind: str) -> Dict[str, Any]:
    basename = "%s_%s.png" % (short, kind)
    path = os.path.join(maps_dir, basename)
    if not os.path.isfile(path):
        raise HandlerError(
            "%s does not exist" % path,
            hint="maya_bake_mesh_maps bakes %s maps from geometry; bake "
                 "it for %s before calling apply_surface_detail"
                 % (kind, short))
    uni = pngprobe.uniformity(path)
    if uni["non_uniform"] is None:
        raise HandlerError(
            "%s could not be measured (%s)" % (path, uni["unavailable_reason"]),
            hint="the file may be corrupt or an unsupported PNG shape; "
                 "re-bake it with maya_bake_mesh_maps")
    if not uni["non_uniform"]:
        raise HandlerError(
            "%s is flat (distinct_values=%d) - there is no directional "
            "signal to drive %s from" % (path, uni["distinct_values"], kind),
            hint="re-bake with maya_bake_mesh_maps at a mesh/radius that "
                 "actually varies, or drop the effect that needs it")
    return pngprobe.read_png(path)


def _resolve_masks(mesh: Tuple[str, str], effects: List[Dict[str, Any]],
                   maps_dir: str,
                   resolution: Optional[int]) -> Tuple[Dict[str, Any], int]:
    """Which mask PNGs this call needs, loaded and verified; and the
    resolution to render at (given, or the mask width when it was not)."""
    transform, _shape = mesh
    short = transform.split("|")[-1]
    kinds = {e["kind"] for e in effects}
    need_curv = "wear" in kinds or "grain" in kinds
    need_ao = "grime" in kinds or "grain" in kinds

    curv_png = _load_mask(maps_dir, short, "curvature") if need_curv else None
    ao_png = _load_mask(maps_dir, short, "ao") if need_ao else None

    if resolution is None:
        if "grain" in kinds:
            if (curv_png["width"] != ao_png["width"]
                    or curv_png["height"] != ao_png["height"]):
                raise HandlerError(
                    "the grain masks disagree in size: %s_curvature.png "
                    "is %dx%d but %s_ao.png is %dx%d"
                    % (short, curv_png["width"], curv_png["height"], short,
                       ao_png["width"], ao_png["height"]),
                    hint="re-bake both with the same maya_bake_mesh_maps "
                         "resolution, or pass resolution= explicitly")
            resolution = curv_png["width"]
        elif curv_png is not None:
            resolution = curv_png["width"]
        else:
            resolution = ao_png["width"]

    return {"curvature": curv_png, "ao": ao_png}, resolution


# --------------------------------------------------------------------------
# pattern assembly - pure math, no Maya, no file I/O
# --------------------------------------------------------------------------


def _build_effects(effects: List[Dict[str, Any]], masks: Dict[str, Any],
                   resolution: int, seed: int
                   ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Turn validated effect params + loaded mask PNGs into what
    surfdetail_math needs: colour effects for `composite_detail`, and a
    grain bundle for the height loop below. No mutation, no file I/O."""
    curv_field = (surfdetail_math.mask_values(masks["curvature"], invert=False)
                 if masks["curvature"] is not None else None)
    # Inverted: a baked AO map is bright where lit/convex, dark where
    # occluded - grime and grain's pocket term want the OPPOSITE, high
    # where geometry is occluded (a crevice, a seam, an inside corner).
    ao_inv_field = (surfdetail_math.mask_values(masks["ao"], invert=True)
                    if masks["ao"] is not None else None)

    color_effects: List[Dict[str, Any]] = []
    grain: Optional[Dict[str, Any]] = None
    for e in effects:
        if e["kind"] == "wear":
            color_effects.append({
                "kind": "wear",
                "pattern": surfdetail_math.wear_pattern(resolution, e["scale"],
                                                        seed),
                "mask": curv_field,
                "strength": e["strength"],
                "color_linear": tuple(e["color"]),
            })
        elif e["kind"] == "grime":
            color_effects.append({
                "kind": "grime",
                "pattern": surfdetail_math.grime_pattern(resolution, e["scale"],
                                                          seed),
                "mask": ao_inv_field,
                "strength": e["strength"],
                "color_linear": tuple(e["color"]),
            })
        else:  # grain
            grain = {
                "height_field": surfdetail_math.height_pattern(
                    resolution, e["scale"], seed),
                "curv": curv_field,
                "ao_inv": ao_inv_field,
                "strength": e["strength"],
            }
    return color_effects, grain


def _base_linear(base: Dict[str, Any],
                 resolution: int) -> List[Tuple[float, float, float]]:
    """The colour base (a flat value, or a loaded file's pixels) resampled
    to `resolution`x`resolution` linear floats - meshmaps.composite_ao's
    own base-sampling loop, reused verbatim because composite_detail wants
    exactly this shape."""
    n = resolution * resolution
    if base["kind"] == "value":
        rgb = base["rgb"]
        return [(float(rgb[0]), float(rgb[1]), float(rgb[2]))] * n
    bw, bh = base["width"], base["height"]
    src = base["pixels"]
    out = []
    for i in range(n):
        x, y = i % resolution, i // resolution
        sx = min(bw - 1, x * bw // resolution)
        sy = min(bh - 1, y * bh // resolution)
        out.append(src[sy * bw + sx])
    return out


def _grain_pixels(grain: Dict[str, Any],
                  resolution: int) -> Tuple[List[Tuple[int, int, int]], float]:
    """v = height_pattern * (0.5*curvature + 0.5*ao_inv), per texel,
    written grayscale. `strength` is NOT folded in here - it becomes the
    bump2d's bumpDepth instead (the measured Task 1 shape), not a
    pixel-value multiplier."""
    n = resolution * resolution
    pixels: List[Tuple[int, int, int]] = []
    nonzero = 0
    for i in range(n):
        x, y = i % resolution, i // resolution
        v = surfdetail_math.sample(grain["height_field"], x, y, resolution) * (
            0.5 * surfdetail_math.sample(grain["curv"], x, y, resolution)
            + 0.5 * surfdetail_math.sample(grain["ao_inv"], x, y, resolution))
        v = max(0.0, min(1.0, v))
        b = int(round(v * 255))
        if b > 0:
            nonzero += 1
        pixels.append((b, b, b))
    return pixels, nonzero / float(n)


# --------------------------------------------------------------------------
# the tool
# --------------------------------------------------------------------------


def apply_surface_detail(params: Dict[str, Any]) -> Dict[str, Any]:
    # Ahead of _cmds(): an unknown key needs no Maya to answer (#767).
    # validate() guards again - it is the seam the headless tests drive.
    require_known_keys(params, APPLY_SURFACE_DETAIL_KEYS,
                       "apply_surface_detail", APPLY_SURFACE_DETAIL_SYNONYMS)
    cmds = _cmds()
    settings = validate(params, cmds)
    mesh = settings["mesh"]
    transform, shape = mesh
    effects = settings["effects"]

    masks, resolution = _resolve_masks(mesh, effects, settings["maps_dir"],
                                       settings["resolution"])

    color_effects_cfg = [e for e in effects if e["kind"] in ("wear", "grime")]
    grain_cfg = next((e for e in effects if e["kind"] == "grain"), None)

    # --- planning: every refusal below fires before any file/scene touch --
    warnings: List[str] = []
    color_job: Optional[Dict[str, Any]] = None
    shader: Optional[str] = None
    if color_effects_cfg:
        jobs, plan_warnings = meshmaps.plan_apply(cmds, [mesh])
        color_job = jobs[0]
        warnings.extend(plan_warnings)
        shader = color_job["material"]

    if grain_cfg is not None:
        if shader is None:
            shader, _stype = texture_recipes._shader_of(cmds, shape)
        existing = cmds.listConnections("%s.normalCamera" % shader,
                                        source=True, destination=False)
        if existing:
            raise HandlerError(
                "%s.normalCamera already carries a bump/normal network - "
                "this tool will not stack them" % shader,
                hint="bake the existing network into the colour/normal map "
                     "first (maya_bake_textures), or remove it, before "
                     "adding grain")

    # --- pure computation: still no mutation ------------------------------
    color_built, grain_built = _build_effects(effects, masks, resolution,
                                              settings["seed"])

    changed: Dict[str, float] = {}
    color_pixels = None
    if color_effects_cfg:
        base_linear = _base_linear(meshmaps.load_base_pixels(color_job["base"]),
                                   resolution)
        comp = surfdetail_math.composite_detail(base_linear, color_built,
                                                resolution)
        color_pixels = comp["pixels"]
        changed.update(comp["changed"])

    height_pixels = None
    if grain_built is not None:
        height_pixels, grain_changed = _grain_pixels(grain_built, resolution)
        changed["grain"] = grain_changed

    effects_result = []
    for e in effects:
        frac = changed.get(e["kind"], 0.0)
        if frac < CHANGED_FRACTION_FLOOR:
            warnings.append(
                "%s strength/scale produced almost nothing "
                "(changed_fraction=%.4f)" % (e["kind"], frac))
        effects_result.append({"kind": e["kind"], "strength": e["strength"],
                               "scale": e["scale"], "changed_fraction": frac})

    # --- the only mutation, all under one checkpoint -----------------------
    checkpoint = session.auto_checkpoint("apply_surface_detail")
    created_nodes: List[str] = []
    color_file = color_basename = None
    height_file = height_basename = None
    try:
        if color_pixels is not None:
            color_basename = "%s_color_detail.png" % color_job["material"]
            color_file = os.path.join(settings["out_dir"], color_basename)
            # F2 (#775 fix wave): re-applying to the same material resolves
            # its own previous composite as the base (meshmaps.plan_apply
            # reads whatever the colour slot is now wired to) and is about
            # to write over that exact path. The ORIGINAL input is never
            # touched, but THIS file is - and a same-kind re-apply on top
            # of it compounds rather than starting fresh, so say so.
            prior_path = (color_job["base"].get("path") or "").replace(
                "\\", "/")
            if prior_path == color_file.replace("\\", "/"):
                warnings.append(
                    "%s is already %s's colour base and is about to be "
                    "replaced by this composite - the previous composite "
                    "is being overwritten, and detail will compound if "
                    "the same effect kind is re-applied here again"
                    % (color_basename, color_job["material"]))
            part = os.path.join(settings["out_dir"],
                                color_basename + ".part.png")
            pngwrite.write_png(part, resolution, resolution, color_pixels)
            os.replace(part, color_file)
            node = meshmaps._rewire_color(cmds, color_job,
                                          color_file.replace("\\", "/"),
                                          suffix="color_detail")
            created_nodes.append(node)
            for c in (cmds.listConnections(node, source=True,
                                          destination=False) or []):
                if cmds.nodeType(c) == "place2dTexture":
                    created_nodes.append(c)
            old = color_job["base"].get("file_node")
            if old:
                doomed, kept = texbake._sweep_orphans(
                    cmds, [old], {"material": color_job["material"],
                                  "attr": color_job["attr"]})
                warnings.extend(kept)

        if height_pixels is not None:
            short = transform.split("|")[-1]
            height_basename = "%s_height.png" % short
            height_file = os.path.join(settings["out_dir"], height_basename)
            part = os.path.join(settings["out_dir"],
                                height_basename + ".part.png")
            pngwrite.write_png(part, resolution, resolution, height_pixels)
            os.replace(part, height_file)

            fnode = cmds.shadingNode(
                "file", asTexture=True,
                name=naming.unique_name(cmds, "%s_height_tex" % short))
            created_nodes.append(fnode)
            cmds.setAttr(fnode + ".fileTextureName",
                         height_file.replace("\\", "/"), type="string")
            # Data, not colour - same reasoning as pbr.py's normal/mask maps.
            cmds.setAttr(fnode + ".colorSpace", "Raw", type="string")
            cmds.setAttr(fnode + ".ignoreColorSpaceFileRules", True)
            # WITHOUT THIS THE WHOLE BUMP NETWORK IS INERT (#775 task 6,
            # measured live). pngwrite emits RGB with no alpha channel, and
            # a Maya `file` node then returns a CONSTANT outAlpha of 1.0 -
            # so bump2d, which reads the height from outAlpha (below), sees
            # one flat value at every texel and perturbs no normal at any
            # bumpDepth. Measured on the live gate's limb at 1024: bumpDepth
            # 2.0 and 4.0 rendered identically (1972 / 1977 pixels moved
            # against a 2011-pixel noise floor); flipping ONLY this flag on
            # the same node took it to 85734 pixels moved and the limb
            # rendered as unmistakable relief. alphaIsLuminance makes the
            # file synthesise outAlpha from the image's luminance, which is
            # exactly what a grayscale height map carries.
            cmds.setAttr(fnode + ".alphaIsLuminance", True)

            place = cmds.shadingNode(
                "place2dTexture", asUtility=True,
                name=naming.unique_name(cmds, "%s_height_p2d" % short))
            created_nodes.append(place)
            for src, dst in pbr._PLACE2D_LINKS:
                try:
                    cmds.connectAttr("%s.%s" % (place, src),
                                     "%s.%s" % (fnode, dst), force=True)
                except Exception:  # noqa: BLE001 - attr sets differ by version
                    pass

            bump = cmds.shadingNode(
                "bump2d", asUtility=True,
                name=naming.unique_name(cmds, "%s_height_bump" % short))
            created_nodes.append(bump)
            cmds.setAttr(bump + ".bumpInterp", 0)  # 0 = height (not normal map)
            cmds.setAttr(bump + ".bumpDepth", grain_cfg["strength"])
            # outAlpha, not outColor: bumpValue is a single float (measured
            # trap, pbr.py) - Maya reads the height from the alpha plug.
            cmds.connectAttr(fnode + ".outAlpha", bump + ".bumpValue",
                             force=True)
            cmds.connectAttr(bump + ".outNormal", "%s.normalCamera" % shader,
                             force=True)
    except Exception as exc:
        for node in reversed(created_nodes):
            try:
                cmds.delete(node)
            except Exception:  # noqa: BLE001 - already gone is fine
                pass
        raise HandlerError(
            "the scene has been modified while applying surface detail and "
            "then this happened: %s: %s - checkpoint %s has the pre-apply "
            "scene" % (type(exc).__name__, exc, checkpoint["checkpoint_id"]),
            hint="call maya_restore_checkpoint(checkpoint_id=%r) to "
                 "recover" % checkpoint["checkpoint_id"]) from exc

    # Postcondition (colour only): the slot must now read as file-backed
    # at the new composite - a "success" that left it elsewhere is a bug
    # in this tool, so it raises rather than warning (the meshmaps idiom).
    if color_pixels is not None:
        try:
            claims = texclaim.material_claims(cmds, [shape])
        except Exception as exc:  # noqa: BLE001 - labelled, scene is changed
            raise HandlerError(
                "surface detail was applied and the scene was modified, "
                "but the postcondition check itself could not run: %s: %s "
                "- checkpoint %s has the pre-apply scene"
                % (type(exc).__name__, exc, checkpoint["checkpoint_id"]),
                hint="call maya_restore_checkpoint(checkpoint_id=%r) to "
                     "recover" % checkpoint["checkpoint_id"]) from exc
        claim = next((c for c in claims
                      if c["material"] == color_job["material"]
                      and c["attr"] == color_job["attr"]), None)
        if claim is None or claim["classification"] != "file":
            raise HandlerError(
                "POSTCONDITION FAILED: %s.%s does not read as file-backed "
                "after the composite - the scene has been modified and "
                "checkpoint %s has the pre-apply state"
                % (color_job["material"], color_job["attr"],
                   checkpoint["checkpoint_id"]),
                hint="maya_restore_checkpoint returns the scene; this is a "
                     "bug in apply_surface_detail, please report the "
                     "network shape")

    return {
        "mesh": transform,
        "effects": effects_result,
        "color_file": color_file,
        "color_basename": color_basename,
        "height_file": height_file,
        "height_basename": height_basename,
        "file_nodes": created_nodes,
        "checkpoint_id": checkpoint["checkpoint_id"],
        "warnings": warnings,
    }
