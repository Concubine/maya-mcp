"""Named texture recipes (design doc 5.4, narrowed).

The doc specifies an arbitrary NodeSpec DAG. That is deferred: it is the
largest single item in M2 and hard to test meaningfully without real usage
showing which nodes matter. A small set of validated recipes covers most
genuine need at a fraction of the surface area; the general builder lands
later, informed by which recipes people actually reach for.

Every node a recipe creates is tracked, so any failure sweeps exactly those
nodes and nothing else - the etch_text finally pattern from M1.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from ..dispatcher import HandlerError
from . import material, naming

RECIPES = ("noise_bump", "ramp_gradient", "layered_mask", "file_texture")
# Which semantic slot each recipe drives.
RECIPE_SLOT = {
    "noise_bump": "normal",
    "ramp_gradient": "color",
    "layered_mask": "color",
    "file_texture": "color",
}


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _shader_of(cmds, shape: str):
    """The shader node feeding this shape, and its type."""
    sgs = cmds.listSets(object=shape, type=1) or []
    if not sgs:
        raise HandlerError(
            "%s has no shading group" % shape,
            hint="call maya_assign_material first - a texture needs a shader "
            "to connect to",
        )
    # Query the .surfaceShader plug specifically (same idiom as
    # objinfo.py/scene.py's material lookup) rather than an unfiltered
    # cmds.listConnections(sgs[0], type=None): passing an explicit type=None
    # to real Maya's listConnections raises "RuntimeError: -t expects type
    # STRING" (verified live, Maya 2027) even though fake-cmds tolerates it.
    shaders = cmds.listConnections(sgs[0] + ".surfaceShader", source=True) or []
    if not shaders:
        raise HandlerError(
            "shading group %s has no shader" % sgs[0],
            hint="call maya_assign_material first",
        )
    shader = shaders[0]
    return shader, cmds.nodeType(shader)


def _validate_number(name: str, value: Any) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise HandlerError(
            "%s must be a number" % name, hint="got %r" % (value,)
        )
    return float(value)


def _noise_bump(cmds, tracker, shader, attr, params) -> None:
    scale = _validate_number("scale", params.get("scale", 1.0))
    depth = _validate_number("depth", params.get("depth", 0.4))
    noise = tracker(cmds.shadingNode("noise", asTexture=True,
                                     name=naming.unique_name(cmds, "mcpTex_noise")))
    bump = tracker(cmds.shadingNode("bump2d", asUtility=True,
                                    name=naming.unique_name(cmds, "mcpTex_bump")))
    cmds.setAttr(noise + ".frequency", 8.0 * scale)
    cmds.setAttr(bump + ".bumpDepth", depth)
    cmds.connectAttr(noise + ".outColorR", bump + ".bumpValue", force=True)
    cmds.connectAttr(bump + ".outNormal", "%s.%s" % (shader, attr), force=True)


def _ramp_gradient(cmds, tracker, shader, attr, params) -> None:
    ramp = tracker(cmds.shadingNode("ramp", asTexture=True,
                                    name=naming.unique_name(cmds, "mcpTex_ramp")))
    cmds.connectAttr(ramp + ".outColor", "%s.%s" % (shader, attr), force=True)


def _layered_mask(cmds, tracker, shader, attr, params) -> None:
    layered = tracker(cmds.shadingNode(
        "layeredTexture", asTexture=True,
        name=naming.unique_name(cmds, "mcpTex_layered")))
    mask = tracker(cmds.shadingNode(
        "noise", asTexture=True, name=naming.unique_name(cmds, "mcpTex_mask")))
    cmds.connectAttr(mask + ".outAlpha", layered + ".inputs[0].alpha", force=True)
    cmds.connectAttr(layered + ".outColor", "%s.%s" % (shader, attr), force=True)


def _file_texture(cmds, tracker, shader, attr, params) -> None:
    path = params.get("file_path")
    if not path:
        raise HandlerError(
            "the file_texture recipe requires file_path",
            hint="pass an absolute path to an image file",
        )
    node = tracker(cmds.shadingNode("file", asTexture=True,
                                    name=naming.unique_name(cmds, "mcpTex_file")))
    cmds.setAttr(node + ".fileTextureName", str(path), type="string")
    cmds.connectAttr(node + ".outColor", "%s.%s" % (shader, attr), force=True)


_BUILDERS: Dict[str, Callable] = {
    "noise_bump": _noise_bump,
    "ramp_gradient": _ramp_gradient,
    "layered_mask": _layered_mask,
    "file_texture": _file_texture,
}


def apply_texture_recipe(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    mesh_long, shape = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    recipe = params.get("recipe")
    if recipe not in RECIPES:
        raise HandlerError(
            "unknown recipe %r" % recipe,
            hint="valid recipes: %s" % ", ".join(RECIPES),
        )
    shader, shader_type = _shader_of(cmds, shape)
    slot = params.get("slot") or RECIPE_SLOT[recipe]
    attr = material.resolve_slot(shader_type, slot)

    created: List[str] = []

    def tracker(node: str) -> str:
        created.append(node)
        return node

    try:
        _BUILDERS[recipe](cmds, tracker, shader, attr, params.get("params") or {})
    except Exception:
        # zero orphans: sweep exactly what this call built, nothing else
        for node in reversed(created):
            if cmds.objExists(node):
                try:
                    cmds.delete(node)
                except Exception:
                    pass
        raise

    warnings: List[str] = []
    if recipe != "file_texture":
        warnings.append(
            "this recipe builds a procedural network that Maya's FBX "
            "exporter silently drops - maya_export_fbx reports it in "
            "textures.dropped_maps; use file textures (maya_assign_pbr or "
            "the file_texture recipe) for anything that must survive export")

    return {
        "mesh": mesh_long,
        "recipe": recipe,
        "slot": slot,
        "nodes": created,
        "warnings": warnings,
    }
