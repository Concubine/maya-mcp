"""setup_lighting: preset rigs (design doc 5.4).

"A model can't be judged unlit; M2 blocks on this."

This is the only destructive tool in M2: replace_existing=True deletes
user-authored nodes, so it auto-checkpoints - AFTER validation, so a refused
call never burns one (the correction M1 made to sculpt_ops/remesh).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError
from . import naming

PRESETS = ("three_point", "single_sun", "hdri", "environment")

# Arnold's lights are their own node types and do NOT reliably answer
# cmds.ls(lights=True) or ls(type="light"). Every place that asks "what is
# lighting this scene" has to ask for these too, or a scene lit entirely by a
# dome reads as unlit - which would have render_scene add a fallback key on top
# of it and setup_lighting's replace_existing leave the old dome behind.
ARNOLD_LIGHT_TYPES = ("aiSkyDomeLight", "aiAreaLight", "aiPhotometricLight",
                      "aiMeshLight", "aiLightPortal")

# A dome is the environment, not a lamp: swinging it to follow the camera would
# rotate the world's reflections shot to shot, which is the opposite of what an
# environment is for.
OMNIDIRECTIONAL_LIGHT_TYPES = ("aiSkyDomeLight",)

# A neutral studio dome: sky above, ground below, and a horizon between them.
# A FLAT grey dome lights a metal evenly and it still reads as grey paint - the
# horizon line is what makes a mirror surface legible as a mirror.
DEFAULT_SKY = (0.55, 0.62, 0.72)
DEFAULT_GROUND = (0.18, 0.16, 0.15)

# aiSkyDomeLight.format: 0 = mirrored ball, 1 = angular, 2 = latlong. Every HDRI
# a caller is likely to own is latlong, and the default is not.
_LATLONG = 2

# (suffix, intensity multiplier, rotate) - a conventional key/fill/rim rig.
_THREE_POINT = (
    ("key", 1.0, [-35.0, 30.0, 0.0]),
    ("fill", 0.35, [-15.0, -55.0, 0.0]),
    ("rim", 0.7, [-10.0, 165.0, 0.0]),
)
_SINGLE_SUN = (("sun", 1.0, [-45.0, 25.0, 0.0]),)

# Arnold's distant light spreads its energy over the hemisphere the surface can
# see, so a lambert facing it at intensity 1.0 returns albedo/pi, not albedo.
# VP2 does the same - both measured on a linear-0.5 plane at N.L = 1, which
# reads its own albedo only at intensity pi (redmine #617).
#
# Carrying the factor here makes `intensity` a UNIT: 1.0 is a fully-lit
# surface, 0.5 is visibly dim, 2.0 is deliberately hot. Before this, "1.0"
# delivered 32% of a lit surface and named nothing, so every caller dialled in
# its own number by eye - 1.2, 1.5, 2.1, 3.0, 3.2, 4.0, 16.0 across the evals,
# no two agreeing, each also compensating for the #615 gamma bug.
#
# A sky dome does NOT get this: a hemisphere of uniform luminance already
# integrates to albedo * L. Measured, environment at 1.0 lights the plane to
# ~122 where a pi-divided dome would be ~88.
FULLY_LIT = math.pi


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _auto_checkpoint(reason: str):
    from . import session  # noqa: PLC0415 - avoid an import cycle

    return session.auto_checkpoint(reason)


def light_shapes(cmds) -> List[str]:
    """Every shape that lights the scene, Maya's and Arnold's alike.

    Shared with render.py, because "is this scene lit?" and "which lights are
    mine to swing?" must answer the same way this does - an Arnold dome that
    only one of them can see is worse than one neither can.
    """
    found: List[str] = []
    for query in (("light",),) + tuple((t,) for t in ARNOLD_LIGHT_TYPES):
        try:
            shapes = cmds.ls(type=query[0], long=True) or []
        except Exception:
            continue  # node type unknown in this Maya (mtoa absent)
        for shape in shapes:
            if shape not in found:
                found.append(shape)
    return found


def _existing_light_transforms(cmds) -> List[str]:
    """Transforms that own a light shape - and nothing else.

    Deliberately derived from the node types, not from a selection or a naming
    convention: this list is about to be deleted.
    """
    out: List[str] = []
    for shape in light_shapes(cmds):
        parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
        for parent in parents:
            if parent not in out:
                out.append(parent)
    return out


def _sweep(cmds, nodes: List[str]) -> None:
    """Delete every node in `nodes` that still exists.

    Used to clean up a partially-built rig on any failure path, so a raise
    never leaves orphans behind - the house pattern from etch.py's
    _TYPE_NODE_TYPES sweep, adapted here to a plain created-node list since
    _build/_build_hdri create only nodes they name directly.
    """
    for node in nodes:
        if cmds.objExists(node):
            try:
                cmds.delete(node)
            except Exception:
                pass


def _build(cmds, prefix: str, specs, intensity: float) -> List[str]:
    created: List[str] = []
    try:
        for suffix, factor, rotate in specs:
            name = naming.unique_name(cmds, "%s_%s" % (prefix, suffix))
            shape = cmds.directionalLight(
                name=name, intensity=intensity * factor * FULLY_LIT)
            parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
            transform = parents[0] if parents else shape
            created.append(transform)
            cmds.xform(transform, rotation=rotate, worldSpace=True)
    except Exception:
        _sweep(cmds, created)
        raise
    return created


def setup_lighting(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    preset = params.get("preset")
    if preset not in PRESETS:
        raise HandlerError(
            "unknown lighting preset %r" % preset,
            hint="valid presets: %s" % ", ".join(PRESETS),
        )
    intensity = params.get("intensity", 1.0)
    if (
        not isinstance(intensity, (int, float)) or isinstance(intensity, bool)
        or not (0.0 < intensity <= 20.0)
    ):
        raise HandlerError(
            "intensity must be a number in (0, 20]",
            hint="got %r; 1.0 is the neutral default" % (intensity,),
        )
    hdri_path = params.get("hdri_path")
    if preset == "hdri" and not hdri_path:
        raise HandlerError(
            "the hdri preset requires hdri_path",
            hint="maya-mcp bundles no HDRI (they are large and separately "
            "licensed) - pass an absolute path to your own .hdr/.exr, or use "
            "preset='environment' for a neutral studio dome that needs no file",
        )
    replace_existing = params.get("replace_existing", True) is not False

    # Everything above is validation; only now is it safe to spend a
    # checkpoint or delete anything.
    checkpoint_id: Optional[str] = None
    removed: List[str] = []
    warnings: List[str] = []
    if replace_existing:
        existing = _existing_light_transforms(cmds)
        if existing:
            info = _auto_checkpoint("lighting")
            checkpoint_id = (info or {}).get("checkpoint_id")
            removed, warnings = _replace_existing_lights(cmds, existing)

    if preset == "three_point":
        lights = _build(cmds, "mcpLight", _THREE_POINT, float(intensity))
    elif preset == "single_sun":
        lights = _build(cmds, "mcpLight", _SINGLE_SUN, float(intensity))
    else:
        lights, dome_warnings = _build_dome(
            cmds, float(intensity),
            hdri_path=str(hdri_path) if hdri_path else None,
        )
        warnings.extend(dome_warnings)

    return {
        "preset": preset,
        "lights": lights,
        "removed": removed,
        "checkpoint_id": checkpoint_id,
        "warnings": warnings,
    }


def _replace_existing_lights(cmds, transforms: List[str]) -> Tuple[List[str], List[str]]:
    """Remove prior lights, deleting a transform ONLY when it's left empty.

    Deleting a transform in Maya deletes its whole subtree - every shape on
    it and every node parented under it. So this never deletes a transform
    directly: it deletes the light shape(s) first, then removes the
    transform only if that leaves it holding nothing else (no other shape,
    no child node). A transform that also carries a mesh, or has a locator
    (or anything) parented under it, survives - callers find out via the
    returned warnings.
    """
    removed: List[str] = []
    warnings: List[str] = []
    for transform in transforms:
        if not cmds.objExists(transform):
            continue
        short = transform.split("|")[-1]
        # Filtered against the set we already found rather than by type="light",
        # which does not match Arnold's own light nodes - a dome would survive
        # replace_existing and quietly double the lighting of the next rig.
        lit = set(light_shapes(cmds))
        under = cmds.listRelatives(transform, shapes=True, fullPath=True) or []
        for shape in [s for s in under if s in lit]:
            if cmds.objExists(shape):
                cmds.delete(shape)
        remaining = cmds.listRelatives(transform, children=True, fullPath=True) or []
        if remaining:
            kept = ", ".join(n.split("|")[-1] for n in remaining)
            warnings.append(
                "kept %s: still holds %s after its light was removed"
                % (short, kept)
            )
            continue
        cmds.delete(transform)
        removed.append(short)
    return removed, warnings


def _arnold_available(cmds) -> bool:
    """Is aiSkyDomeLight buildable? Loads mtoa if it is merely not loaded yet.

    Same shape as render._ensure_renderer, and for the same reason: a cold Maya
    has mtoa installed and unloaded, and making the caller load a plugin to use
    the tool's own preset is a defect, not their mistake.
    """
    try:
        if cmds.pluginInfo("mtoa", query=True, loaded=True):
            return True
    except Exception:
        pass
    try:
        cmds.loadPlugin("mtoa", quiet=True)
    except Exception:
        return False
    try:
        return bool(cmds.pluginInfo("mtoa", query=True, loaded=True))
    except Exception:
        return False


def _build_dome(
    cmds, intensity: float, hdri_path: Optional[str] = None,
    sky=DEFAULT_SKY, ground=DEFAULT_GROUND,
) -> Tuple[List[str], List[str]]:
    """A real environment: a dome the whole scene sits inside.

    This is the tool's answer to a measured failure. metalness = 1.0 renders
    BLACK in a three-point rig, because a full metal has no diffuse response and
    three directional lights give it nothing to reflect - so the kit's steel was
    being judged in a rig that physically cannot show it. Directional lights
    cannot fix that at any intensity; only an environment can.

    The previous hdri preset was a directional light with a file texture on its
    colour. That is a coloured lamp, not image-based lighting: it lights one
    side and reflects nothing. It survives here only as the fallback for a Maya
    without Arnold, and it says so out loud.
    """
    created: List[str] = []
    warnings: List[str] = []
    try:
        if not _arnold_available(cmds):
            name = naming.unique_name(cmds, "mcpLight_domeFallback")
            # The factor, so a Maya without mtoa does not render three times
            # darker than one with it for the same call (#617).
            shape = cmds.directionalLight(name=name, intensity=intensity * FULLY_LIT)
            parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
            transform = parents[0] if parents else shape
            created.append(transform)
            if hdri_path:
                tex = cmds.shadingNode(
                    "file", asTexture=True,
                    name=naming.unique_name(cmds, "mcpLight_domeTex"))
                created.append(tex)
                cmds.setAttr(tex + ".fileTextureName", hdri_path, type="string")
                cmds.connectAttr(tex + ".outColor", shape + ".color", force=True)
            warnings.append(
                "Arnold is unavailable, so this is a DIRECTIONAL light standing "
                "in for a dome. It lights one side and reflects nothing: a "
                "metallic material will still render black or flat. Install/load "
                "mtoa, and render with renderer='arnold'."
            )
            return created[:1], warnings

        # shadingNode(asLight=True), NOT createNode. createNode builds the node
        # and stops there: the dome then draws as background and illuminates
        # NOTHING. Measured in a live Maya (#601 run) - a plain 50%-grey sphere
        # under a createNode dome renders pure black while the dome's own sky
        # blows out behind it, at intensity 1.0 and 4.0 alike, and setting
        # colour, defaultLightSet membership and the lightList connection
        # afterwards fixes none of it. A light has to be BUILT as a light.
        # This preset is the tool's own answer to metalness rendering black, so
        # the bug silently voided the fix it exists to provide.
        node = cmds.shadingNode(
            "aiSkyDomeLight", asLight=True,
            name=naming.unique_name(cmds, "mcpLight_domeShape"))
        # Maya hands back the shape here and the auto-created transform there,
        # depending on version. Normalise rather than trust either.
        if cmds.nodeType(node) == "aiSkyDomeLight":
            shape = node
            parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
            transform = parents[0] if parents else node
        else:
            transform = node
            shape = (cmds.listRelatives(node, shapes=True, fullPath=True)
                     or [node])[0]
        created.append(transform)
        transform = cmds.rename(transform, naming.unique_name(cmds, "mcpLight_dome"))
        created[0] = transform
        shape = (cmds.listRelatives(transform, shapes=True, fullPath=True)
                 or [shape])[0]
        cmds.setAttr(shape + ".intensity", intensity)

        if hdri_path:
            tex = cmds.shadingNode(
                "file", asTexture=True,
                name=naming.unique_name(cmds, "mcpLight_domeTex"))
            created.append(tex)
            cmds.setAttr(tex + ".fileTextureName", hdri_path, type="string")
            # An HDRI is lighting data, not a picture: an sRGB curve on it
            # changes every reflection and every bounce.
            for attr, value, kwargs in (
                (".colorSpace", "Raw", {"type": "string"}),
                (".ignoreColorSpaceFileRules", True, {}),
            ):
                try:
                    cmds.setAttr(tex + attr, value, **kwargs)
                except Exception:
                    pass
            cmds.setAttr(shape + ".format", _LATLONG)
            cmds.connectAttr(tex + ".outColor", shape + ".color", force=True)
        else:
            # A V ramp: ground at the bottom, sky at the top, horizon between.
            ramp = cmds.shadingNode(
                "ramp", asTexture=True,
                name=naming.unique_name(cmds, "mcpLight_domeRamp"))
            created.append(ramp)
            cmds.setAttr(ramp + ".type", 0)  # 0 = V ramp
            cmds.setAttr(ramp + ".interpolation", 1)  # linear
            cmds.setAttr(ramp + ".colorEntryList[0].position", 0.0)
            cmds.setAttr(ramp + ".colorEntryList[0].color", *ground, type="double3")
            cmds.setAttr(ramp + ".colorEntryList[1].position", 0.5)
            cmds.setAttr(ramp + ".colorEntryList[1].color", *ground, type="double3")
            cmds.setAttr(ramp + ".colorEntryList[2].position", 0.52)
            cmds.setAttr(ramp + ".colorEntryList[2].color", *sky, type="double3")
            cmds.setAttr(ramp + ".colorEntryList[3].position", 1.0)
            cmds.setAttr(ramp + ".colorEntryList[3].color", *sky, type="double3")
            cmds.setAttr(shape + ".format", _LATLONG)
            cmds.connectAttr(ramp + ".outColor", shape + ".color", force=True)
    except Exception:
        _sweep(cmds, created)
        raise
    return created[:1], warnings
